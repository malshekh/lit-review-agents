import sys,json
from pathlib import Path
from build_pilot7_batch_receipts_runtime import DEST as OLD
from build_pilot7_cp_syn_runtime import RUN,seal
from build_pilot7_readiness_runtime import REPO,git

DEST=OLD.with_name('execution-20261125-v36-pilot7-a07-plan-50usd')
PIN='a1c66be51fd265e27595bf2e2ce1f6d42823ca43dcfb03fe8491c0208aaccbfe'
if __name__=='__main__':
    assert sys.dont_write_bytecode and not git('status','--porcelain').strip() and not DEST.exists()
    sys.path[:0]=[str(REPO/'src'),str(OLD/'vendor')]
    from litreview.runtime_integrity import sha,verify
    m=OLD/'frozen_runtime_manifest.json'
    assert sha(m)==PIN
    manifest=json.loads(m.read_bytes())
    assert verify(OLD,manifest)['telemetry_appends_verified']==21
    run=OLD/'runs'/RUN
    assert json.loads((run/'state.json').read_bytes())['stage']=='synthesize'
    assert not (run/'checkpoints/CP_SYN_approved.json').exists()
    assert len(json.loads((run/'reservations.json').read_bytes()))==5
    assert (run/'data/researcher_decisions/T8_closed.json').is_file()
    before={p.relative_to(run).as_posix():sha(p) for p in run.rglob('*') if p.is_file()}
    seal(OLD,DEST,manifest,before,PIN,'v35','v36',Path(__file__))
