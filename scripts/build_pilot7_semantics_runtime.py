"""Seal the authorized source-semantics continuation; no provider dispatch."""
from pathlib import Path
import datetime,io,json,shutil,subprocess,sys,tarfile
import build_runtime
REPO=Path(__file__).resolve().parents[1]
OLD=Path(r'C:\Users\maykh\LitReviewStage1\execution-20261124-v26-pilot7-functional-only-50usd')
DEST=Path(r'C:\Users\maykh\LitReviewStage1\execution-20261124-v27-pilot7-a06-only-50usd')
RUN='20261123-214928'
SOURCE_PIN='3315560c9d4977ce631a65db59f049d53e6f69b49530c6455151d0cefaeeca09'

def git(*args):return subprocess.check_output(['git',*args],cwd=REPO)
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8')
def main():
    assert sys.dont_write_bytecode,'Run the builder with python -B; sealed vendor files must stay untouched'
    assert not git('status','--porcelain').strip(),'Commit all source first'
    subprocess.run(['git','merge-base','--is-ancestor','1048330','HEAD'],cwd=REPO,check=True)
    assert not DEST.exists(),'Never modify an existing sealed runtime'
    sys.path[:0]=[str(REPO/'src'),str(OLD/'vendor')]
    from litreview.runtime_integrity import sha,verify
    assert sha(OLD/'frozen_runtime_manifest.json')==SOURCE_PIN
    verify(OLD,json.loads((OLD/'frozen_runtime_manifest.json').read_text()))
    source=OLD/'runs'/RUN
    before={p.relative_to(source).as_posix():sha(p) for p in source.rglob('*') if p.is_file()}
    reviewed=json.loads((REPO/'docs/pilot7/source_semantics_v2/raw_validated/original_artifact_hashes.json').read_text())
    assert all(before.get(name)==digest for name,digest in reviewed.items()),'Reviewed archived evidence changed'
    commit=git('rev-parse','HEAD').decode().strip();DEST.mkdir()
    with tarfile.open(fileobj=io.BytesIO(git('archive','--format=tar',commit,*build_runtime.FROM_GIT))) as tar:tar.extractall(DEST,filter='data')
    for relative in build_runtime.FROM_RUNTIME:
        src,dst=OLD/relative,DEST/relative;dst.parent.mkdir(parents=True,exist_ok=True)
        if src.is_dir():shutil.copytree(src,dst)
        else:shutil.copy2(src,dst)
    shutil.copy2(DEST/'scripts/runtime_bootstrap.py',DEST/'bootstrap.py')
    for relative in ['config/pipeline.yaml','config/prices.yaml','pilot_authorization.json','pilot_outline_source.txt']:
        shutil.copy2(OLD/relative,DEST/relative)
    retained=json.loads((OLD/'pilot_retained_hold_authorization.json').read_text())
    for row in [retained,*retained['additional_authorized_holds']]:
        row['continue_without_retry']=['audit','availability','a06-strict','a06-only','remaining-strict','scope']
        row['user_instruction']='Explicit researcher authorization 2026-11-24: retain all five existing holds; seven strict checks plus corrected-record A06 only up to $0.550645 additional; then scope to CP1 without approval.'
    write(DEST/'pilot_retained_hold_authorization.json',retained)
    costs=[json.loads(x) for x in (source/'costs.jsonl').read_text().splitlines() if x.strip()]
    from litreview import structured
    targets=[{k:t[k] for k in ('schema_file','provider','model','schema_sha256')} for t in structured.targets() if t['schema_file'] in ['A02-SP.schema.json','A03-LM.schema.json','A06-SV.schema.json','A08-OL.schema.json','A10-RV.bounded.schema.json','A12-EDI.schema.json','A12-EDI.unit.schema.json']]
    assert len(targets)==7
    auth={'run_id':RUN,'approved_by':'May Khalid: explicit chat authorization 2026-11-24','required_commit':'1048330','implementation_commit':commit,
          'additional_cap_usd':0.550645,'strict_cap_usd':0.180645,'a06_cap_usd':0.37,'baseline_spend_usd':0.1762446,'baseline_hold_usd':0.124671,
          'baseline_entry_count':len(costs),'smoke_cap_usd':1,'pilot_cap_usd':50,'review_points_usd':[25,48],
          'strict_targets':targets,'execution_order':['a06-strict','a06-only','remaining-strict','scope'],
          'source_payload_sha256':'1cb1af9df9d9767aec4b22fc23fb3b97c64d509f12ca78a08efcb8e220259056',
          'stop_on':['new unresolved hold','scientific assessment failure','reviewed bound exceeded'],
          'scientific_checkpoint_approvals':False,'scope_stop':'CP1','test_excerpt_in_discovery_corpus':False}
    write(DEST/'pilot_semantics_authorization.json',auth)
    manifest={'runtime_version':'stage1-v27-pilot7-a06-only-50usd','git_commit':commit,'required_ancestor':'1048330','runtime_builder_sha256':sha(Path(__file__)),
              'built_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_runtime':str(OLD),'source_manifest_sha256':SOURCE_PIN,
              'files':{p.relative_to(DEST).as_posix():sha(p) for p in DEST.rglob('*') if p.is_file() and p.relative_to(DEST).as_posix()!='records/model_record.jsonl'},
              'mutable_telemetry':{'baseline':'candidate/model_record_baseline.jsonl'}}
    write(DEST/'frozen_runtime_manifest.json',manifest);pin=sha(DEST/'frozen_runtime_manifest.json');verify(DEST,manifest)
    target=DEST/'runs'/RUN;shutil.copytree(source,target)
    assert all(sha(target/name)==digest for name,digest in before.items())
    shutil.copy2(target/'input/runtime_pin.json',target/'input/runtime_pin.v26.json')
    write(target/'input/runtime_pin.json',{'run_id':RUN,'runtime':str(DEST),'manifest_sha256':pin,'reviewed_commit':commit})
    write(target/'migration/v27_continuation.json',{'run_id':RUN,'source_runtime':str(OLD),'source_manifest_sha256':SOURCE_PIN,
          'runtime':str(DEST),'manifest_sha256':pin,'commit':commit,'original_run_files_sha256':before,'authorization':auth,
          'original_failed_verdict_preserved':True,'new_paid_calls_at_migration':0,'scientific_approvals_added':0})
    assert all(sha(source/name)==digest for name,digest in before.items())
    result={'runtime':str(DEST),'commit':commit,'manifest_sha256':pin,'run_id':RUN,**verify(DEST,manifest)}
    write(REPO/'runs/v27_runtime_pin.json',result);print(json.dumps(result,indent=2))
if __name__=='__main__':main()
