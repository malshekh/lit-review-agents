"""Offline reconciliation rehearsal on a disposable copy of the sealed pilot."""
from pathlib import Path
import copy
import hashlib
import json
import socket
import sys
import tempfile
import shutil
from decimal import Decimal, ROUND_CEILING
from unittest.mock import patch

ROOT = Path.cwd()
REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'vendor')]
import litreview
litreview.__path__.insert(0,str(REPO/'src/litreview'))
from litreview import paths
for key in ('REPO_ROOT','PROMPTS_DIR','SHARED_PROMPTS_DIR','AGENT_PROMPTS_DIR','CONFIG_DIR','SCHEMAS_DIR','RECORDS_DIR'):
    setattr(paths,key,ROOT/getattr(paths,key).relative_to(REPO))
from litreview import orchestrator, approved_scope, decisions
from litreview.agents.base import build_system_prompt, user_parts, _provider_response_schema
from litreview.llm.anthropic_client import message_params
from litreview.reconciliation_paging import build_pages
from litreview.synthesis_registry import fingerprint
from litreview.runtime_integrity import sha
from litreview.synthesis_job import JobStopped

RUN='20261123-214928'
TAG='30edcaaf8d90ed14'
LIVE=ROOT/'runs'/RUN
def wire(params):
    return json.dumps(params, ensure_ascii=False, allow_nan=False, separators=(',',':')).encode('utf8')
def dump(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def main(tmp):
    orchestrator.RUNS_DIR=tmp/'runs'
    shutil.copytree(LIVE,orchestrator.RUNS_DIR/RUN)
    r=orchestrator.Run(RUN);d=r.dir
    old_step='A07-SYN_job'+TAG+'_RECONCILE_0001_LOOKUP0'
    old=r.load('agent_inputs/'+old_step+'.json')['payload']
    rejected=json.loads((d/'outputs'/(old_step+'.json')).read_bytes())
    focus=[p['proposition_id'] for p in old['focus']]
    j,tag=r._synthesis_job()
    assert tag==TAG and j.identity==json.loads((d/'checkpoints/CP_SYN_approved.json').read_bytes())['fingerprint']
    assert len(focus)==len(set(focus))==32 and len(rejected['issues'])==9
    static={k:old[k] for k in ('cp_syn_researcher_decision','reviewed_organization_proposals','approved_scope_guide','source_access')}
    agent='A07-SYN';model=r.route(agent);system=build_system_prompt(agent)
    shape=_provider_response_schema(agent,'A07-SYN.bounded-reconcile.schema.json',model.provider,model.model)
    cap=j.limit('RECONCILE')
    def body(payload):
        from litreview.reconciliation_paging import provider_body
        return provider_body(r,{**payload,**static},model,cap)
    measure=lambda p:len(wire(body(p)))
    usd=lambda n,out: (Decimal(str(r.budget.cost(model.model,0,out,0,0,n)))*Decimal('1.30')).quantize(Decimal('.000001'),rounding=ROUND_CEILING)
    questions = [
        "Which R0078 analyses reuse measurements, and what is known about independence?",
        "Which propositions share the R0115 abstract and its access limitations?",
        "Which benchmark claims depend on the same R0058 data?",
        "Which R0090 results concern model analytes and which concern erlotinib?",
        "Compare the three Israel classifiers: which metric, split, task and uncertainty does each value describe?",
        "Compare buffer and synthetic-fluid binary-category performance separately for each anthracycline.",
        "Do opposite intensity responses use comparable constructs, analytes and conditions?",
        "Are the two daunorubicin binding estimates defined on the same unit of analysis?",
        "Can the bacterial partitioning result be compared directly with classification on one optical-array test set?"
    ]
    pages=build_pages(j,focus,rejected['issues'],measure,28,165000,questions)
    j.evidence_pages=pages
    props={p['proposition_id']:p for p in j._all_props()}
    records=j.registry.findings
    output=LIVE/'data/recovery/reconciliation_evidence_review';output.mkdir(exist_ok=True,parents=True)
    mapping={}
    for pid,prop in props.items():
        fids=[e['finding_id'] for e in prop['evidence']]
        mapping[pid]={'original_focal':pid in focus,'finding_roles':prop['evidence'],'source_items':prop['source_item_ids'],
                      'finding_hashes':{f:fingerprint(records[f]) for f in fids},
                      'cross_group_candidates':[other for other,v in props.items() if other.split('.')[0]!=pid.split('.')[0]
                          and set(fids).intersection(e['finding_id'] for e in v['evidence'])]}
    dump(output/'proposition_map.json',mapping)
    details_dir=output/'requests';details_dir.mkdir(exist_ok=True)
    summary=[];rendered={};seen_leads=[]
    for turn,p in j.reconciliation_payloads():
        ids=p['prefill_finding_ids'];full={**p,'retrieved_evidence':j.registry.details(ids)}
        # Capture the real production request after enrichment and decision attachment, before any transport.
        class Captured(Exception): pass
        def capture(run,agent_id,step,payload):
            rendered[turn]=copy.deepcopy(payload)
            raise Captured()
        with patch.object(r,'_reserve',return_value=(True,0)),patch.object(approved_scope,'save_delivery',capture),patch.object(r.budget,'release'):
            try:j.call('RECONCILE',full,turn+'_LOOKUP0')
            except Captured:pass
            else:raise AssertionError('production interception failed')
        assert rendered[turn]=={**full,**static}
        req=body(full);b=wire(req);(details_dir/(turn+'.json')).write_bytes(b)
        foc=[a['proposition_id'] for a in p['focus']]
        leads=[a['lead'] for a in p['comparison_leads']];seen_leads+=leads
        ids=set(ids)
        # A full registry record is sent for every finding used by every focal proposition, including appraisals.
        assert all({e['finding_id'] for e in props[pid]['evidence']}<=ids for pid in foc)
        assert all(h['inspect'] and set(h['inspect'])<=ids for h in p['comparison_leads'])
        assert len(req['messages'])==1 and all(fingerprint(row)==fingerprint(records[row['finding_id']]) for row in full['retrieved_evidence']['findings'])
        summary.append({'turn':turn,'cohort':'rejected32' if foc[0] in focus else 'remaining18','focus':foc,'findings':sorted(ids),
                        'leads':leads,'body_sha256':hashlib.sha256(b).hexdigest(),'request_bytes':len(b),
                        'input_upper':len(b)+2048,'output_cap':cap,'cold_reservation_usd':str(usd(len(b)+2048,cap))})
    assert sorted(seen_leads)==list(range(1,10))
    allf=[pid for page in summary for pid in page['focus']]
    assert len(allf)==len(set(allf))==len(props)==50 and set(allf)==set(props)
    assert {pid for page in summary if page['cohort']=='rejected32' for pid in page['focus']}==set(focus)
    for page in summary:
        for pid in page["focus"]:
            mapping[pid]["page"] = page["turn"]
            mapping[pid]["comparison_leads"] = [i for i,issue in enumerate(rejected["issues"],1) if pid in issue["proposition_ids"]]
    dump(output/'proposition_map.json',mapping)
    dump(output/'pages.json',summary)
    dump(output/'lead_map.json',[{'lead':n,'original_unaccepted_issue':z,'recheck_on':next(a['turn'] for a in summary if n in a['leads'])} for n,z in enumerate(rejected['issues'],1)])
    dump(output/"plan.json",dict(run_id=RUN,job_identity=j.identity,rejected_response_sha256=sha(d/"outputs"/(old_step+".json")),registry=j.registry.digest,baseline_stage_usd=round(r.budget.stage_committed("A07"),7),request_hashes={row["turn"]:row["body_sha256"] for row in summary},reservations={row["turn"]:row["cold_reservation_usd"] for row in summary},pages=pages))
    print([(a['turn'],len(a['focus']),len(a['findings']),a['request_bytes'],a['cold_reservation_usd']) for a in summary],flush=True)
    return r,j,summary,output,usd,records,props,body,cap

def exercise(r,j,pages,output,usd,records,props,body,cap):
    from litreview.synthesis_job import JobStopped
    from litreview.reconciliation_paging import check_spend
    from litreview.budget import StageCapReached
    old='A07-SYN_job'+TAG+'_RECONCILE_0001_LOOKUP0'
    base=json.loads((r.dir/'outputs'/(old+'.json')).read_bytes())
    # Model outputs below are test fixtures; only the production builder and validators are under test.
    def response():
        return {**base,'reviews':[],'issues':[],'warnings':[],'limitations':[],'retrieval_requests':[],'status':'COMPLETE'}
    israel={'kind':'CONTEXT_DEPENDENT','proposition_ids':['GROUP_G0004.P3','GROUP_G0003.P5','GROUP_G0005.P1'],
            'finding_ids':['R0078:F12','R0078:F13','R0078:F14'],
            'limitation':'Four-drug identity in buffer: SVM 98 +/- 4% CV and 50% test; decision tree 94 +/- 12% CV and 100% test; XGBoost 100% CV and 100% test. The cause of the SVM drop is unresolved; the different evaluations do not establish a contradiction or model superiority.'}
    other={'kind':'SHARED_EVIDENCE','proposition_ids':['GROUP_G0002.P6','GROUP_G0003.P6'],
           'finding_ids':['R0078:F26','R0078:F28'],'limitation':'One Table 1 contributes the comparison of sensor-selection criteria and the specific daunorubicin concentration-PCA wavelength-shift feature. These are distinct observations from one publication.'}
    owner=next(p for p in pages if 5 in p['leads'])
    assert any(pid not in owner['focus'] for pid in israel['proposition_ids'])
    assert set(israel['finding_ids'])<=set(owner['findings'])
    quote=records['R0078:F13']['span']
    assert all(t in quote for t in ['94 \u00b1 12% (DT)','98 \u00b1 4% (SVM)','100% (XGBoost)','100%, 50%, and 100%'])
    assert 'reason' in records['R0078:F13']['plain_language_limit'] and 'unresolved' in records['R0078:F13']['plain_language_limit']
    assert owner==pages[0] and 'R0078:F28' not in owner['findings'] and 'GROUP_G0003.P6' in owner['focus']
    assert 'GROUP_G0002.P6' in pages[1]['focus']
    judged=[];lookups=[]
    def fixture(mode,payload,turn,negative=False):
        out=response()
        focus=[q['proposition_id'] for q in payload['focus']]
        visible={q['finding_id'] for q in payload['retrieved_evidence']['findings']}
        if turn.startswith(owner['turn']):
            if 'R0078:F28' not in visible and not negative:
                out.update(status='NEEDS_EVIDENCE',retrieval_requests=[dict(finding_ids=['R0078:F28'])])
                lookups.append(turn)
                return out
            out['issues']=[copy.deepcopy(israel),copy.deepcopy(other)]
        implicated={p for i in out['issues'] for p in i['proposition_ids']}
        out['reviews']=[{'proposition_id':p,'outcome':'ISSUES_IDENTIFIED' if p in implicated else 'NO_CONFLICT_IDENTIFIED',
                         'rationale':'Offline coverage fixture.'} for p in focus]
        if not negative:judged.extend(focus)
        return out
    j.call=lambda m,p,t:fixture(m,p,t,True)
    try:j.reconcile()
    except JobStopped as exc:assert 'lacks evidence anchors' in str(exc)
    else:raise AssertionError('accepted unseen evidence')
    assert j._committed(owner['turn']) is None
    j.call=fixture;j.served_by=lambda:'offline fixture'
    j.reconcile()
    assert len(judged)==len(set(judged))==50 and len(lookups)==1
    accepted=j._committed(owner['turn'])
    assert [i['kind'] for i in accepted['issues']]==['CONTEXT_DEPENDENT','SHARED_EVIDENCE']
    def israel_expected(issue):
        return (issue['kind']=='CONTEXT_DEPENDENT' and set(issue['finding_ids'])==set(israel['finding_ids'])
                and all(x in issue['limitation'] for x in ('98 +/- 4% CV and 50% test','94 +/- 12% CV and 100% test',
                    '100% CV and 100% test','cause of the SVM drop is unresolved')))
    assert israel_expected(accepted['issues'][0])
    assert not israel_expected({**accepted['issues'][0], 'kind':'UNRESOLVED_CONTRADICTION'})
    j.call=lambda *args:(_ for _ in ()).throw(AssertionError('repeat call on restart'))
    j.reconcile()
    def money(p):return Decimal(p['cold_reservation_usd'])
    prefix=sum(money(p) for p in pages if p['cohort']=='rejected32')
    total=sum(money(p) for p in pages)
    stage=Decimal(str(round(r.budget.stage_committed('A07'),7)))
    stage_cap=Decimal(str(r.budget.stage_caps['A07']))
    plan=json.loads((output/'plan.json').read_bytes())
    auth={'approved':True,'approved_by':'offline test only','job_tag':TAG,
          'plan_fingerprint':fingerprint(plan),'approved_turns':[a['turn'] for a in pages],
          'baseline_stage_usd':float(stage),'max_increment_usd':float(total)}
    check_spend(auth,stage,total)
    try:check_spend(auth,stage+Decimal('0.01'),total)
    except ValueError:pass
    else:raise AssertionError('aggregate ceiling not enforced')
    r.save('reconciliation_repair_plan.json',plan);r.save('reconciliation_repair_approved.json',auth)
    restored,_=r._synthesis_job()
    assert [p for _,p in restored.reconciliation_payloads()]==plan['pages']
    assert all(restored._committed(p['turn']) for p in pages)
    test_page = dict(restored.evidence_pages[0])
    test_page["retrieved_evidence"] = j.registry.details(test_page["prefill_finding_ids"])
    test_page["reconciliation_instruction"] += " Changed after review."
    try: restored.call("RECONCILE",test_page,pages[0]["turn"]+"_LOOKUP0")
    except orchestrator.Pause as exc: assert "reviewed provider body" in str(exc)
    else: raise AssertionError("accepted request drift")
    original = restored.evidence_pages
    restored.evidence_pages = [{**original[0],"comparison_leads":[]}, *original[1:]]
    try: restored._committed(pages[0]['turn'])
    except JobStopped as exc: assert 'fingerprint mismatch' in str(exc)
    else: raise AssertionError('reused a result under a different page identity')
    restored.evidence_pages = original
    # Exercise the actual reservation guard on the copy, including an estimated retry that does not fit.
    step='A07-SYN_job'+TAG+'_'+pages[0]['turn']+'_LOOKUP1'
    try:r._reserve('offline-test-over',float(total)+0.01,'A07-SYN',steps=[step],margin_included=True)
    except orchestrator.Pause as exc:assert 'incremental reservation' in str(exc)
    else:raise AssertionError('over-budget retry admitted')
    # Intercept a real format-repair dispatch before it can send or reserve money.
    from litreview.agents.base import run_agent
    from litreview.reconciliation_paging import generation_body, body_bytes
    sample = dict(restored.evidence_pages[0])
    sample["retrieved_evidence"] = j.registry.details(sample["prefill_finding_ids"])
    class RepairCaptured(Exception): pass
    def capture_repair(attempt, system, message, model):
        assert attempt == 1
        assert json.loads(message[-1]["text"].split("\n",1)[1]) == sample["retrieved_evidence"]
        params = generation_body(system, message, model, model.max_tokens, model.cache_system, model.cache_ttl)
        reserve_tokens = r.cfg["admission"]["reasoning_reserve_tokens"].get(model.provider,0)
        expected = r.budget.cost(model.model,0,model.max_tokens+reserve_tokens,0,0,len(body_bytes(params))+2048)
        with patch.object(r,"_reserve",return_value=(True,0)) as capture:
            r._call_guard("A07-SYN",step,None)(attempt, system, message, model)
            assert capture.call_args.args[1] == expected
        raise RepairCaptured()
    try:
        run_agent("A07-SYN",sample,r.dir,step,r.budget,r.prov,model=r.route("A07-SYN"),
                  schema_file="A07-SYN.bounded-reconcile.schema.json",repair_from=("{}","missing reviews"),
                  dispatch_guard=capture_repair)
    except RepairCaptured: pass
    else: raise AssertionError("repair capture failed")
    for p in pages:
        request=json.loads((output/'requests'/(p['turn']+'.json')).read_bytes())
        assert len(request['messages'])==1 and request['max_tokens']==cap
    # Bound additional details after 1 or 2 lookups: singleton marginal serialized sizes
    # overcount shared contexts, entity records and framing. Add separator slack per record.
    opt=[]
    for page,(_,q) in zip(pages,restored.reconciliation_payloads()):
        ids=set(page['findings'])
        size=lambda chosen:len(wire(body({**q,'retrieved_evidence':j.registry.details(sorted(chosen))})))
        first=size(ids)
        assert first==page['request_bytes']
        deltas=sorted((size(ids|{f})-first+16 for f in records if f not in ids),reverse=True)
        costs=[usd(first+2048+sum(deltas[:k]),cap) for k in [12,24]]
        opt.append({'turn':page['turn'],'lookup1_upper_usd':str(costs[0]),'lookup2_upper_usd':str(costs[1])})
    facts={'job':TAG,'plan_fingerprint':fingerprint(plan),'focus_reviewed':len(judged),'original_focus_reviewed':32,
           'eligible_additional_focus_reviewed':18,'original_rejected_issues_routed':9,'distinct_cross_page_compares':2,
           'new_non_seeded_pair':other,'israel_fixture':israel,'unseen_negative':'rejected by production anchor validator',
           'format_repair_visibility_and_quote':'verified before transport', 'restart_dispatched':False,'network':'disabled','actual_charge_usd':0,'prior_stage_committed_usd':str(stage),
           'remaining_A07_usd':str(stage_cap-stage),'rejected32_primary_and_proposed_inclusive_cap_usd':str(prefix),
           'all50_primary_and_proposed_inclusive_cap_usd':str(total),
           'all50_remaining_A07_if_spent_to_ceiling_usd':str(stage_cap-stage-total),
           'lookup_upper_without_incremental_ceiling':opt,'all50_primary_plus_two_lookups_before_repairs_usd':
              str(total+sum(Decimal(o['lookup1_upper_usd'])+Decimal(o['lookup2_upper_usd']) for o in opt)),
           'additional_stage_room_before_FINAL_at_actuals':True}
    dump(output/'rehearsal.json',facts)
    print(json.dumps(facts),flush=True)


if __name__=='__main__':
    with tempfile.TemporaryDirectory() as tmp, patch.object(socket.socket,'connect',side_effect=AssertionError('offline only')):
        def audit_files():
            return {f.relative_to(LIVE).as_posix():sha(f) for f in LIVE.rglob('*')
                    if f.is_file() and 'reconciliation_evidence_review' not in f.parts}
        before = audit_files()
        exercise(*main(Path(tmp)))
        assert before == audit_files(), 'live audit record changed'
        dump(LIVE/'data/recovery/reconciliation_evidence_review/preservation.json', before)
