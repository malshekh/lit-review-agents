"""Seal the CP_EARLY to CP_SYN continuation, preserving the complete v33 evidence chain."""
import datetime
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile
RUN = '20261123-214928'

OLD = Path(r'C:/Users/maykh/LitReviewStage1/execution-20261125-v33-pilot7-five-paper-cp2-50usd')
DEST = Path(r'C:/Users/maykh/LitReviewStage1/execution-20261125-v34-pilot7-standard-cp-syn-50usd')
SOURCE_PIN = 'fd05a0ff494f82b47cf9c51be2a46d4c6b09fa167de8a009215cadf06ae907b1'
POLICY = {
    'run_id': RUN, 'family': 'ai-enabled-nanobiosensing-cancer-therapy',
    'inherited_bytes': 12766, 'inherited_sha256': 'c36bfe6c5292824823b65ff1a6f18d91b8e3a6ded708f59344522a352d5cb18e',
    'routes': {
        'A05-KE': {'provider': 'anthropic', 'model': 'claude-sonnet-5-5', 'step_pattern': r'A05-KE_R00(?:58|39)'},
        'A06-SV': {'provider': 'openai', 'model': 'gpt-6.1-sol', 'step_pattern':
            r'A06-SV_(?:R(?:0078|0115|0090|0058|0039)_(?:v1|repeat)(?:_B[0-9]{3}_[0-9a-f]{10}_try[12])?|theme_T[1-8](?:_(?:P[0-9]{3}of[0-9]{3}|reconcile(?:_r[0-9]+)?))?)'},
        'A07-SYN': {'provider': 'anthropic', 'model': 'claude-opus-5', 'step_pattern': r'A07-SYN_job[0-9a-f]{16}_PLAN'}
    }
}


def main():
    from build_pilot7_readiness_runtime import REPO, git, write
    from build_runtime import FROM_GIT, FROM_RUNTIME
    assert sys.dont_write_bytecode and not git('status','--porcelain').strip() and not DEST.exists()
    sys.path[:0] = [str(REPO/'src'),str(OLD/'vendor')]
    from litreview.runtime_integrity import sha, verify
    assert sha(OLD/'frozen_runtime_manifest.json') == SOURCE_PIN
    assert sha(OLD/'records/model_record.jsonl') == POLICY['inherited_sha256']
    manifest = json.loads((OLD/'frozen_runtime_manifest.json').read_bytes())
    # Only the reviewed telemetry rule changes during migration preflight. All old immutable hashes still apply.
    manifest['mutable_telemetry']['standard_completions'] = POLICY
    assert verify(OLD,manifest)['telemetry_appends_verified'] == 4
    src = OLD/'runs'/RUN
    before = {p.relative_to(src).as_posix():sha(p) for p in src.rglob('*') if p.is_file()}
    evidence=json.loads((src/'checkpoints/CP_EARLY_continuation_integrity_stop.json').read_bytes())
    assert evidence['ledger_sha256']==before['costs.jsonl'] and evidence['holds_sha256']==before['reservations.json']
    assert before.get('checkpoints/CP2_approved.json') and not before.get('checkpoints/CP_SYN_approved.json')
    seal(OLD, DEST, manifest, before, SOURCE_PIN, 'v33', 'v34', Path(__file__))


def seal(OLD, DEST, manifest, before, SOURCE_PIN, previous_version, version, builder, stop_at="CP_SYN"):
    from build_pilot7_readiness_runtime import REPO, git, write
    from build_runtime import FROM_GIT, FROM_RUNTIME
    from litreview.runtime_integrity import sha, verify
    src = OLD/'runs'/RUN
    commit = git('rev-parse','HEAD').decode().strip()
    DEST.mkdir()
    with tarfile.open(fileobj=io.BytesIO(git('archive','--format=tar',commit,*FROM_GIT))) as archive:
        archive.extractall(DEST,filter='data')
    for rel in [*FROM_RUNTIME,'config/pipeline.yaml','config/prices.yaml','pilot_authorization.json',
                'pilot_outline_source.txt','pilot_discovery_authorization.json','pilot_retained_hold_authorization.json']:
        a,b=OLD/rel,DEST/rel
        b.parent.mkdir(parents=True,exist_ok=True)
        if a.is_dir():shutil.copytree(a,b)
        else:shutil.copy2(a,b)
    shutil.copy2(DEST/'scripts/runtime_bootstrap.py',DEST/'bootstrap.py')
    new={'runtime_version':DEST.name,'git_commit':commit,'runtime_builder_sha256':sha(builder),
         'source_runtime':str(OLD),'source_manifest_sha256':SOURCE_PIN,'stop_at':stop_at,
         'built_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
         'mutable_telemetry':manifest['mutable_telemetry'],
         'files':{p.relative_to(DEST).as_posix():sha(p) for p in DEST.rglob('*') if p.is_file()
                  and p.relative_to(DEST).as_posix()!='records/model_record.jsonl'}}
    write(DEST/'frozen_runtime_manifest.json',new)
    pin=sha(DEST/'frozen_runtime_manifest.json')
    target=DEST/'runs'/RUN
    shutil.copytree(src,target)
    assert all(sha(target/k)==h and sha(src/k)==h for k,h in before.items())
    shutil.copy2(target/'input/runtime_pin.json',target/f'input/runtime_pin.{previous_version}.json')
    write(target/'input/runtime_pin.json',{'reviewed_commit':commit,'run_id':RUN,'runtime':str(DEST),'manifest_sha256':pin})
    write(target/f'migration/{version}_continuation.json',{'source_manifest_sha256':SOURCE_PIN,'manifest_sha256':pin,
          'original_run_files_sha256':before,'new_paid_calls_at_migration':0,'original_telemetry_sha256':sha(OLD/'records/model_record.jsonl')})
    result={'commit':commit,'runtime':str(DEST),'manifest_sha256':pin,'run_id':RUN,**verify(DEST,new)}
    write(REPO/f'runs/{version}_runtime_pin.json',result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()

