import hashlib,json
from pathlib import Path
import pytest
from litreview import orchestrator as orch, pilot_authorization as pa, checkpoints
from litreview.synthesis_registry import fingerprint

# Exercise real financial gates; the repository otherwise disables them in its autouse fixture.
pytestmark = pytest.mark.projection_guard

@pytest.fixture
def run(tmp_path,monkeypatch):
    monkeypatch.setattr(orch,'RUNS_DIR',tmp_path/'runs')
    r=orch.Run('pilot');r.save_state({'stage':'scope','status':'READY','counters':{},'execution_mode':'STAGED_PILOT'})
    key=tmp_path/'private-evaluator'/'key.txt';key.parent.mkdir();key.write_text('Synthetic evaluator-only fixture; no scientific answer key',encoding='utf-8')
    pa.record_key(r,{'version':'test-1','sha256':hashlib.sha256(key.read_bytes()).hexdigest(),'commit':'test-only-commit',
        'verified_by':'Test human','approved_at':'2026-10-30','store_path':str(key),'human_verified':True})
    return r

def authorize(r,stage=pa.STAGE_1):
    review=pa.request(r,stage);return pa.approve(r,stage,review['fingerprint'],'Test human')

def spend(r,usd):
    r.budget.log_path.write_text(json.dumps({'agent':'A02-SP','step':'prior','time':'2026-10-30T00:00:00','cost_usd':usd})+'\n',encoding='utf-8')

def test_stage1_own_projection_and_no_manuscript_scope(run):
    p=pa.project(run,pa.STAGE_1)
    assert p['verdict']=='WITHIN_CAP' and p['projected_total_usd']<35
    assert not any(x['stage'] in pa.SECOND for x in p['lines'])
    a=authorize(run);assert a['status']==pa.STAGE_1
    pa.require(run,'A02-SP');assert not run.budget.reservations()

@pytest.mark.parametrize('agent',sorted(pa.SECOND))
def test_stage1_cannot_dispatch_or_reserve_stage2(run,monkeypatch,agent):
    authorize(run);calls=[];monkeypatch.setattr(orch,'run_agent',lambda *a,**k:calls.append(a))
    with pytest.raises((orch.Pause,pa.AuthorizationRequired)):run.agent(agent,{},'blocked')
    with pytest.raises(orch.Pause):run._reserve('blocked',1,agent,'test',steps=['blocked'])
    assert not calls and not run.budget.reservations() and run.budget.spent()==0

@pytest.mark.parametrize('spent,held,future,allowed',[(0,0,35/1.3,True),(10,12,10,True),(10,12,10.00001,False),(35,0,0,True),(35.000001,0,0,False)])
def test_future_only_margin_and_exact_boundaries(spent,held,future,allowed):
    # Avoid a binary floating boundary in this test's first future amount.
    if spent==held==0:future=26.92307692307692
    p=pa.admit(spent,held,future)
    assert (p['verdict']=='WITHIN_CAP')==allowed
    assert p['projected_total_usd']==pytest.approx(spent+held+1.3*future)

@pytest.mark.parametrize('amount,stops',[(25,False),(25.000001,True),(35,True)])
def test_review_point_still_stops_before_commitment(run,monkeypatch,amount,stops):
    monkeypatch.setattr(run,'pause_for_checkpoint',lambda cp:(_ for _ in ()).throw(orch.Pause(cp)))
    if stops:
        with pytest.raises(orch.Pause,match='CP_SPEND'):run._spend_review('A02-SP','test',amount)
    else:run._spend_review('A02-SP','test',amount)
    assert run.budget.cap==35 and not run.budget.reservations()

def test_unknown_commitment_requires_reconciliation_not_double_counting(run):
    run.budget.reserve('unknown',2,'A05-KE')
    with pytest.raises(pa.AuthorizationRequired,match='Unsettled'):pa.project(run,pa.STAGE_1)
    assert run.budget.reserved()==2

def test_logged_interactive_cost_offsets_its_held_reservation_once(run):
    run.budget.reserve('interactive',5,'A02-SP')
    run.budget.record('A02-SP','openai','gpt-6.1-sol',1_000_000,0,step='request',reservation_key='interactive')
    assert run.budget.spent()==4 and run.budget.reserved()==1
    assert pa.admit(run.budget.spent(),run.budget.reserved(),10)['projected_total_usd']==18
    run.budget.release('interactive');assert run.budget.spent()==4 and run.budget.reserved()==0

def test_current_commitment_replaces_future_work_once(run):
    authorize(run);before=pa.project(run,pa.STAGE_1)
    candidate=pa.project(run,pa.STAGE_1,candidate=('A02-SP',1))
    # One dollar is moved from the future allowance into a strict commitment; its 30% margin is removed.
    assert candidate['committed_usd']==1
    assert before['uncommitted_future_usd']-candidate['uncommitted_future_usd']==pytest.approx(1.05)
    assert candidate['projected_total_usd']==pytest.approx(before['projected_total_usd']-1.365+1)

def test_reservation_guard_stops_before_cap_and_leaves_no_hold(run):
    authorize(run)
    with pytest.raises(orch.Pause):run._reserve('too-big',35,'A02-SP',steps=['too-big'])
    assert not run.budget.reservations()

def test_stage2_separate_approval_and_over_budget_partial(run,monkeypatch):
    authorize(run);run.save_state({**run.state(),'stage':'cp3'})
    monkeypatch.setattr(pa,'scientific_ready',lambda r:{'status':'COMPLETE'})
    with pytest.raises(pa.AuthorizationRequired,match='FULL_PIPELINE'):pa.require(run,'A08-OL')
    assert run.state()['evaluation_result']=='COMPLETED_STAGE_1_PARTIAL_EVALUATION'
    assert run.state()['stage']=='cp3' and not run.budget.reservations()
    real=pa.project
    def projection(r,stage,**kw):
        if stage==pa.STAGE_2:return {**pa.admit(r.budget.spent(),r.budget.reserved(),30),'lines':[]}
        return real(r,stage,**kw)
    monkeypatch.setattr(pa,'project',projection)
    review=pa.request(run,pa.STAGE_2)
    with pytest.raises(pa.AuthorizationRequired,match='exceeds'):pa.approve(run,pa.STAGE_2,review['fingerprint'],'Test human')
    assert run.load('pilot_'+pa.STAGE_2+'.json') is None and not run.budget.reservations()

@pytest.mark.parametrize('mutation',['configuration','prices','plan','key','scope','evidence','projection'])
def test_mutations_invalidate_affected_approval(run,monkeypatch,mutation):
    if mutation=='evidence':run.save('validated_findings.json',[])
    authorize(run)
    if mutation=='configuration':run.cfg={**run.cfg,'test_change':True}
    elif mutation=='prices':run.budget.prices={**run.budget.prices,'test_model':{'input':1,'output':1}}
    elif mutation=='plan':run.save('pilot_financial_plan.json',{'revision':2})
    elif mutation=='key':Path(run.load('pilot_reference_approval.json')['store_path']).write_text('changed',encoding='utf-8')
    elif mutation=='scope':run.save('selected_corpus.json',[{'record_id':'other','pmid':'1'}])
    elif mutation=='evidence':run.save('validated_findings.json',[{'changed':True}])
    else:
        a=run.load('pilot_'+pa.STAGE_1+'.json');a['projection']['uncommitted_future_usd']=0;run.save('pilot_'+pa.STAGE_1+'.json',a)
    with pytest.raises(pa.AuthorizationRequired):pa.require(run,'A02-SP')

@pytest.mark.parametrize('unapproved',[False,True])
def test_missing_or_unapproved_key_blocks_even_stage1(run,unapproved):
    if unapproved:
        meta=run.load('pilot_reference_approval.json');meta['human_verified']=False;run.save('pilot_reference_approval.json',meta)
    else:run.data('pilot_reference_approval.json').unlink()
    with pytest.raises(pa.AuthorizationRequired,match='reference'):pa.request(run,pa.STAGE_1)
    assert not run.budget.reservations()

def test_reference_inside_retrieval_repository_is_rejected(run):
    meta=run.load('pilot_reference_approval.json');meta['store_path']=str(pa.REPO_ROOT/'docs/pilot_reference_findings.md')
    with pytest.raises(pa.AuthorizationRequired,match='outside'):pa.record_key(run,meta)
    assert Path(pa.key_metadata(run)['store_path']).name=='key.txt'

def test_approval_never_bypasses_scientific_cp3_gate(run):
    authorize(run)
    with pytest.raises(pa.AuthorizationRequired,match='CP3'):pa.request(run,pa.STAGE_2)
    assert not run.budget.reservations()

def test_new_runs_are_staged_by_default(tmp_path,monkeypatch):
    monkeypatch.setattr(orch,'RUNS_DIR',tmp_path)
    rid=orch.new_run('test only')
    assert pa.enabled(orch.Run(rid))

def mock_provider(run,monkeypatch,reply=None):
    from litreview.agents import base
    from litreview.llm.base import LLMResponse
    calls=[]
    def complete(*args,**kw):
        calls.append(kw)
        if isinstance(reply,Exception):raise reply
        return LLMResponse(json.dumps({'status':'COMPLETE'}),'openai','gpt-6.1-sol',100,20)
    monkeypatch.setattr(base,'complete',complete)
    monkeypatch.setattr(base,'validate',lambda *a,**k:None) # finance fixture; no assertion of scientific validity
    monkeypatch.setattr(run,'_context_check',lambda *a,**k:{'input_counted':100,'input_byte_bound':100,'output_reserve':32000})
    monkeypatch.setattr(run,'_context_actual',lambda *a:None)
    monkeypatch.setattr(orch.model_record,'add',lambda *a,**k:None)
    return calls

def test_actual_dispatch_guard_and_accepted_resume_do_not_duplicate_calls(run,monkeypatch):
    authorize(run);calls=mock_provider(run,monkeypatch)
    first=run.agent('A02-SP',{'evaluation':'finance only'},'scope_once')
    assert len(calls)==1 and not run.budget.reservations()
    entries=run.budget.entries();key=entries[0]['reservation_key']
    # Simulate interruption after the accepted output/cost but before hold cleanup.
    run.budget.reserve(key,1,'A02-SP')
    second=run.agent('A02-SP',{'evaluation':'finance only'},'scope_once')
    assert first==second and len(calls)==1 and len(run.budget.entries())==1
    assert not run.budget.reservations()
    assert 'Synthetic evaluator-only' not in json.dumps(calls)

def test_uncertain_provider_submission_is_held_and_never_automatically_retried(run,monkeypatch):
    authorize(run);calls=mock_provider(run,monkeypatch,ConnectionError('uncertain submission'))
    with pytest.raises(orch.AgentError):run.agent('A02-SP',{},'uncertain')
    held=run.budget.reservations();assert len(held)==1 and len(calls)==1
    with pytest.raises(orch.Pause):run.agent('A02-SP',{},'uncertain')
    assert run.budget.reservations()==held and len(calls)==1

def test_stage2_approval_cannot_reuse_stage1_fingerprint(run,monkeypatch):
    a=authorize(run);monkeypatch.setattr(pa,'scientific_ready',lambda r:{})
    with pytest.raises(pa.AuthorizationRequired,match='matching'):pa.approve(run,pa.STAGE_2,a['fingerprint'],'Test human')
    assert run.load('pilot_'+pa.STAGE_2+'.json') is None

def test_stage1_scope_blocks_batches_after_cp3_even_with_scientific_approval(run,monkeypatch):
    authorize(run);monkeypatch.setattr(pa,'scientific_ready',lambda r:{'status':'COMPLETE'})
    run.save_state({**run.state(),'stage':'cp3'})
    with pytest.raises(orch.Pause,match='FULL_PIPELINE'):run._batch_gate('A09-WRI',['forbidden'],1)
    assert not run.budget.reservations()

def test_current_cp3_required_even_if_financial_record_was_forged(run):
    a=authorize(run)
    run.save('pilot_'+pa.STAGE_2+'.json',{**a,'status':pa.STAGE_2})
    with pytest.raises(pa.AuthorizationRequired,match='CP3'):pa.require(run,'A08-OL')


def test_cp3_completion_remains_at_cp3_without_financial_promotion(run,monkeypatch):
    authorize(run);run.save_state({**run.state(),'stage':'cp3'})
    monkeypatch.setattr(run,'preflight_routing',lambda:None)
    monkeypatch.setattr(run,'stage_cp3',lambda st:'outline') # supplied scientific approval boundary only
    monkeypatch.setattr(pa,'scientific_ready',lambda r:{'status':'COMPLETE'})
    result=run.run()
    assert result.startswith('PAUSED') and run.state()['stage']=='cp3'
    assert run.state()['evaluation_result']=='COMPLETED_STAGE_1_PARTIAL_EVALUATION'
    assert not run.budget.reservations()



def test_explicit_reprojection_after_spend_requires_fresh_approval(run):
    authorize(run);spend(run,0.2)
    review=pa.request(run,pa.STAGE_1)
    with pytest.raises(pa.AuthorizationRequired,match='Revised projection'):pa.require(run,'A02-SP')
    pa.approve(run,pa.STAGE_1,review['fingerprint'],'Test human')
    pa.require(run,'A02-SP')


def test_invalidated_forecast_requires_reapproval_and_preserves_work(run):
    authorize(run);run.save('accepted_scientific_fixture.json',{'retained':True})
    run._supersede_projection('unexpected paid failure')
    with pytest.raises(pa.AuthorizationRequired,match='stale'):pa.require(run,'A02-SP')
    assert run.load('accepted_scientific_fixture.json')=={'retained':True}
    authorize(run);pa.require(run,'A02-SP')


def test_separate_stage2_approval_opens_only_its_scope(run,monkeypatch):
    # Finance-only low-cost scenario. Scientific gate is supplied here and separately enforced above.
    authorize(run);run.save_state({**run.state(),'stage':'cp3'})
    monkeypatch.setattr(pa,'scientific_ready',lambda r:{'status':'COMPLETE'})
    original=pa.project
    def cheap(r,stage,**kwargs):
        if stage==pa.STAGE_2:return {**pa.admit(r.budget.spent(),r.budget.reserved(),1),'lines':[]}
        return original(r,stage,**kwargs)
    monkeypatch.setattr(pa,'project',cheap)
    with pytest.raises(pa.AuthorizationRequired,match='FULL_PIPELINE'):pa.require(run,'A08-OL')
    a=authorize(run,pa.STAGE_2)
    assert a['status']==pa.STAGE_2 and a['scope']==pa.STAGE_2
    pa.require(run,'A08-OL');assert not run.budget.reservations()
    assert 'evaluation_result' not in run.state()
    run.save('manuscript_plan.json',{'changed':True})
    with pytest.raises(pa.AuthorizationRequired,match='stale'):pa.require(run,'A08-OL')


def test_a07_candidate_excludes_its_entire_modeled_unit_including_cache(run):
    before=pa.project(run,pa.STAGE_1)
    current=next(x for x in before['lines'] if x['stage']=='A07-SYN')
    cache=next(x for x in before['lines'] if x['stage']=='A07 cache writes')
    after=pa.project(run,pa.STAGE_1,in_flight=frozenset({'GROUP_1'}),candidate=('A07-SYN',1))
    assert after['committed_usd']==1
    assert before['uncommitted_future_usd']-after['uncommitted_future_usd']==pytest.approx((current['usd']+cache['usd'])/current['calls']*1.05)


def test_completed_stage2_work_is_not_forecast_again_and_old_plan_is_not_credited(run,monkeypatch):
    monkeypatch.setattr(pa,'scientific_ready',lambda r:{'status':'COMPLETE'})
    run.save_state({**run.state(),'stage':'cp3'})
    before=pa.project(run,pa.STAGE_2)
    out={'status':'COMPLETE'};path=run.dir/'outputs'/'A10-RV_done.json';path.parent.mkdir();path.write_text(json.dumps(out),encoding='utf-8')
    run.budget.log_path.write_text(json.dumps({'agent':'A10-RV','step':'A10-RV_done','time':'2026-10-30T00:00:00','cost_usd':.1})+'\n',encoding='utf-8')
    run.save('pilot_requests.json',{'A10-RV_done':{'agent':'A10-RV','projection_basis':pa.work_basis(run),'output_hash':fingerprint(out),'forecast_usd':1}})
    after=pa.project(run,pa.STAGE_2)
    assert before['uncommitted_future_usd']-after['uncommitted_future_usd']==pytest.approx(1.05)
    assert after['spent_usd']==.1
    run.save('manuscript_plan.json',{}) # a different plan cannot inherit old work credits
    changed=pa.project(run,pa.STAGE_2)
    assert next(x for x in changed['lines'] if x['stage']=='A10-RV')['completed_forecast_usd']==0


def test_staged_projection_preserves_conservative_long_context_pricing(run,monkeypatch):
    from litreview.tools import downstream_projection as dp
    monkeypatch.setattr(pa,'scientific_ready',lambda r:{'status':'COMPLETE'})
    # Isolate one 300k-byte production-pricing request on GPT's actual 272k threshold.
    monkeypatch.setattr(dp,'requests',lambda *a,**k:{a:([(300000,None,'outline')] if a=='A08-OL' else [],'fixture') for a in ('A08-OL','A09-WRI','A11-RC','A12-EDI')})
    run.save_state({**run.state(),'stage':'outline'})
    p=pa.project(run,pa.STAGE_2)
    line=next(x for x in p['lines'] if x['stage']=='A08-OL')
    assert line['long_context_calls']==1 and line['basis']=='STAGED_FORECAST'
    assert line['gross_forecast_usd']==pytest.approx((300000/2.1*4+16000*15)/1e6)
    run._reproject('outline')
    saved=run.load('cost_projection.json');assert saved['created']
    run.prov.tool_run('admission','test',{'agent':'A08-OL','crosses_threshold':True})
    run._check_long_context('A08-OL',{'input_bound':300000,'long_context_threshold':272000,'model':'gpt-6.1-sol'})


def test_stage2_batch_stops_before_even_context_counter_or_upload(run,monkeypatch):
    from litreview.batch_stage import BatchStage
    authorize(run)
    monkeypatch.setattr(pa,'scientific_ready',lambda r:{'status':'COMPLETE'})
    seen=[];monkeypatch.setattr(run,'_context_check',lambda *a:seen.append(a))
    batch=BatchStage(run,'A09-WRI',[('forbidden',{})],lambda *a:None)
    with pytest.raises(orch.Pause,match='FULL_PIPELINE'):batch._submit(run.route('A09-WRI'),['forbidden'])
    assert not seen and not run.budget.reservations()
