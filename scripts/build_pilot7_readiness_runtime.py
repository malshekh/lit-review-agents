"""Seal the pending five-paper CP2 readiness revision without paid dispatch."""
from pathlib import Path
import datetime,io,json,shutil,subprocess,sys,tarfile
import build_runtime
REPO=Path(__file__).resolve().parents[1]
OLD=Path(r'C:\Users\maykh\LitReviewStage1\execution-20261124-v32-pilot7-single-screening-cp2-50usd')
DEST=Path(r'C:\Users\maykh\LitReviewStage1\execution-20261125-v33-pilot7-five-paper-cp2-50usd')
RUN='20261123-214928'
SOURCE_PIN='93559fee89b744e1b5137612d17ed61796be3fe7bc8900103ca2f47e20d5787c'
def git(*a):return subprocess.check_output(['git',*a],cwd=REPO)
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8')
def main():
    assert sys.dont_write_bytecode and not git('status','--porcelain').strip()
    assert not DEST.exists()
    sys.path[:0]=[str(REPO/'src'),str(OLD/'vendor')]
    from litreview.runtime_integrity import sha,verify
    assert sha(OLD/'frozen_runtime_manifest.json')==SOURCE_PIN
    verify(OLD,json.loads((OLD/'frozen_runtime_manifest.json').read_text()))
    source=OLD/'runs'/RUN
    before={p.relative_to(source).as_posix():sha(p) for p in source.rglob('*') if p.is_file()}
    assert (source/'checkpoints/CP1_approved.json').exists()
    commit=git('rev-parse','HEAD').decode().strip();DEST.mkdir()
    with tarfile.open(fileobj=io.BytesIO(git('archive','--format=tar',commit,*build_runtime.FROM_GIT))) as tar:tar.extractall(DEST,filter='data')
    for relative in build_runtime.FROM_RUNTIME:
        a,b=OLD/relative,DEST/relative;b.parent.mkdir(parents=True,exist_ok=True)
        if a.is_dir():shutil.copytree(a,b)
        else:shutil.copy2(a,b)
    shutil.copy2(DEST/'scripts/runtime_bootstrap.py',DEST/'bootstrap.py')
    for relative in ['config/pipeline.yaml','config/prices.yaml','pilot_authorization.json','pilot_outline_source.txt']:
        shutil.copy2(OLD/relative,DEST/relative)
    for relative in ('pilot_discovery_authorization.json','pilot_retained_hold_authorization.json'):
        shutil.copy2(OLD/relative, DEST/relative)
    authorization = {'purpose':'Five-paper CP2 readiness only','paid_dispatch':False,'CP2_approved':False}
    assert not (source/'checkpoints/CP2_approved.json').exists()
    manifest={'runtime_version':'stage1-v33-pilot7-five-paper-cp2-50usd','git_commit':commit,
              'runtime_builder_sha256':sha(Path(__file__)), 'purpose':authorization,
              'built_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_runtime':str(OLD),'source_manifest_sha256':SOURCE_PIN,
              'files':{p.relative_to(DEST).as_posix():sha(p) for p in DEST.rglob('*') if p.is_file() and p.relative_to(DEST).as_posix()!='records/model_record.jsonl'},
              'mutable_telemetry':{'baseline':'candidate/model_record_baseline.jsonl'}}
    write(DEST/'frozen_runtime_manifest.json',manifest);pin=sha(DEST/'frozen_runtime_manifest.json');verify(DEST,manifest)
    target=DEST/'runs'/RUN;shutil.copytree(source,target)
    assert all(sha(target/name)==h for name,h in before.items())
    shutil.copy2(target/'input/runtime_pin.json',target/'input/runtime_pin.v32.json')
    write(target/'input/runtime_pin.json',{'run_id':RUN,'runtime':str(DEST),'manifest_sha256':pin,'reviewed_commit':commit})
    write(target/'migration/v33_continuation.json',{'run_id':RUN,'source_runtime':str(OLD),'source_manifest_sha256':SOURCE_PIN,
          'runtime':str(DEST),'manifest_sha256':pin,'commit':commit,'original_run_files_sha256':before,'authorization':authorization,'new_paid_calls_at_migration':0})
    assert all(sha(source/name)==h for name,h in before.items())
    result={'runtime':str(DEST),'commit':commit,'manifest_sha256':pin,'run_id':RUN,**verify(DEST,manifest)}
    write(REPO/'runs/v33_runtime_pin.json',result);print(json.dumps(result,indent=2))
if __name__=='__main__':main()
