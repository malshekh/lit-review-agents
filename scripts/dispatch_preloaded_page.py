"""One approved reconciliation entry point. No other stage is invoked."""
import hashlib
import json
from pathlib import Path
from litreview.orchestrator import Run
from litreview.synthesis_registry import fingerprint
from litreview.synthesis_job import JobStopped

PIN='01620d1bd26a14d1ded04bc3347883452911716b8b2353f7b3459568c6236961'
RUN='20261123-214928'
TURN='RECONCILE_1102'

def main():
    r=Run(RUN)
    archive=r.dir/'data/recovery/page1001_preloaded'
    plan=json.loads((archive/'plan.json').read_bytes())
    body=(archive/'opening-request.json').read_bytes()
    assert fingerprint(plan)==PIN and len(body)==164715 and hashlib.sha256(body).hexdigest()==plan['request_hashes'][TURN]
    assert r.cfg['loops']['reserved_call_repairs']==1 and r.cfg['loops']['max_truncation_retries']==0
    for filename, key in [('orchestrator.py','reservation_implementation_utf8_lf_sha256'),
                          ('synthesis_bounded.py','reconcile_implementation_utf8_lf_sha256'),('reconciliation_links.py','guard_utf8_lf_sha256')]:
        source=Path(__file__).resolve().parents[1]/'src/litreview'/filename
        assert hashlib.sha256(source.read_text(encoding='utf8').encode()).hexdigest()==plan[key]
    # This entry point is for a single launch. A restart needs inspection of the journal.
    started=archive/'dispatch-started.json'
    if started.exists():
        raise RuntimeError('single launch already recorded; inspect saved receipts before resuming')
    assert abs(r.budget.stage_committed('A07')-3.6421535)<1e-8 and len(r.budget.reservations())==5
    auth=dict(approved=True,approved_by='researcher, explicit single preloaded page 1001 retry',job_tag='30edcaaf8d90ed14',
              approved_turns=[TURN],plan_fingerprint=PIN,baseline_stage_usd=3.6421535,max_increment_usd=4.537919)
    for name, value in [('reconciliation_repair_approved.json',auth),('reconciliation_repair_plan.json',plan)]:
        previous=r.load(name)
        if previous!=value:
            backup=archive/('v39_'+name)
            if not backup.exists(): backup.write_bytes(r.data(name).read_bytes())
            r.save(name,value)
    job,tag=r._synthesis_job()
    assert tag==auth['job_tag'] and all(job._committed('GROUP_G%04d'%n) for n in range(1,10))
    assert fingerprint(job.registry.findings['R0078:F28'])==plan['lookup_record_sha256']
    page=dict(job.reconciliation_payloads())[TURN]
    assert len(page['prefill_finding_ids'])==29 and len(page['focus'])==21 and not job._committed(TURN)
    step='A07-SYN_job'+tag+'_'+TURN+'_LOOKUP0'
    call=job.call
    def guarded(mode,payload,name):
        if mode!='RECONCILE' or name!=TURN+'_LOOKUP0':raise JobStopped('further judging turn requires approval')
        out=call(mode,payload,name)
        if (r.dir/'outputs'/(step+'.raw1.txt')).exists():
            from litreview.agents.base import parse_json
            original=(r.dir/'outputs'/(step+'.raw0.txt')).read_text(encoding='utf8')
            try: before=parse_json(original)
            except ValueError: raise JobStopped('format-only equivalence needs review; both responses preserved')
            fields=('issues','reviews','warnings','limitations','retrieval_requests','status')
            if any(before.get(k)!=out.get(k) for k in fields):
                raise JobStopped('repaired scientific fields require equivalence review before page acceptance')
        return out
    job.call=guarded
    with started.open('x',encoding='utf8') as f:json.dump(auth,f)
    try:
        job.reconcile(only_turn=TURN)
    except Exception as exc:
        (archive/'pause.json').write_text(json.dumps({'page':1001,'exception':type(exc).__name__,'reason':str(exc)},indent=2),encoding='utf8')
        raise
    accepted=job._committed(TURN)
    print(json.dumps({'page':1001,'accepted_reviews':len(accepted['reviews']),'issues':len(accepted['issues'])}))
if __name__=='__main__':
    main()
