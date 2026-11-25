"""Seal the explicitly approved CP1-to-CP2 continuation without paid dispatch."""
from pathlib import Path
import datetime,io,json,shutil,subprocess,sys,tarfile
import build_runtime
REPO=Path(__file__).resolve().parents[1]
OLD=Path(r'C:\Users\maykh\LitReviewStage1\execution-20261124-v30-pilot7-screening-small-cp2-50usd')
DEST=Path(r'C:\Users\maykh\LitReviewStage1\execution-20261124-v31-pilot7-effective-screening-cp2-50usd')
RUN='20261123-214928'
SOURCE_PIN='9a32198936f16bacc66a6e664dd0cd2e427ed77cfd4b92643a040eadeb819fde'
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
    import yaml,copy
    pipeline_path=DEST/'config/pipeline.yaml'
    pipeline=yaml.safe_load(pipeline_path.read_text(encoding='utf-8'))
    agents=copy.deepcopy(pipeline['agents'])
    pipeline['profiles']['pilot7'].setdefault('overrides',{}).setdefault('loops',{})['cq_batch_size']=4
    from litreview.config import _merge
    assert _merge(pipeline,pipeline['profiles']['pilot7']['overrides'])['loops']['cq_batch_size']==4
    assert pipeline['agents']==agents and pipeline['profiles']['pilot7']['spend_cap_usd']==50
    assert pipeline['profiles']['pilot7']['spend_review_points_usd']==[25,48]
    pipeline_path.write_text(yaml.safe_dump(pipeline,sort_keys=False),encoding='utf-8')
    retained=json.loads((OLD/'pilot_retained_hold_authorization.json').read_text())
    for row in [retained,*retained['additional_authorized_holds']]:
        row['continue_without_retry']=['approve-cp1','discover-to-cp2','report-cp2','audit','availability']
        row['user_instruction']='Researcher approves CP1 P1 with scope guide, OPEN_CORPUS discovery/expansion and no seeds. Keep all holds and $50 cap with $25/$48 reviews. Stop at CP2 before corpus freezing or paid extraction.'
    write(DEST/'pilot_retained_hold_authorization.json',retained)
    authorization={'run_id':RUN,'approved_by':'May Khalid: explicit CP1 decision in chat','scope_guide_sha256':sha(DEST/'docs/pilot7/cp1_scope_guide/approved_scope_guide.json'),
                   'stop_at':'CP2','expected_screening_batch_size':4,'max_publications':7,'combined_cap_usd':50,'review_points_usd':[25,48],'CP1_approval_authorized':True,'CP2_approval_authorized':False,'no_seed_papers':True,
                   'baseline_spend_usd':0.8813451,'baseline_held_usd':0.124671,'user_instructions':'Approved P1, eight discovery themes, two eligibility routes, evidence roles, six manuscript subheadings; preserve receipts and all holds. No corpus freeze or paid extraction.'}
    write(DEST/'pilot_discovery_authorization.json',authorization)
    manifest={'runtime_version':'stage1-v31-pilot7-effective-screening-cp2-50usd','git_commit':commit,'runtime_builder_sha256':sha(Path(__file__)),'operational_override':{'cq_batch_size':4,'reason':'Accounted 20-record batch truncated; same model and 16000-token cap'},
              'built_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_runtime':str(OLD),'source_manifest_sha256':SOURCE_PIN,
              'files':{p.relative_to(DEST).as_posix():sha(p) for p in DEST.rglob('*') if p.is_file() and p.relative_to(DEST).as_posix()!='records/model_record.jsonl'},
              'mutable_telemetry':{'baseline':'candidate/model_record_baseline.jsonl'}}
    write(DEST/'frozen_runtime_manifest.json',manifest);pin=sha(DEST/'frozen_runtime_manifest.json');verify(DEST,manifest)
    target=DEST/'runs'/RUN;shutil.copytree(source,target)
    assert all(sha(target/name)==h for name,h in before.items())
    shutil.copy2(target/'input/runtime_pin.json',target/'input/runtime_pin.v30.json')
    write(target/'input/runtime_pin.json',{'run_id':RUN,'runtime':str(DEST),'manifest_sha256':pin,'reviewed_commit':commit})
    write(target/'migration/v31_continuation.json',{'run_id':RUN,'source_runtime':str(OLD),'source_manifest_sha256':SOURCE_PIN,
          'runtime':str(DEST),'manifest_sha256':pin,'commit':commit,'original_run_files_sha256':before,'authorization':authorization,'new_paid_calls_at_migration':0})
    assert all(sha(source/name)==h for name,h in before.items())
    result={'runtime':str(DEST),'commit':commit,'manifest_sha256':pin,'run_id':RUN,**verify(DEST,manifest)}
    write(REPO/'runs/v31_runtime_pin.json',result);print(json.dumps(result,indent=2))
if __name__=='__main__':main()
