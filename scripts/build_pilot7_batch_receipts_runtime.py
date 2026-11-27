"""Seal the completed batch receipts alongside the interactive STANDARD-run evidence."""
import json
import sys
from pathlib import Path

from build_pilot7_cp_syn_runtime import DEST as OLD, RUN, seal
from build_pilot7_readiness_runtime import REPO, git

DEST = OLD.with_name('execution-20261125-v35-pilot7-batch-receipts-cp-syn-50usd')
SOURCE_PIN = '6e40491fd1fb26ab9494e3e65f323f26840167f880e35a9e0ebab3d1cbe9353f'
BATCH_ID = 'batch_6b072c691fc08190b24c8d5b8da213c8'
SUBMITTED = '2d3cfcaeae27c6dd2d4c91b81b9ed3370dec1037c74be41e8e6d5a8fe3dfbeb2'


def main():
    assert sys.dont_write_bytecode and not git('status', '--porcelain').strip() and not DEST.exists()
    sys.path[:0] = [str(REPO/'src'), str(OLD/'vendor')]
    from litreview.runtime_integrity import sha, verify
    manifest_file = OLD/'frozen_runtime_manifest.json'
    assert sha(manifest_file) == SOURCE_PIN
    manifest = json.loads(manifest_file.read_bytes())
    run = OLD/'runs'/RUN
    approval = json.loads((run/'checkpoints/CP_EARLY_approved.json').read_bytes())
    assert approval['approve_continue'] and approval['fingerprint'] == 'ccea7ad52f9374f6d0e88cd02711066c05aa8890c7fbe7bb2161404822db9e63'
    assert not (run/'checkpoints/CP_SYN_approved.json').exists()
    holds = json.loads((run/'reservations.json').read_bytes())
    assert len(holds) == 5 and all(k.startswith('smoke') for k in holds)
    receipts = run/'data/batches/provider_evidence'/BATCH_ID
    proof = {name:sha(receipts/name) for name in ('job.json','submitted.jsonl','responses.jsonl')}
    assert proof['submitted.jsonl'] == SUBMITTED
    policy = manifest['mutable_telemetry']['standard_completions']
    policy['batch_receipts'] = {BATCH_ID:proof}
    verify(OLD, manifest)
    telemetry = OLD/'records/model_record.jsonl'
    policy.update(inherited_bytes=telemetry.stat().st_size, inherited_sha256=sha(telemetry))
    before = {p.relative_to(run).as_posix():sha(p) for p in run.rglob('*') if p.is_file()}
    seal(OLD, DEST, manifest, before, SOURCE_PIN, 'v34', 'v35', Path(__file__))


if __name__ == '__main__':
    main()
