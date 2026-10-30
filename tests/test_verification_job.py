"""Scripted adversarial verdicts prove coverage/enforcement, not scientific error detection."""
import copy
import pytest
from litreview import config
from litreview.agents.base import build_system_prompt, user_parts
from litreview.synthesis_registry import EvidenceRegistry, offline_tokens
from litreview.synthesis_job import JobStopped
from litreview.verification_job import VerificationJob, inventory, CHECKS, current, version
from test_synthesis_bounded import corpus


def response(mode):
    return {'agent_id':'A10-RV','prompt_version':'2.0','mode':mode,'status':'COMPLETE',
            'verdicts':[],'issues':[],'retrieval_requests':[], 'inventory_fingerprint':'','reviewed_index_ids':[]}


class ScriptedVerifier:
    """All scientific judgments are supplied, never discoveries by this fixture."""
    def __init__(self):self.calls=[]
    def __call__(self, mode,payload,name):
        self.calls.append((mode,copy.deepcopy(payload),name))
        out=response(mode)
        if mode=='LOCAL':
            for o in payload['occurrences']:
                fids=[x['finding_id'] for x in o['evidence_roles']]
                out['verdicts'].append({'occurrence_id':o['occurrence_id'],'verdict':'VERIFIED' if fids else 'NON_SCIENTIFIC',
                    'rationale':'Scripted structural evaluation, not scientific assessment','checks':CHECKS if fids else [],
                    'evidence_finding_ids':list(dict.fromkeys(fids)),'source_item_ids':[],
                    'appraisal_checks':[{'binding_id':a['binding_id'],'preserved':True} for a in o['appraisal_bindings']]})
        else:
            out['inventory_fingerprint']=payload['inventory_fingerprint']
            out['reviewed_index_ids']=[x['id'] for x in payload['evidence_index_page']]
        return out


def setup():
    r=EvidenceRegistry(corpus())
    p={'propositions':[{'proposition_id':f'P{i}','type':'SOURCE_GROUNDED','assertion':f'Source-limited observation {i}',
        'evidence':[{'finding_id':f'R{i:04d}:F1','role':'SUPPORTING'}]} for i in range(1,5)]}
    m={'title':'Evaluation heading', 'abstract':'Evaluation abstract', 'sections':[
        {'section_id':'S1','heading':'Introduction','text_markdown':'Observation [@R0001] ⟦P1⟧. Repeated [@R0001] ⟦P1⟧. Uncited mechanism.'},
        {'section_id':'S2','heading':'Conclusion','text_markdown':'Opposite claim [@R0002] ⟦P2⟧.'}],
        'table_captions':[{'caption':'Evaluation table'}]}
    return r,p,m


def job(tmp_path,model=None,**cfg):
    r,p,m=setup()
    model=model or ScriptedVerifier()
    settings={**config.load('pipeline')['scientific_verification'],**cfg}
    return VerificationJob(tmp_path,m,{},p,r,[{'kind':'TABLE','columns':['Observation'],
        'rows':[['Table claim [@R0001] ⟦P1⟧']]}],settings,model,offline_tokens,{'prompt':'fixture'}),model


def test_occurrences_cover_repeated_tags_uncited_text_and_all_surfaces(tmp_path):
    j,model=job(tmp_path)
    report=j.run()
    texts=[o['text'] for o in report['occurrence_inventory']]
    assert any('Uncited' in t for t in texts) and any('Table claim' in t for t in texts)
    assert len([o for o in j.occurrences if o['item_ids']==['P1']])==3
    assert len({o['occurrence_id'] for o in j.occurrences})==len(j.occurrences)
    assert report['coverage']['occurrences_reviewed']==len(j.occurrences)
    assert set(j.registry.findings)<=set(report['global_index_ids_reviewed'])
    assert all('synthesis_package' not in p for _,p,_ in model.calls)


@pytest.mark.parametrize('defect',['missing','duplicate','appraisal_missing','blocked','uncited','numerical','mechanism','misattribution'])
def test_adversarial_enforcement_and_supplied_defects(tmp_path,defect):
    base=ScriptedVerifier()
    j,_=job(tmp_path)
    if defect in ('numerical','mechanism','misattribution'):
        r,p,m=setup()
        f=r.findings['R0001:F1']
        f['span']='DSF/Cu at 1 uM reduced viability in U87 cells after 24 hours; direct target engagement was not established.'
        r.contexts[f['context_id']]={'evidence_system':'IN_VITRO_CELLULAR','cell_line':'U87','dose':'1 uM',
                                    'comparator':'vehicle','outcome':'viability','exposure':'24 hours'}
        wrong={'numerical':'DSF/Cu at 1000 mM reduced viability [@R0001] ⟦P1⟧.',
               'mechanism':'Parent disulfiram directly engages the molecular target in patients [@R0001] ⟦P1⟧.',
               'misattribution':'R0002 established the DSF/Cu result described by R0001 [@R0002] ⟦P1⟧.'}
        m['sections'][0]['text_markdown']=wrong[defect]
        j=VerificationJob(tmp_path/'adversarial',m,{},p,r,[],j.cfg,base,offline_tokens,{'fixture':True})
    if defect=='blocked':
        j.registry.findings['R0001:F1']['eligibility']={'status':'REJECTED'}
    if defect=='appraisal_missing':
        f=j.registry.findings['R0001:F1'];f['eligibility']={'status':'NOT_ESTABLISHED'}
        f['disposition']='DOES_NOT_ESTABLISH'
        j.package['propositions'][0]['evidence'][0].update(role='SUBJECT_OF_APPRAISAL',
            appraisal={'statement':'source claim','claim_source_record_id':'R0001','a06_rationale':f['plain_language_limit']})
        j.evidence_idx=__import__('litreview.evidence',fromlist=['_named'])._named(j.package,{})
    def model(mode,payload,name):
        out=base(mode,payload,name)
        if mode=='LOCAL':
            if defect=='missing':out['verdicts']=out['verdicts'][:-1]
            elif defect=='duplicate':out['verdicts'][-1]=copy.deepcopy(out['verdicts'][0])
            elif defect=='appraisal_missing':
                for v in out['verdicts']:v['appraisal_checks']=[]
            elif defect=='uncited':
                v=next(v for v in out['verdicts'] if 'Uncited' in j.by_occurrence[v['occurrence_id']]['text'])
                v.update(verdict='UNRESOLVED',checks=CHECKS)
            elif defect in ('numerical','mechanism','misattribution'):
                v=next(v for v in out['verdicts'] if j.by_occurrence[v['occurrence_id']]['item_ids']==['P1'])
                v['verdict']='DEFECT';v['checks']=CHECKS
                out['issues']=[{'occurrence_ids':[v['occurrence_id']],'finding_ids':[],
                    'code':defect.upper(),'severity':'BLOCKING','rationale':'Supplied adversarial error',
                    'correction':'Restore source-limited interpretation'}]
        return out
    j.call=model
    if defect in ('missing','duplicate','appraisal_missing'):
        with pytest.raises(JobStopped):j.run()
    else:
        r=j.run();assert r['release_disposition']=='HOLD_FOR_REVISION'
        assert all(f['locations'] and f['locations'][0]['text'] for f in r['findings'])


def test_global_distant_conflict_and_uncited_retrieval(tmp_path):
    j,base=job(tmp_path)
    def model(mode,payload,name):
        if mode=='GLOBAL' and not payload['retrieved_evidence']['findings']:
            return {**response(mode),'status':'NEEDS_EVIDENCE','retrieval_requests':[{'finding_ids':['R0004:F1']}]}
        out=base(mode,payload,name)
        if mode=='GLOBAL':
            out['issues']=[{'occurrence_ids':[j.occurrences[2]['occurrence_id'],j.occurrences[-1]['occurrence_id']],
                'finding_ids':['R0004:F1'],'code':'DISTANT_CONTRADICTION','severity':'BLOCKING',
                'rationale':'Supplied distant conflict with uncited evidence','correction':'Reconcile both statements'}]
        return out
    j.call=model
    r=j.run()
    assert r['finding_severity']=='BLOCKING'
    assert any(p['retrieved_evidence']['findings'] for mode,p,_ in base.calls if mode=='GLOBAL')


def test_resume_and_revision_cache_never_reuse_stale_global_results(tmp_path):
    j,model=job(tmp_path/'one',max_occurrences_per_packet=1)
    report=j.run()
    initial=len(model.calls)
    assert j.run()['coverage']==report['coverage'] and len(model.calls)==initial
    r,p,m=setup();m['abstract']='Changed evaluation abstract'
    second=ScriptedVerifier()
    revised=VerificationJob(tmp_path/'two',m,{},p,r,j.tables,j.cfg,second,offline_tokens,{'prompt':'fixture'},
        cache_directory=j.cache_dir)
    new=revised.run()
    assert not current(report,new['verification_fingerprint'])
    assert sum(mode=='LOCAL' for mode,_,_ in second.calls)==1
    assert any(mode=='GLOBAL' for mode,_,_ in second.calls)


def test_truncation_has_no_coverage_and_resumes_valid_local_outputs(tmp_path):
    j,base=job(tmp_path)
    def broken(mode,payload,name):
        if mode=='GLOBAL':raise JobStopped('simulated truncated response')
        return base(mode,payload,name)
    j.call=broken
    with pytest.raises(JobStopped):j.run()
    resumed=ScriptedVerifier();j.call=resumed
    assert j.run()['verification_execution']=='COMPLETE'
    assert all(mode=='GLOBAL' for mode,_,_ in resumed.calls)


def test_context_admission_fails_before_model_dispatch(tmp_path):
    j,base=job(tmp_path,context_ceiling_tokens=1)
    with pytest.raises(JobStopped):j.run()
    assert not base.calls


def test_metadata_only_revision_rebinds_version_without_paid_reverification(tmp_path):
    j,_=job(tmp_path/'one')
    first=j.run()
    revised=copy.deepcopy(j.manuscript);revised['output_manuscript_version']='proof-2'
    model=ScriptedVerifier()
    other=VerificationJob(tmp_path/'two',revised,j.plan,j.package,j.registry,j.tables,j.cfg,
        model,offline_tokens,{'prompt':'fixture'},cache_directory=j.cache_dir)
    second=other.run()
    assert not model.calls
    assert first['verification_fingerprint']!=second['verification_fingerprint']


def test_a11_reverifies_stale_report_before_critique(tmp_path,monkeypatch):
    from litreview import orchestrator as orch
    monkeypatch.setattr(orch,'RUNS_DIR',tmp_path)
    run=orch.Run('critique')
    run.save('manuscript_plan.json',{})
    run.save('synthesis_approved.json',{})
    run.save('rv_latest.json',{'stale':True})
    from bridge_fixtures import bridge_stubs
    bridge_stubs(run,monkeypatch)   # A10/A11 sequencing only; the bridge's own checks are tested in test_bridge.py
    monkeypatch.setattr(run,'_current',lambda:{'title':'New version'})
    monkeypatch.setattr(run,'_verification_current',lambda *a:False)
    monkeypatch.setattr(run,'_prose_vendors',lambda *a:frozenset({'anthropic'}))
    calls=[]
    fresh={'verification_fingerprint':'new','findings':[]}
    monkeypatch.setattr(run,'_verify',lambda *a:calls.append('verify') or fresh)
    def critique(a,payload,**kwargs):
        calls.append('critique');assert payload['a10_findings']==fresh
        return {'decision':'ACCEPT'}
    monkeypatch.setattr(run,'agent',critique)
    assert run.stage_review_loop({})=='finish_edit' and calls==['verify','critique']


def test_changed_policy_and_missing_global_coverage_cannot_be_current(tmp_path):
    from litreview.verification_job import policy_hash
    j,_=job(tmp_path)
    r=j.run()
    assert current(r,j.digest,policy_hash(j.cfg))
    assert not current(r,j.digest,'changed scientific prompt')
    broken=copy.deepcopy(r);broken['verification_execution']='INCOMPLETE'
    assert not current(broken,j.digest)


@pytest.mark.parametrize('failure',['budget','unknown_billing','known_truncation'])
def test_each_dispatch_reserves_cost_and_unknown_billing_is_not_retried(tmp_path,monkeypatch,failure):
    from litreview import orchestrator as orch
    from test_verification_scope import _run, _wrote, PACKAGE, PLAN, FINDINGS, manuscript
    run=_run(tmp_path,monkeypatch)
    run.save('manuscript_plan.json',PLAN);run.save('synthesis_approved.json',PACKAGE)
    run.save('validated_findings.json',FINDINGS)
    _wrote(run,'A09-WRI','A09-WRI_draft1','anthropic')
    if failure=='budget':run.budget.cap=.000001
    calls=[]
    def fail(agent,payload,step,**kwargs):
        calls.append(step)
        assert kwargs['reservation_key'] in run.budget.reservations()
        if failure=='known_truncation':
            m=run.route('A10-RV')
            run.budget.record('A10-RV',m.provider,m.model,10,10,step=step)
        raise orch.AgentError('simulated unknown billing' if failure=='unknown_billing' else 'simulated truncated response')
    monkeypatch.setattr(run,'agent',fail)
    with pytest.raises((orch.Pause,orch.BudgetExceeded)):
        run._verify(manuscript('Evaluation [@R0001] ⟦P1⟧.'),'FINAL','test')
    if failure=='budget':assert not calls
    elif failure=='known_truncation':assert not run.budget.reservations()
    else:
        assert run.budget.reservations()
        with pytest.raises(orch.Pause,match='unsettled A10'):
            run._verify(manuscript('Evaluation [@R0001] ⟦P1⟧.'),'FINAL','test')
        assert len(calls)==1


def test_legacy_bindings_now_cover_repeat_tags_and_appraisals_in_table_caption():
    from litreview.evidence import verification_bindings
    r,p,m=setup()
    p['propositions'][0]['evidence'][0]['role']='SUBJECT_OF_APPRAISAL'
    p['propositions'][0]['evidence'][0]['appraisal']={'statement':'reported claim'}
    r.findings['R0001:F1']['eligibility']={'status':'NOT_ESTABLISHED'}
    r.findings['R0001:F1']['disposition']='DOES_NOT_ESTABLISH'
    m['table_captions']=[{'caption':'Claim ⟦P1⟧'}]
    flags,appraisals=verification_bindings(m,p,list(r.findings.values()))
    assert len(appraisals)==3 and len({a['occurrence_id'] for a in appraisals})==3


def test_identical_sentences_are_distinct_and_table_cells_keep_row_context():
    text='Identical claim [@R0001] ⟦P1⟧. '
    occ=inventory({'sections':[{'text_markdown':text+text}]},
        [{'columns':['Dose','Outcome'],'rows':[['1 uM [@R0001]','Viability ⟦P1⟧']]}])
    repeated=[o for o in occ if 'Identical' in o['text']]
    assert len(repeated)==2 and repeated[0]['occurrence_id']!=repeated[1]['occurrence_id']
    cells=[o for o in occ if 'rows' in o['path']]
    assert all(o['citation_record_ids']==['R0001'] and o['item_ids']==['P1'] for o in cells)
    assert all(o['surface_context']['columns']==['Dose','Outcome'] for o in cells)


@pytest.mark.parametrize('failure',['missing_global','retrieval_exhausted','tampered_cache'])
def test_incomplete_global_and_tampered_acceptance_never_approve(tmp_path,failure):
    import json
    j,base=job(tmp_path)
    if failure=='tampered_cache':
        j.run()
        path=next(p for p in j.cache_dir.glob('*.json') if not p.name.startswith('global-'))
        saved=json.loads(path.read_text());saved['output']['verdicts'][0]['rationale']='tampered'
        path.write_text(json.dumps(saved))
    else:
        def model(mode,payload,name):
            out=base(mode,payload,name)
            if mode=='GLOBAL':
                if failure=='missing_global':out['reviewed_index_ids']=[]
                else:out={**response(mode),'status':'NEEDS_EVIDENCE','retrieval_requests':[{'finding_ids':['R0004:F1']}]}
            return out
        j.call=model
    with pytest.raises(JobStopped):j.run()


@pytest.mark.parametrize('severity',['NONE','MAJOR','BLOCKING'])
def test_line_verification_is_preserved_before_proof_or_scientific_hold(tmp_path,monkeypatch,severity):
    from test_verification_scope import _run
    from litreview import orchestrator as orch
    run=_run(tmp_path,monkeypatch)
    run.save('manuscript_plan.json',{})
    from bridge_fixtures import bridge_stubs
    bridge_stubs(run,monkeypatch)   # A10/A12 sequencing only; the bridge's own checks are tested in test_bridge.py
    monkeypatch.setattr(run,'_current',lambda:{'sections':[]})
    line_report={'finding_severity':severity,'findings':[{'code':'EVALUATION_CORRECTION'}],
                 'verification_fingerprint':'line-version'}
    monkeypatch.setattr(run,'_maybe_verify',lambda *a,**k:line_report)
    calls=[]
    def edit(agent,payload,**kwargs):
        calls.append(payload['mode'])
        if payload['mode']=='PROOF':
            assert payload['verification_findings']==line_report['findings']
            assert run.load('rv_latest.json')==line_report
        return {'sections':[]}
    monkeypatch.setattr(run,'agent',edit)
    monkeypatch.setattr(run,'_verify',lambda *a,**k:{'release_disposition':'APPROVED'})
    if severity=='NONE':
        assert run.stage_finish_edit({})=='finalize' and calls==['LINE','PROOF']
    else:
        with pytest.raises(orch.Pause,match='scientific findings'):run.stage_finish_edit({})
        assert calls==['LINE'] and run.load('rv_latest.json')==line_report
