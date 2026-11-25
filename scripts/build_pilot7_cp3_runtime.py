import sys,json
from pathlib import Path
from build_pilot7_plan_runtime import DEST as OLD
from build_pilot7_cp_syn_runtime import RUN,seal
from build_pilot7_readiness_runtime import REPO,git

DEST=OLD.with_name('execution-20261125-v37-pilot7-a07-cp3-50usd')
PIN='20465a657575f8a4f944f27721f9536c74742932df8ef56b56ce303a2c1940d5'
if __name__=='__main__':
    assert sys.dont_write_bytecode and not git('status','--porcelain').strip() and not DEST.exists()
    sys.path[:0]=[str(REPO/'src'),str(OLD/'vendor')]
    from litreview.runtime_integrity import sha,verify
    m=OLD/'frozen_runtime_manifest.json'
    assert sha(m)==PIN
    manifest=json.loads(m.read_bytes())
    assert verify(OLD,manifest)['telemetry_appends_verified']==22
    run=OLD/'runs'/RUN
    assert json.loads((run/'state.json').read_bytes())['stage']=='synthesize'
    approval=json.loads((run/'checkpoints/CP_SYN_approved.json').read_bytes())
    assert approval['approve_alignment'] and approval['keep_approved_framework']
    assert approval['fingerprint']=='4f5214ad2942f0d8566980846efd884ffa23803388d179899cda47a89db70016'
    assert not (run/'checkpoints/CP3_approved.json').exists()
    policy=manifest['mutable_telemetry']['standard_completions']
    telemetry=OLD/'records/model_record.jsonl'
    policy.update(inherited_bytes=telemetry.stat().st_size,inherited_sha256=sha(telemetry))
    policy['routes']['A07-SYN']['step_pattern']=r'A07-SYN_job30edcaaf8d90ed14_(?:PLAN|FINAL|(?:GROUP_G000[1-9]|RECONCILE_[0-9]{4})_LOOKUP[0-2])'
    assert len(json.loads((run/'reservations.json').read_bytes()))==5
    assert (run/'data/researcher_decisions/T8_closed.json').is_file()
    before={p.relative_to(run).as_posix():sha(p) for p in run.rglob('*') if p.is_file()}
    seal(OLD,DEST,manifest,before,PIN,'v36','v37',Path(__file__),'CP3')
