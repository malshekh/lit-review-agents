"""Offline single-opening proposal. Run under isolated Python from sealed v39."""
import copy
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import socket
import sys
import tempfile
from unittest.mock import patch

# Reuse the sealed-environment setup, source verifier and candidate module loader.
env = runpy.run_path(str(Path(__file__).with_name('rehearse_page1001_retry.py')))
root, live, repo, output = (env[k] for k in ('root','live','repo','output'))
extension, sha, verify, fingerprint = (env[k] for k in ('extension','sha','verify','fingerprint'))
from litreview.reconciliation_paging import provider_body, body_bytes
from litreview.synthesis_job import JobStopped
from litreview import approved_scope, decisions

def read(path):
    return json.loads(path.read_bytes())

def main(tmp):
    manifest=root/'frozen_runtime_manifest.json'
    assert sha(manifest)=='b321b41ce4f2e677b9441804f0cad24a8ba236bea2797a6b546618a5e810d510'
    verify(root,read(manifest))
    links=extension('reconciliation_links')
    extension('synthesis_bounded')
    module=extension('orchestrator')
    module.RUNS_DIR=tmp/'runs'
    shutil.copytree(live,module.RUNS_DIR/live.name)
    run=module.Run(live.name)
    job,tag=run._synthesis_job()
    old_dir=repo/'runs/offline_20261123-214928_page1001_v39'
    old=read(old_dir/'plan.json')
    old_hash=fingerprint(old)
    assert old_hash=='e36ffd870e988dd9d7e3d1e61beb5400c72aacdf69a087fd007491bb8bb0e7fa'
    page=copy.deepcopy(old['pages'][0])
    del page['comparison_leads']
    page['reconciliation_instruction']=page['reconciliation_instruction'].replace('The leads are unverified suggestions. ','')
    page['issue_link_instructions']=links.RULE.replace('G0002.P6 R0078:F28 explanation', 'Gxxxx.Pn Rxxxx:Fn explanation')
    page['pause_before_lookup_judgment']=True
    extra=job.registry.retrieve([{'finding_ids':['R0078:F28']}],job.cfg['retrieval_limit'])
    ids=sorted(set(page['prefill_finding_ids'])|set(extra))
    page['prefill_finding_ids']=ids
    details=job.registry.details(ids)
    assert len(page['focus'])==21 and len(ids)==len(details['findings'])==29
    assert {row['finding_id']:fingerprint(row) for row in details['findings']}=={fid:fingerprint(job.registry.findings[fid]) for fid in ids}
    assert fingerprint(job.registry.findings['R0078:F28'])==old['lookup_record_sha256']
    payload={**page,'retrieved_evidence':details}
    def enrich(p):
        p=approved_scope.enrich(run,'A07-SYN',p)
        return decisions.attach(run.dir,'A07-SYN',{**p,'source_access':run.load('source_access.json',{})})
    step='A07-SYN_job'+tag+'_RECONCILE_1001_LOOKUP0'
    static=run.load('agent_inputs/'+step+'.json')['payload']
    enriched=enrich({**payload,**{k:static[k] for k in ('cp_syn_researcher_decision','reviewed_organization_proposals')}})
    model=run.route('A07-SYN')
    cap=job.limit('RECONCILE')
    def body(p): return body_bytes(provider_body(run,p,model,cap))
    request=body(enriched)
    digest=hashlib.sha256(request).hexdigest()
    hold=(Decimal(str(run.budget.cost(model.model,0,cap,0,0,len(request)+2048)))*Decimal('1.30')).quantize(Decimal('.000001'),rounding=ROUND_CEILING)
    repair=Decimal('1.850000')
    maximum=hold+repair
    turn='RECONCILE_1102'
    def source_hash(f):return hashlib.sha256((repo/'src/litreview'/f).read_text(encoding='utf8').encode()).hexdigest()
    plan={**old,'prior_plan':old_hash,'pages':[page,*old['pages'][1:]],'retry_turn':turn,'request_hashes':{turn:digest},
          'reservations':{turn:str(maximum)},'opening_reservation_usd':str(hold),'format_repair_caps':{turn:str(repair)},
          'max_format_repairs':1,'lookup_hashes':{},'stop_after':turn,
          'reconcile_implementation_utf8_lf_sha256':source_hash('synthesis_bounded.py'),
          'reservation_implementation_utf8_lf_sha256':source_hash('orchestrator.py')}
    auth={**run.load('reconciliation_repair_approved.json'),'approved_by':'offline test only','plan_fingerprint':fingerprint(plan),
          'approved_turns':[turn],'max_increment_usd':float(maximum),'baseline_stage_usd':plan['baseline_stage_usd']}
    run.save('reconciliation_repair_plan.json',plan)
    run.save('reconciliation_repair_approved.json',auth)
    job,_=run._synthesis_job()
    assert dict(job.reconciliation_payloads())[turn]==page
    assert run.cfg['loops']['reserved_call_repairs']==1
    class Captured(Exception): pass
    def capture(run,agent,step,p):
        assert body(p)==request and step.endswith(turn+'_LOOKUP0')
        raise Captured()
    def reserve(key,quote,*a,**kw):
        assert (Decimal(str(quote))*Decimal('1.30')).quantize(Decimal('.000001'),rounding=ROUND_CEILING)==hold
        return True,0
    with patch.object(run,'_reserve',reserve),patch.object(approved_scope,'save_delivery',capture),patch.object(run.budget,'release'):
        try:job.call('RECONCILE',payload,turn+'_LOOKUP0')
        except Captured:pass
        else:raise AssertionError('capture missed')
    checks={}
    def reject(key,fn,reason):
        try:fn()
        except (JobStopped,module.Pause) as err:
            assert reason in str(err),str(err)
            checks[key]=str(err)
        else:raise AssertionError(key)
    reject('direct further judging call',lambda:job.call('RECONCILE',payload,turn+'_LOOKUP1'),'separate researcher approval')
    # The validator fixtures enter only after the request and its production delivery have been captured.
    sample=read(old_dir/'test-response.json')
    assert 'issues' not in enriched and 'reviews' not in enriched and 'comparison_leads' not in enriched
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for child in value:
                yield from strings(child)
        elif isinstance(value, dict):
            for child in value.values():
                yield from strings(child)
    delivered_text = list(strings(enriched))
    for issue in sample['issues']:
        assert all(issue['limitation'] not in text for text in delivered_text)
    props={p['proposition_id']:p for p in job._all_props()}
    unseen_prop, unseen=next((p,f['finding_id']) for p,prop in props.items() for f in prop['evidence'] if f['finding_id'] not in ids)
    def replay(result):
        job.call=lambda *args:copy.deepcopy(result)
        job.reconcile(only_turn=turn)
    bad=copy.deepcopy(sample)
    i=bad['issues'][0]
    i['proposition_ids'].append(unseen_prop)
    i['finding_ids'].append(unseen)
    i['limitation']+='\n'+unseen_prop.removeprefix('GROUP_')+' '+unseen+' Candidate evidence for comparison.'
    reject('index-only citation',lambda:replay(bad),'invalid or unexplained')
    bad=copy.deepcopy(sample)
    bad['issues'][7]['limitation']=bad['issues'][7]['limitation'].replace('G0002.P8 R0115:F5','G0002.P8 R0115:F6')
    reject('visible finding linked to wrong proposition',lambda:replay(bad),'invalid or unexplained')
    bad=copy.deepcopy(sample)
    bad['issues'][0]['limitation']=bad['issues'][0]['limitation'].replace(links.SVM,'Model choice caused the decline.')
    reject('unsupported SVM cause',lambda:replay(bad),'unresolved cause')
    before=tmp/'before-lookup-test'
    shutil.copytree(job.dir,before)
    need={**sample,'status':'NEEDS_EVIDENCE','reviews':[],'issues':[],'retrieval_requests':[{'finding_ids':[unseen]}]}
    job.served_by=lambda:'offline test only'
    reject('new requested evidence',lambda:replay(need),'separate approval')
    assert job._committed(turn+'_LOOKUP0')['retrieval_requests']==need['retrieval_requests']
    restored,_=run._synthesis_job()
    restored.call=lambda *a:(_ for _ in ()).throw(AssertionError('unexpected dispatch'))
    reject('restart after evidence request',lambda:restored.reconcile(only_turn=turn),'separate approval')
    job.dir.rename(tmp/'lookup-test')
    before.rename(job.dir)
    job,_=run._synthesis_job()
    job.served_by=lambda:'offline test only'
    replay(sample)
    assert len(job._committed(turn)['reviews'])==21
    for t in ('RECONCILE_1002','RECONCILE_1003'):
        reject(t,lambda:run._reserve('test',1,'A07-SYN',steps=['A07-SYN_job'+tag+'_'+t+'_LOOKUP0']),'outside the approved tranche')
    job,_=run._synthesis_job()
    reject('FINAL',lambda:job.call('FINAL',{},'FINAL'),'separate researcher approval')
    key='A07-SYN_job'+tag+'_'+turn+'_LOOKUP0'
    reject('oversized repair',lambda:run._reserve('call-test',1.850001,'A07-SYN',steps=[key],margin_included=True),'format repair exceeds')
    env['save']('plan.json',plan)
    (output/'opening-request.json').write_bytes(request)
    results=dict(plan_fingerprint=fingerprint(plan),opening_bytes=len(request),opening_sha256=digest,findings=len(ids),focal=21,
        f28_sha256=old['lookup_record_sha256'],opening_usd=str(hold),repair_usd=str(repair),ceiling_usd=str(maximum),
        remaining_authorization=str(Decimal('6.287415')-maximum),remaining_stage=str(Decimal('6.7678465')-maximum),
        new_evidence_control=unseen,negative_controls=checks,actual_spend='0',live_acceptance=False)
    env['save']('rehearsal.json',results)
    print(json.dumps(results))
if __name__=='__main__':
    with tempfile.TemporaryDirectory() as temp, patch.object(socket.socket,'connect',side_effect=AssertionError('offline')):
        before={p.relative_to(live):sha(p) for p in live.rglob('*') if p.is_file()}
        main(Path(temp))
        assert before=={p.relative_to(live):sha(p) for p in live.rglob('*') if p.is_file()}
        print('Preserved',len(before),'live files')
