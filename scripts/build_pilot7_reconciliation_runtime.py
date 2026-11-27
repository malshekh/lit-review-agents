"""Seal the approved evidence-first reconciliation continuation without provider access."""
import json
import sys
from pathlib import Path

from build_pilot7_cp_syn_runtime import RUN, seal
from build_pilot7_group_runtime import DEST as OLD
from build_pilot7_readiness_runtime import REPO, git

PIN = '18c3fda86f9a58affebc26a9013219be9447b65c3eb341c3c2c1e1ae72927e5a'
DEST = OLD.with_name('execution-20261126-v39-pilot7-reconciliation-50usd')

if __name__ == '__main__':
    assert sys.dont_write_bytecode and not git('status', '--porcelain').strip() and not DEST.exists()
    sys.path[:0] = [str(REPO/'src'), str(OLD/'vendor')]
    from litreview.runtime_integrity import sha, verify
    from litreview.synthesis_registry import fingerprint
    manifest_path = OLD/'frozen_runtime_manifest.json'
    assert sha(manifest_path) == PIN
    manifest = json.loads(manifest_path.read_bytes())
    verify(OLD, manifest)
    source = OLD/'runs'/RUN
    plan = json.loads((source/'data/recovery/reconciliation_evidence_review/plan.json').read_bytes())
    assert fingerprint(plan) == '25fc19775a474a0f91d78067f4b03ddb40ad4976c24b819467cd0e0b22f5e9a6'
    before = {p.relative_to(source).as_posix(): sha(p) for p in source.rglob('*') if p.is_file()}
    seal(OLD, DEST, manifest, before, PIN, 'v38b', 'v39', Path(__file__), 'BEFORE_FINAL')

