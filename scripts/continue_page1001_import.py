"""Hash-specific researcher authorization for a single reconciliation import and bounded A07 continuation."""
import json, hashlib, sys, tempfile, shutil
from pathlib import Path
from unittest.mock import patch
import socket
from litreview import orchestrator
from litreview.job_ledger import RunLock
from litreview.runtime_integrity import sha
from litreview.synthesis_registry import fingerprint
from litreview.synthesis_job import JobStopped

RUN='20261123-214928'
TAG='30edcaaf8d90ed14'
TURN='RECONCILE_1102'
HASH='665b268d30c2a02f3584832b09d89b87af7fd88f9fd5578ef9e60806907d7195'
ORIGINAL='8e6dec8625b8d60eceb02217b0c7f29bcfd621c0b9e4fab2cc58faccbdbd294c'
def read(p):return json.loads(p.read_bytes())
def archive(r):return r.dir/'data/recovery/page1001_import_v2'
def evidence(r,j):
    d=archive(r); prefix='A07-SYN_job'+TAG+'_'+TURN+'_LOOKUP0'
    src=r.dir/'outputs'/(prefix+'.json')
    receipt=src.with_suffix('.provider.receipt0.json')
    pause=r.dir/'data/recovery/page1001_preloaded/pause.json'
    assert sha(src)==ORIGINAL and sha(receipt)=='9a45dc6aa753c2ea89f9ac9e8fb5a1cc520321cc66710f84cf6202b53e2277f4'
    assert sha(pause)=='78114971e780975c782209564df80534309a9bb44c885026b18e72dfd80266c4'
    charge=[line for line in (r.dir/'costs.jsonl').read_bytes().splitlines() if json.loads(line)['step']==prefix]
    assert len(charge)==1 and hashlib.sha256(charge[0]).hexdigest()=='919c736f0f883caa40450585e3a88904ec6daf5275d051c335ac8d42d83cd318'
    assert sha(d/'evidence.json')=='c9db5535fcf2e4c24696e0d77d4ee3ea6c8e3138ec1e6bd0c379c16cf7be4464'
    e=read(d/'evidence.json')
    assert j.registry.details(sorted(x['finding_id'] for x in e['detailed_records']['findings']))==e['detailed_records']
    for rid,expected in e['source_passages'].items():
        record=r.load('agent_inputs/A05-KE_'+rid+'.json')['payload']['record']
        assert expected==({k:record['content'][k] for k in expected} if isinstance(expected,dict) else record['abstract'])
    assert j.registry.digest=='4617d5a45df44cfe56d421e766268b6e9ea1bb583b119a3931f9b10f0036e4a7'
    cp=r.dir/'checkpoints/CP_SYN_approved.json'
    assert sha(cp)=='b172d2242036fedea260262b8a270f40a0224ca12214fa175d0ce5d7fb7bc6b8'
    assert read(cp)['fingerprint']==j.identity
    plan=read(r.dir/'data/recovery/page1001_preloaded/plan.json')
    assert fingerprint(plan)=='01620d1bd26a14d1ded04bc3347883452911716b8b2353f7b3459568c6236961'
    page=dict(j.reconciliation_payloads())[TURN]
    assert page==plan['pages'][0]
    proof=dict(candidate_sha256=HASH,original_sha256=ORIGINAL,receipt_sha256=sha(receipt),rejection_sha256=sha(pause),
               charge_entry_sha256=hashlib.sha256(charge[0]).hexdigest(),cp_syn_sha256=sha(cp),plan_sha256=fingerprint(plan),
               evidence_sha256=sha(d/'evidence.json'),details_hash=fingerprint(j.registry.details(page['prefill_finding_ids'])),
               page_hash=fingerprint(page),run_id=RUN,job=j.dir.name,registry=j.registry.digest,fingerprint=j.identity,
               turn=TURN,logical_page=1001,approved_by='researcher: explicit zero-cost exactly-once import')
    return (d/'page1001.recovery-v2.json').read_bytes(),proof

def apply(r,test=False):
    with RunLock(r.dir):
        job,tag=r._synthesis_job()
        assert tag==TAG
        b,proof=evidence(r,job)
        assert hashlib.sha256(b).hexdigest()==HASH
        protected=[r.dir/'costs.jsonl',r.dir/'reservations.json',*job.dir.glob('turns/GROUP_G????.json')]
        assert len(protected)==11
        before=[sha(p) for p in protected]
        if test:
            for name,contents in [(TURN,b+b' '),('RECONCILE_1002',b)]:
                try:job.import_reconciliation(name,contents,proof)
                except JobStopped:pass
                else:raise AssertionError('mismatched import accepted')
        job.import_reconciliation(TURN,b,proof)
        restarted,_=r._synthesis_job()
        restarted.call=lambda *a:(_ for _ in ()).throw(AssertionError('unexpected model call'))
        restarted.import_reconciliation(TURN,b,proof)
        restarted.reconcile(only_turn=TURN)
        events=[x for x in restarted.ledger.events() if x.get('turn')==TURN and x['event'] in ('TURN_ACCEPTED','TURN_IMPORTED_REPAIR')]
        assert len(events)==1 and events[0]['event']=='TURN_IMPORTED_REPAIR' and events[0]['import_record']==proof
        assert len(restarted._committed(TURN)['reviews'])==21 and before==[sha(p) for p in protected]
        if test:
            path=restarted._turn_file(TURN)
            changed=read(path);changed['warnings']=[]
            path.write_text(json.dumps(changed),encoding='utf8')
            try:restarted._committed(TURN)
            except JobStopped:pass
            else:raise AssertionError('changed accepted output reused')
        print(json.dumps({'copy_test':test,'events':len(events),'reviews':21,'cost_usd':0,'candidate':HASH}),flush=True)

def resume(r):
    assert not (r.dir/'checkpoints/CP3_approved.json').exists() and r.state()['stage'] in ('synthesize','cp3')
    with RunLock(r.dir):
        j,tag=r._synthesis_job()
        assert j._marker(TURN)['import_record']['candidate_sha256']==HASH and len(j._committed(TURN)['reviews'])==21
        olddir=r.dir/'data/recovery/page1001_preloaded'
        prior=read(olddir/'v39_reconciliation_repair_plan.json')
        assert fingerprint(prior)=='25fc19775a474a0f91d78067f4b03ddb40ad4976c24b819467cd0e0b22f5e9a6'
        single=read(olddir/'plan.json')
        assert single['pages'][1:]==prior['pages'][1:]
        plan={**prior,'pages':single['pages'],'accepted_recovery':HASH}
        auth={**read(olddir/'v39_reconciliation_repair_approved.json'),'plan_fingerprint':fingerprint(plan),
              'approved_by':'researcher: resume remaining pages and FINAL under existing caps',
              'final_approved_under_stage_cap':True}
        assert auth['baseline_stage_usd']==2.7465485 and auth['max_increment_usd']==7.183020
        for name,value in [('reconciliation_repair_plan.json',plan),('reconciliation_repair_approved.json',auth)]:
            backup=archive(r)/('pre_continuation_'+name)
            if not backup.exists():backup.write_bytes(r.data(name).read_bytes())
            r.save(name,value)
    print(r.run(until='outline'),flush=True)

if __name__=='__main__':
    r=orchestrator.Run(RUN)
    if sys.argv[1]=='test':
        with tempfile.TemporaryDirectory() as t,patch.object(socket.socket,'connect',side_effect=AssertionError('offline')):
            orchestrator.RUNS_DIR=Path(t)/'runs'
            shutil.copytree(r.dir,orchestrator.RUNS_DIR/RUN)
            apply(orchestrator.Run(RUN),True)
    elif sys.argv[1]=='import':apply(r)
    elif sys.argv[1]=='resume':resume(r)
    else:raise ValueError('unknown action')
