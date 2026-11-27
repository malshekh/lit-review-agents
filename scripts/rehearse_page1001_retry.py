"""Run with -I -S -B, sealed v39 as cwd and a separate report directory. No provider transport."""
from pathlib import Path
import copy, hashlib, importlib.util, json, shutil, socket, sys, tempfile
from decimal import Decimal as D, ROUND_CEILING
from unittest.mock import patch

root=Path.cwd()
repo=Path(__file__).resolve().parents[1]
output=Path(sys.argv[1]).resolve()
run_id='20261123-214928'
live=root/'runs'/run_id
assert not output.is_relative_to(root) and sys.flags.isolated
output.mkdir(parents=True,exist_ok=True)
sys.path[:0]=[str(root/'src'),str(root/'vendor')]
from litreview import orchestrator
from litreview.runtime_integrity import sha, verify
from litreview.synthesis_registry import fingerprint
from litreview.synthesis_job import JobStopped
from litreview.reconciliation_paging import provider_body, body_bytes, generation_body
from litreview.agents.base import REPAIR_SYSTEM, repair_message
from dataclasses import replace
import jsonschema

def extension(name):
    spec=importlib.util.spec_from_file_location('litreview.'+name,repo/'src/litreview'/(name+'.py'))
    mod=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    return mod

def save(name,data):
    (output/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf8')

def experiment(tmp):
    source_manifest=root/'frozen_runtime_manifest.json'
    assert sha(source_manifest)=='b321b41ce4f2e677b9441804f0cad24a8ba236bea2797a6b546618a5e810d510'
    verify(root,json.loads(source_manifest.read_bytes()))
    orchestrator.RUNS_DIR=tmp/'runs'
    shutil.copytree(live,orchestrator.RUNS_DIR/run_id)
    run=orchestrator.Run(run_id)
    job,tag=run._synthesis_job()
    props={p['proposition_id']:p for p in job._all_props()}
    turn='RECONCILE_1001'
    step='A07-SYN_job'+tag+'_'+turn+'_LOOKUP0'
    raw=run.dir/'outputs'/(step+'.raw0.txt')
    saved=run.dir/'outputs'/(step+'.json')
    rejected=json.loads(saved.read_bytes())
    prior=copy.deepcopy(dict(job.reconciliation_payloads())[turn])
    ids=set(prior['prefill_finding_ids'])
    assert len(prior['focus'])==21 and 'R0078:F28' not in ids
    errors={}
    def fail(label,fn,expected):
        try:fn()
        except (JobStopped,ValueError,jsonschema.ValidationError,sys.modules['litreview.orchestrator'].Pause) as exc:
            assert expected in str(exc),str(exc)[:500]
            errors[label]=str(exc)[:350]
        else:raise AssertionError(label)
    fail('raw primary schema',lambda:job.validate_output('RECONCILE',json.loads(raw.read_bytes())),'too long')
    def replay(response):
        job.call=lambda *args:copy.deepcopy(response)
        job.reconcile(only_turn=turn)
    fail('actual rejected repaired response',lambda:replay(rejected),'lacks referenced proposition evidence')
    # Production stops at the first error. Isolate each later failing reference without altering the archive.
    for n,pid in [(6,'G0002.P6'),(8,'G0002.P8'),(8,'G0001.P6')]:
        sub=copy.deepcopy(rejected)
        row=sub['issues'][n-1]
        row['proposition_ids']=['GROUP_'+pid]+(['GROUP_G0003.P6'] if n==6 else [])
        sub['issues']=[row]
        fail(f'issue {n} {pid}',lambda:replay(sub),'lacks referenced proposition evidence')
    links=extension('reconciliation_links')
    revised=extension('synthesis_bounded')
    job.__class__=revised.RegistrySynthesisJob
    page={**prior,'issue_link_contract':'page1001-v2','issue_link_instructions':links.RULE}
    # Hand-authored test explanations; never infer a link from overlapping identifiers.
    lines=[
    [('3.5','78:14','Decision tree uses the same buffer evaluation.'),('4.3','78:13',links.SVM),('5.1','78:12','XGBoost used the same two evaluations.'),('5.2','78:12','Identity task; independent preparations unreported.')],
    [('2.1','78:1','Array response screen.'),('2.4','78:15','Within-model SHAP attribution.'),('2.8','78:1','Same optical screen.'),('3.3','78:10','ANOVA on collected features.'),('3.4','78:11','Exploratory PCA on array data.'),('3.5','78:14','Decision tree on buffer data.'),('3.6','78:26','Comparison of selection criteria.'),('4.3','78:13',links.SVM)],
    [('3.1','58:3','Partitioning benchmark in bacterial isolates.'),('3.2','58:4','Author characterization in the same abstract.'),('4.1','58:1','Spectrum-level split gave inflated accuracy.'),('4.2','58:2','Isolate or subject partitioning in this benchmark.')],
    [('1.5','115:6','Surface preparation in the Chen abstract.'),('1.6','115:6','Preparation context only.'),('2.7','115:5','Spectral input in the same abstract.'),('2.8','115:5','Same source for signal interpretation.'),('3.9','115:2','Multiplex classification accuracy.'),('3.10','115:4','Internal standard in that assay.'),('3.11','115:2','Same abstract contributes classification evidence.')],
    [('3.7','90:10','MBA recovered in the flow setting.'),('3.8','90:8','Crystal violet undetected in flow but detected in batch; mechanism unresolved.')],
    [('2.4','78:15','Daunorubicin SHAP features reflect within-model attribution.'),('2.6','78:28','Source-recovered Table 1 daunorubicin concentration-PCA cell: (TAT)6-(10,2) red wavelength shift; distinct from the blue Kd cell.'),('3.6','78:26','Comparison across selection criteria; no independent superiority test.')],
    [('3.1','58:3','Bacterial SERS partitioning benchmark.'),('3.5','78:14','Decision tree on the buffer drug-identity task.'),('4.1','58:1','Inflation observed with spectrum-level splitting in the bacterial benchmark.'),('4.3','78:13',links.SVM)],
    [('3.11','115:2','Chen reports multiplex classification accuracy.'),('2.8','115:5','Chen supplies measured spectra for computational interpretation.'),('1.6','115:6','Chen supplies material-preparation context. These uses share one abstract; dataset independence is unknown.')]]
    fixture=copy.deepcopy(rejected)
    for issue,rows in zip(fixture['issues'],lines,strict=True):
        notes=[];fids=[];pids=[]
        for short,f,reason in rows:
            g,p=short.split('.'); r,n=f.split(':')
            pid=f'G{int(g):04d}.P{p}'; fid=f'R{int(r):04d}:F{n}'
            notes.append(f'{pid} {fid} {reason}');pids.append('GROUP_'+pid);fids.append(fid)
        assert set(pids)==set(issue['proposition_ids'])
        issue.update(finding_ids=sorted(set(fids)),limitation='\n'.join(notes))
    fixture['limitations']=['R0078 Table 1 was visually verified. F28 retains source-derived recovery provenance.',
        'Study and dataset independence are unknown. R0115 is abstract-only; serum applies to its detection limits.']
    fixture['warnings']=[]
    for rev in fixture['reviews']:
        rev['rationale']={'GROUP_G0004.P3':links.SVM,'GROUP_G0003.P5':'The classifiers share the four-drug identity task. Preparation independence is unstated.',
            'GROUP_G0003.P9':'The multiplex accuracy and serum detection limits describe different measurements in one abstract.',
            'GROUP_G0003.P11':'R0115 contributes classification evidence here and preparation or signal context elsewhere; independent replication is unestablished.'}.get(rev['proposition_id'],rev['rationale'])
    job.evidence_pages=[page]
    turn='RECONCILE_1101'
    assert not job._committed(turn)
    fail('F28 cited from index without lookup',lambda:replay(fixture),'invalid or unexplained')
    got=job.registry.retrieve([{'finding_ids':['R0078:F28']}],job.cfg['retrieval_limit'])
    assert got==['R0078:F28']
    visible=ids|set(got)
    frozen=job.registry.findings
    checks={'R0078:F13':['3-fold cross-validation','98 \u00b1 4% (SVM)','100%, 50%, and 100%'],
            'R0078:F28':['Daunorubicin','Concentration-based PCA','(10,2) | red | wavelength shift'],
            'R0115:F2':['serum matrices','classification accuracies exceeding 95% in multiplex mixtures'],
            'R0115:F5':['SERS spectra','feature extraction and classification'],
            'R0115:F6':['co-precipitation','functionalized with carboxyl-PEG']}
    for fid, terms in checks.items():
        assert all(term in frozen[fid]['span'] for term in terms)
    assert 'reason for this discrepancy unresolved' in frozen['R0078:F13']['plain_language_limit']
    save('source-checks.json',{fid:{k:frozen[fid].get(k) for k in
        ('finding_id','span','location','plain_language_limit','access_level')} for fid in checks})
    for label,idx,before,after in [('wrong support for P8',7,'G0002.P8 R0115:F5','G0002.P8 R0115:F6'),
            ('causal explanation',0,links.SVM,'Model choice accounts for the decline.'),
            ('missing explanation',7,'Chen supplies measured spectra for computational interpretation.','')]:
        bad=copy.deepcopy(fixture)
        bad['issues'][idx]['limitation']=bad['issues'][idx]['limitation'].replace(before,after)
        fail(label,lambda:links.explained_links(bad,visible,props),'')
    bad=copy.deepcopy(fixture)
    bad['reviews'][-1]['rationale']='Different model choices caused the drop.'
    fail('issue and focal review disagree',lambda:links.explained_links(bad,visible,props),'Israel focal review')
    static=run.load('agent_inputs/'+step+'.json')['payload']
    common={k:static[k] for k in ('cp_syn_researcher_decision','reviewed_organization_proposals','approved_scope_guide','source_access')}
    model=run.route('A07-SYN'); cap=job.limit('RECONCILE')
    usd=lambda tokens,limit:(D(str(run.budget.cost(model.model,0,limit,0,0,tokens)))*D('1.30')).quantize(D('.000001'),rounding=ROUND_CEILING)
    def quote(p):
        params=provider_body(run,{**p,**common},model,cap)
        b=body_bytes(params)
        return {'records':len(p['retrieved_evidence']['findings']),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'reservation_usd':str(usd(len(b)+2048,cap))}
    assert quote({**prior,'retrieved_evidence':job.registry.details(sorted(ids))})['sha256']==run.load('reconciliation_repair_plan.json')['request_hashes']['RECONCILE_1001']
    turns=[]
    def simulated(mode,p,name):
        turns.append((name,quote(p)))
        if name.endswith('LOOKUP0'):
            assert 'R0078:F28' not in {f['finding_id'] for f in p['retrieved_evidence']['findings']}
            return {**fixture,'status':'NEEDS_EVIDENCE','issues':[],'reviews':[],'retrieval_requests':[{'finding_ids':got}]}
        details={f['finding_id']:f for f in p['retrieved_evidence']['findings']}
        assert fingerprint(details['R0078:F28'])==fingerprint(job.registry.findings['R0078:F28'])
        return copy.deepcopy(fixture)
    def extra_lookup(*args):
        return {**fixture,'status':'NEEDS_EVIDENCE','issues':[],'reviews':[],'retrieval_requests':[{'finding_ids':['R0078:F1']}]}
    job.call=extra_lookup
    fail('unpriced lookup refused',lambda:job.reconcile(only_turn=turn),'outside the reviewed F28 lookup')
    job.call=simulated;job.served_by=lambda:'OFFLINE TEST FIXTURE'
    job.reconcile(only_turn=turn)
    assert len(turns)==2 and len(job._committed(turn)['reviews'])==21
    explained=links.explained_links(fixture,visible,props)
    # Recommended live alternative: retrieve the already identified frozen record locally before the fresh judging turn.
    seeded={**page,'prefill_finding_ids':sorted(visible)}
    details=job.registry.details(sorted(visible))
    direct=quote({**seeded,'retrieved_evidence':details})
    repair_model=replace(model,effort='low',cache_system=False)
    bad_text=raw.read_text(encoding='utf8')
    room=min(cap,len(bad_text.encode('utf8'))//2+4000)
    msg=repair_message('A07-SYN','A07-SYN.bounded-reconcile.schema.json',bad_text,'X'*2000)
    msg.append({'text':'Evidence available for checking existing citations only:\n'+json.dumps(details,ensure_ascii=False),'cache':False})
    rb=body_bytes(generation_body(REPAIR_SYSTEM,msg,repair_model,room,False,model.cache_ttl))
    # At the context gate, one high-priced output token displaces one cheaper reserved input token.
    ceiling=run.cfg['synthesis']['context_ceiling_tokens']
    initial=sum(D(q['reservation_usd']) for _,q in turns)
    prior_pages=D('2.287662')+D('2.233036')
    bound={'prefetch_and_judge':direct,'interactive_turns':turns,'interactive_primary_sum':str(sum(D(q['reservation_usd']) for _,q in turns)),
      'local_lookup_charge':'0','repair_example_from_archived_primary':{'bytes':len(rb),'output_cap':room,'reservation':str(usd(len(rb)+2048,room))},
      'one_repair_absolute_context_bound':str(usd(ceiling-cap,cap)),
      'proposed_page_all_attempt_ceiling':str(initial),'remaining_authorization_at_ceiling':str(D('6.287415')-initial),
      'remaining_stage_at_ceiling':str(D('6.7678465')-initial),'later_primary_sum':str(prior_pages)}
    prior_plan=run.load('reconciliation_repair_plan.json')
    def code_hash(filename):
        return hashlib.sha256((repo/'src/litreview'/filename).read_text(encoding='utf8').encode('utf8')).hexdigest()
    plan={**prior_plan,'pages':[page,*prior_plan['pages'][1:]],
          'prior_plan':fingerprint(prior_plan),'runtime_manifest':sha(source_manifest),'baseline_stage_usd':3.6421535,
          'retry_of_page':1001,'retry_turn':turn,'request_hashes':{turn:turns[0][1]['sha256']},
          'reservations':{turn:str(initial)},'format_repair_caps':{turn:'1.850000'},
          'lookup_hashes':{turn+'_LOOKUP1':turns[1][1]['sha256']},'lookup_record_sha256':fingerprint(job.registry.findings['R0078:F28']),
          'rejected_page_response_sha256':sha(saved),'guard_utf8_lf_sha256':code_hash('reconciliation_links.py'),
          'reconcile_implementation_utf8_lf_sha256':code_hash('synthesis_bounded.py'),
          'reservation_implementation_utf8_lf_sha256':code_hash('orchestrator.py'),'stop_after':turn}
    bound['format_repair_limit_per_send']='1.850000'
    bound['uncapped_sum_of_two_turn_quotes_plus_two_permitted_format_limits']=str(initial+D('3.70'))
    bound['prefetch_and_judge']['status']='Unselected alternative exceeds the opening-page packing limit.'
    # Verify the exact proposed plan against the real authorization and reservation machinery on the copy.
    new_run=extension('orchestrator')
    new_run.RUNS_DIR=tmp/'runs'
    test_run=new_run.Run(run_id)
    test_run.save('reconciliation_repair_plan.json',plan)
    auth={**run.load('reconciliation_repair_approved.json'),'approved_by':'offline test fixture',
          'plan_fingerprint':fingerprint(plan),'max_increment_usd':float(initial),
          'baseline_stage_usd':plan['baseline_stage_usd'],'approved_turns':[turn]}
    test_run.save('reconciliation_repair_approved.json',auth)
    test_job,_=test_run._synthesis_job()
    assert test_job._committed(turn) and not test_job._committed('FINAL')
    class QuoteCaptured(Exception): pass
    for n, chosen in enumerate((ids,visible)):
        actual={**page,'retrieved_evidence':job.registry.details(sorted(chosen))}
        def capture(key, usd, *args, **kwargs):
            rounded=(D(str(usd))*D('1.30')).quantize(D('.000001'),rounding=ROUND_CEILING)
            assert rounded==D(turns[n][1]['reservation_usd'])
            raise QuoteCaptured()
        with patch.object(test_run,'_reserve',capture):
            try:test_job.call('RECONCILE',actual,turn+f'_LOOKUP{n}')
            except QuoteCaptured: pass
            else:raise AssertionError('reservation guard not reached')
    step2='A07-SYN_job'+tag+'_'+turn+'_LOOKUP1'
    fail('over-limit format repair',lambda:test_run._reserve('call-test',1.850001,'A07-SYN',steps=[step2],margin_included=True),'format repair exceeds')
    fail('over-limit page total',lambda:test_run._reserve('test-page',float(initial)+.01,'A07-SYN',steps=[step2],margin_included=True),'incremental reservation')
    for forbidden in ('RECONCILE_1002','RECONCILE_1003'):
        fail(forbidden+' stays paused',lambda:test_run._reserve('test-page',1,'A07-SYN',steps=[step2.replace(turn,forbidden)]),'outside the approved tranche')
    fail('FINAL stays paused',lambda:test_job.call('FINAL',{},'FINAL'),'separate researcher approval')
    save('plan.json',plan);save('test-response.json',fixture);save('test-links.json',explained)
    save('results.json',{'label':'OFFLINE REHEARSAL ONLY','fingerprint':fingerprint(plan),'failures_reproduced':errors,'coverage':21,'costs':bound})
    print(json.dumps({'fingerprint':fingerprint(plan),'costs':bound}))
if __name__=='__main__':
    with tempfile.TemporaryDirectory() as t, patch.object(socket.socket,'connect',side_effect=AssertionError('offline only')):
        before={p.relative_to(live):sha(p) for p in live.rglob('*') if p.is_file()}
        experiment(Path(t))
        assert before=={p.relative_to(live):sha(p) for p in live.rglob('*') if p.is_file()}
        save('preservation.json',{'unchanged_run_files':len(before),'hash_index':fingerprint({k.as_posix():v for k,v in before.items()})})
