"""Migrate sealed v39 and add the hash-bound reviewed plan for the page 1001 retry."""
from pathlib import Path
import json
import shutil
import sys
from build_pilot7_cp_syn_runtime import RUN, seal
from build_pilot7_reconciliation_runtime import DEST as OLD
from build_pilot7_readiness_runtime import REPO, git

DEST = OLD.with_name('execution-20261126-v40-pilot7-page1001-50usd')
SOURCE = 'b321b41ce4f2e677b9441804f0cad24a8ba236bea2797a6b546618a5e810d510'
PLAN = '01620d1bd26a14d1ded04bc3347883452911716b8b2353f7b3459568c6236961'

if __name__ == '__main__':
    assert sys.dont_write_bytecode and not git('status','--porcelain').strip() and not DEST.exists()
    sys.path[:0] = [str(REPO/'src'),str(OLD/'vendor')]
    from litreview.runtime_integrity import sha, verify
    from litreview.synthesis_registry import fingerprint
    m = OLD/'frozen_runtime_manifest.json'
    assert sha(m)==SOURCE
    manifest=json.loads(m.read_bytes())
    verify(OLD,manifest)
    proposal=REPO/'runs/offline_20261123-214928_page1001_preload'
    plan=json.loads((proposal/'plan.json').read_bytes())
    assert fingerprint(plan)==PLAN
    body=proposal/'opening-request.json'
    assert sha(body)==plan['request_hashes'][plan['retry_turn']] and body.stat().st_size==164715
    run=OLD/'runs'/RUN
    before={p.relative_to(run).as_posix():sha(p) for p in run.rglob('*') if p.is_file()}
    seal(OLD,DEST,manifest,before,SOURCE,'v39','v40',Path(__file__),'AFTER_PAGE_1001')
    dest=DEST/'runs'/RUN/'data/recovery/page1001_preloaded'
    dest.mkdir()
    for name in ('plan.json','opening-request.json','rehearsal.json'):
        shutil.copy2(proposal/name,dest/name)
