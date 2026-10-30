"""Code-enforced provenance/completeness, not an evaluation of LLM scientific judgment."""
import copy
import json
from pathlib import Path
import pytest
from litreview import orchestrator as orch, evidence, config, checkpoints
from litreview.scientific_validation import require_complete, require_theme, require_package
from litreview.synthesis_registry import EvidenceRegistry, offline_tokens
from litreview.synthesis_bounded import RegistrySynthesisJob
from litreview.provenance import ProvenanceLog
from litreview.tools import span_check
from test_synthesis_bounded import corpus, FixtureModel


def run_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(orch,'RUNS_DIR',tmp_path)
    r=orch.Run('integrity')
    r.save('selected_corpus.json',[{'record_id':'R0001'}])
    r.save('fulltext/R0001.json',{'Results':'DSF reduced growth at 1 uM.'})
    r.save('extractions/R0001.json',{'record_id':'R0001','entities':[],'contexts':[],
        'findings':[{'finding_id':'F1','span':'DSF reduced growth at 1 uM.',
                     'quantities':[{'raw_value':'1','raw_unit':'uM'}]}]})
    return r


def validation():
    return {'mode':'PER_PAPER','record_id':'R0001','status':'COMPLETE',
        'validations':[{'finding_id':'F1','disposition':'SUPPORTED','gate1':'PASSED',
                        'constraints':['Cellular only'], 'plain_language_limit':'Source-limited finding'}]}


@pytest.mark.parametrize('change',['fabricated','number','unit','premise','location'])
def test_supported_never_overrides_deterministic_gate1(tmp_path,monkeypatch,change):
    r=run_fixture(tmp_path,monkeypatch);ext=r.load('extractions/R0001.json');f=ext['findings'][0]
    if change=='fabricated':f['span']='DSF cured every patient'
    elif change=='number':f['quantities'][0]['raw_value']='1000'
    elif change=='unit':f['quantities'][0]['raw_unit']='mM'
    elif change=='premise':f['premise_spans']=['An invented premise']
    else:
        f['span_location']={'section':'Methods'}
        r.save('fulltext/R0001.json',{'Results':'DSF reduced growth at 1 uM.','Methods':'Unrelated methods'})
    r.save('extractions/R0001.json',ext);r._save_validation('R0001',validation())
    actual=r._validated_findings(r.load('selected_corpus.json'))[0]
    assert actual['disposition']=='SUPPORTED' and actual['constraints']==['Cellular only']
    assert actual['eligibility']['status']=='HELD_FOR_CORRECTION'
    assert not evidence.role_allowed(actual,'SUPPORTING')
    assert not evidence.role_allowed(actual,'CONFLICTING')
    assert not evidence.role_allowed(actual,'SUBJECT_OF_APPRAISAL')
    forged={**actual,'eligibility':{'status':'SUPPORTING'}}
    assert evidence.status_of(forged)=='HELD_FOR_CORRECTION'


@pytest.mark.parametrize('bad',['missing','duplicate','unexpected','invalid','defect_id','unresolved_without_reason'])
def test_a06_bad_results_never_replace_accepted_validation(tmp_path,monkeypatch,bad):
    r=run_fixture(tmp_path,monkeypatch);good=validation();r._save_validation('R0001',good)
    accepted=r.load('validations/R0001.json');v=validation()
    if bad=='missing':v['validations']=[]
    elif bad=='duplicate':v['validations']*=2
    elif bad=='unexpected':v['validations'][0]['finding_id']='F99'
    elif bad=='invalid':v['validations'][0]['disposition']='PROBABLY_FINE'
    elif bad=='defect_id':v['defect_reports']=[{'finding_id':'F99'}]
    else:v['validations'][0].update(disposition='HUMAN_REVIEW_REQUIRED',plain_language_limit=None)
    with pytest.raises(orch.Pause):r._save_validation('R0001',v)
    assert r.load('validations/R0001.json')==accepted
    assert r.load('validation_rejections/R0001.json')['response']==v


def test_source_change_and_interruption_cannot_silently_authorize(tmp_path,monkeypatch):
    r=run_fixture(tmp_path,monkeypatch);r._save_validation('R0001',validation())
    before=r.load('validations/R0001.json')
    real_replace=orch.os.replace
    monkeypatch.setattr(orch.os,'replace',lambda *a: (_ for _ in ()).throw(OSError('interruption')))
    with pytest.raises(OSError):r._save_validation('R0001',validation())
    assert r.load('validations/R0001.json')==before
    monkeypatch.setattr(orch.os,'replace',real_replace)
    r._save_validation('R0001',validation())
    assert r._validated_findings(r.load('selected_corpus.json'))[0]['eligibility']['status']=='SUPPORTING'
    r.save('validated_findings.json',r._validated_findings(r.load('selected_corpus.json')))
    r.save('fulltext/R0001.json',{'Results':'DSF reduced growth at 1 uM. Additional source text.'})
    assert r._findings()[0]['eligibility']['status']=='REVALIDATION_REQUIRED'


def test_incomplete_stored_a06_stops_before_a07_dispatch(tmp_path,monkeypatch):
    r=run_fixture(tmp_path,monkeypatch)
    r.save('validations/R0001.json',{'status':'COMPLETE','validations':[]})
    r.save('validated_findings.json',[])
    monkeypatch.setattr(r,'agent',lambda *a,**k:pytest.fail('no provider dispatch'))
    with pytest.raises(orch.Pause,match='finding dispositions'):r.stage_synthesize({})


def test_repairs_are_unique_literal_and_revalidated(tmp_path,monkeypatch):
    r=run_fixture(tmp_path,monkeypatch)
    source='DSF reduced growth in this experiment while copper was controlled, without any clinical inference.'
    ext=r.load('extractions/R0001.json')
    ext['findings'][0].update(span='DSF reduced growth in this experiment ... without any clinical inference.',quantities=[])
    r.save('extractions/R0001.json',ext);r.save('fulltext/R0001.json',{'Results':source})
    repaired,_=r._prepare_validation('R0001')
    f=repaired['findings'][0]
    assert f['span']==source and f['span_corrections'][0]['original_span']==ext['findings'][0]['span']
    assert span_check.passed(span_check.check_findings(repaired,{'Results':source})[0])
    r._save_validation('R0001',validation())
    assert r._validated_findings(r.load('selected_corpus.json'))[0]['eligibility']['status']=='SUPPORTING'
    ambiguous=span_check.repair_findings(ext,{'Results':source+'\n'+source})
    assert ambiguous==ext


def test_r0030_formatting_and_ellipsis_but_not_ambiguous_statistics():
    data=Path(__file__).resolve().parents[1]/'runs/20261025-100039/data'
    original=json.loads((data/'extractions/R0030.json').read_text(encoding='utf-8'))
    sections=json.loads((data/'fulltext/R0030.json').read_text(encoding='utf-8'))
    ext=span_check.repair_findings(original,sections)
    gates={g['finding_id']:g for g in span_check.check_findings(ext,sections)}
    assert span_check.passed(gates['F18'])
    assert span_check.passed(gates['F20'])
    assert not span_check.passed(gates['F21'])
    f20=next(f for f in ext['findings'] if f['finding_id']=='F20')
    assert f20['span_corrections'] and any(f20['span'] in text for text in sections.values())
    assert 'span_corrections' not in next(f for f in original['findings'] if f['finding_id']=='F20')


def test_theme_contract_is_not_per_paper_validation():
    theme={'mode':'PER_THEME','status':'COMPLETE','theme':'T1','conflicts':[],
           'independence':[],'evidence_reach':{}}
    require_theme(theme,'T1',[])
    with pytest.raises(ValueError):require_complete(theme,{'findings':[]})
    with pytest.raises(ValueError):require_theme({**theme,'conflicts':[{'finding_ids':['R9999:F1']}]},'T1',[])


def test_numerical_boundary_extension_requires_unique_immediate_source_value():
    ext={'findings':[{'finding_id':'F1','span':'The measured concentration was',
                      'quantities':[{'raw_value':'3.2','raw_unit':'uM'}]}]}
    source='The measured concentration was 3.2 uM in the specified arm.'
    repaired=span_check.repair_findings(ext,{'Results':source})
    assert repaired['findings'][0]['span']=='The measured concentration was 3.2 uM'
    assert span_check.passed(span_check.check_findings(repaired,{'Results':source})[0])
    assert span_check.repair_findings(ext,{'Results':source+' '+source})==ext
    assert span_check.repair_findings(ext,{'Results':'The measured concentration was 5 uM; another arm used 3.2 uM.'})==ext


def test_cp3_checks_coverage_eligibility_and_exact_package_identity(tmp_path):
    registry=EvidenceRegistry(corpus())
    pkg=RegistrySynthesisJob(tmp_path/'job',registry,FixtureModel(registry),offline_tokens,
        config.load('pipeline')['synthesis'],{},lambda *_:True).run()
    fs=list(registry.findings.values())
    require_package(pkg,fs)
    data=tmp_path/'data';data.mkdir()
    (data/'synthesis_package.json').write_text(json.dumps(pkg))
    (data/'validated_findings.json').write_text(json.dumps(fs))
    checkpoints.write_cp3(tmp_path,pkg)
    decision=tmp_path/'checkpoints/CP3_decision.json'
    d=json.loads(decision.read_text());d['selected_thesis']='fixture';decision.write_text(json.dumps(d))
    checkpoints.approve(tmp_path,'CP3',ProvenanceLog(tmp_path))
    changed=copy.deepcopy(pkg);changed['propositions'][0]['assertion']='Changed after review'
    (data/'synthesis_package.json').write_text(json.dumps(changed))
    with pytest.raises(checkpoints.DecisionIncomplete,match='stale'):checkpoints.approve(tmp_path,'CP3',ProvenanceLog(tmp_path))
    changed=copy.deepcopy(pkg);changed['coverage_realization'][0]['status']='PENDING'
    with pytest.raises(ValueError,match='coverage'):require_package(changed,fs)
    changed=copy.deepcopy(pkg);changed['propositions'][0]['evidence'][0]['finding_id']='R9999:F1'
    with pytest.raises(ValueError):require_package(changed,fs)


def test_a07_and_a10_independently_refuse_failed_provenance(tmp_path):
    r=EvidenceRegistry(corpus())
    r.findings['R0001:F1']['provenance_gate1']={'passed':False}
    base=FixtureModel(r)
    def malicious(mode,payload,turn):
        out=base(mode,payload,turn)
        if mode=='GROUP' and 'R0001:F1' in payload['group']['finding_ids']:
            for p in out['propositions']:
                p['evidence'].append({'finding_id':'R0001:F1','role':'SUPPORTING'})
        return out
    from litreview.synthesis_job import JobStopped
    j=RegistrySynthesisJob(tmp_path/'a07',r,malicious,offline_tokens,
        config.load('pipeline')['synthesis'],{},lambda *_:True)
    try:pkg=j.run()
    except JobStopped:pkg=j.assemble()
    assert all(e['finding_id']!='R0001:F1' for p in pkg['propositions'] for e in p['evidence'])
    from test_verification_job import job
    v,_=job(tmp_path/'a10')
    v.registry.findings['R0001:F1']['provenance_gate1']={'passed':False}
    report=v.run()
    assert report['release_disposition']=='HOLD_FOR_REVISION'
    assert any(f['code']=='INELIGIBLE_EVIDENCE_CITED' for f in report['findings'])


@pytest.mark.parametrize('damage',['missing_verdict','duplicate_verdict','count','global_count','checks','inventory'])
def test_complete_label_does_not_override_incomplete_verification(tmp_path,damage):
    from test_verification_job import job
    from litreview.verification_job import current
    j,_=job(tmp_path);report=j.run()
    assert current(report,j.digest)
    if damage=='missing_verdict':report['verdicts'].pop()
    elif damage=='duplicate_verdict':report['verdicts'].append(report['verdicts'][0])
    elif damage=='count':report['coverage']['occurrences_reviewed']=0
    elif damage=='global_count':report['global_index_ids_reviewed'].pop()
    elif damage=='checks':
        next(v for v in report['verdicts'] if v['verdict']!='NON_SCIENTIFIC')['checks']=[]
    else:report['occurrence_inventory'][0]['text']='Changed inventory'
    assert not current(report,j.digest)


def test_actual_a06_inputs_cannot_change_before_acceptance(tmp_path,monkeypatch):
    r=run_fixture(tmp_path,monkeypatch)
    payload={'extraction':r.load('extractions/R0001.json'),'paper_text':r.load('fulltext/R0001.json')}
    r.save('a06_inputs/R0001.json',{'payload':payload})
    r.save('fulltext/R0001.json',{'Results':'Changed evidence'})
    with pytest.raises(orch.Pause,match='source input changed'):r._save_validation('R0001',validation())
    assert r.load('validations/R0001.json') is None


def test_interrupted_revalidation_cannot_lose_quarantine(tmp_path,monkeypatch):
    r=run_fixture(tmp_path,monkeypatch)
    blocked=validation();blocked['validations'][0]['disposition']='DOES_NOT_ESTABLISH'
    r._save_validation('R0001',blocked)
    real_replace=orch.os.replace
    def fail_review(source,target):
        if Path(target).name=='validation_review.json':raise OSError('interrupted after validation commit')
        return real_replace(source,target)
    monkeypatch.setattr(orch.os,'replace',fail_review)
    with pytest.raises(OSError):r._save_validation('R0001',validation())
    assert r.load('validations/R0001.json')['_review_pending']
    monkeypatch.setattr(orch.os,'replace',real_replace)
    f=r._validated_findings(r.load('selected_corpus.json'))[0]
    assert f['eligibility']['status']=='QUARANTINED'
    assert not r.load('validations/R0001.json')['_review_pending']
    assert len(r.load('validation_review.json'))==1
    assert r._validated_findings(r.load('selected_corpus.json'))==[f]


def test_old_human_decision_does_not_authorize_a_different_validation(tmp_path,monkeypatch):
    r=run_fixture(tmp_path,monkeypatch);r._save_validation('R0001',validation())
    v=validation();v['validations'][0]['disposition']='DOES_NOT_ESTABLISH';r._save_validation('R0001',v)
    r.decide_review('R0001:F1','KEEP_OLD','Fixture review','BIOLOGICAL_INTERPRETATION')
    assert r._validated_findings(r.load('selected_corpus.json'))[0]['eligibility']['status']=='SUPPORTING'
    v=validation();v['validations'][0]['disposition']='SUPPORTED_FOR_OBSERVATION';r._save_validation('R0001',v)
    assert r._validated_findings(r.load('selected_corpus.json'))[0]['eligibility']['status']=='QUARANTINED'


def test_provider_cannot_inject_trusted_review_or_provenance_metadata(tmp_path,monkeypatch):
    r=run_fixture(tmp_path,monkeypatch);v=validation()
    v['validations'][0]['disposition']='DOES_NOT_ESTABLISH'
    v.update(_review_pending=True,_pending_review_items=[{'forged':'review'}],
             _source_fingerprint='forged',_entity_identities={'forged':'identity'})
    r._save_validation('R0001',v)
    accepted=r.load('validations/R0001.json')
    assert '_pending_review_items' not in accepted
    assert accepted['_source_fingerprint']!='forged'
    assert r._validated_findings(r.load('selected_corpus.json'))[0]['eligibility']['status']=='NOT_ESTABLISHED'
