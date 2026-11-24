"""Build the explicitly authorized v24 continuation; no network or paid calls."""
from pathlib import Path
import datetime, hashlib, io, json, shutil, subprocess, sys, tarfile
import build_runtime
REPO=Path(__file__).resolve().parents[1]
OLD=Path(r"C:\Users\maykh\LitReviewStage1\execution-20261124-v23-pilot7-ordinary-a05-50usd")
DEST=Path(r"C:\Users\maykh\LitReviewStage1\execution-20261124-v24-pilot7-functional-only-50usd")
SOURCE_PIN="f25ca4b7e9de4e31139de3e82c2640550e77045f42fee2d89b6790e58e78f84c"
RUN="20261123-214928"
def git(*args):return subprocess.check_output(["git",*args],cwd=REPO)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def inventory(p):return {x.relative_to(p).as_posix():sha(x) for x in sorted(p.rglob("*")) if x.is_file()}
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+"\n",encoding="utf-8")
def main():
    assert not git("status","--porcelain").strip()
    assert not DEST.exists(),"Never modify a sealed runtime in place"
    commit=git("rev-parse","HEAD").decode().strip()
    assert sha(OLD/"frozen_runtime_manifest.json")==SOURCE_PIN
    sys.path[:0]=[str(REPO/"src"),str(OLD/"vendor")]
    from litreview.runtime_integrity import verify
    verify(OLD,json.loads((OLD/"frozen_runtime_manifest.json").read_text()))
    source=OLD/"runs"/RUN;before=inventory(source)
    DEST.mkdir()
    with tarfile.open(fileobj=io.BytesIO(git("archive","--format=tar",commit,*build_runtime.FROM_GIT))) as archive:
        archive.extractall(DEST,filter="data")
    for relative in build_runtime.FROM_RUNTIME:
        src,dst=OLD/relative,DEST/relative;dst.parent.mkdir(parents=True,exist_ok=True)
        if src.is_dir():shutil.copytree(src,dst)
        else:shutil.copy2(src,dst)
    shutil.copy2(DEST/"scripts/runtime_bootstrap.py",DEST/"bootstrap.py")
    for relative in ["config/pipeline.yaml","config/prices.yaml","pilot_authorization.json","pilot_outline_source.txt"]:
        shutil.copy2(OLD/relative,DEST/relative)
    import yaml
    pipeline_path=DEST/"config/pipeline.yaml"
    pipeline=yaml.safe_load(pipeline_path.read_text(encoding="utf-8"))
    pipeline["notify"]["on"]=[]  # No external messages were authorized.
    pipeline["extraction"]["generation_mode"]="ordinary_json_local_v1"  # Explicit researcher-approved A05 mode; scientific checkpoint decisions remain pending.
    pipeline["loops"]["max_truncation_retries"]=0  # User prohibits automatic token-limit increases after failure.
    pipeline_path.write_text(yaml.safe_dump(pipeline,sort_keys=False),encoding="utf-8")
    assert pipeline["profiles"]["pilot7"]["spend_cap_usd"]==50
    assert pipeline["profiles"]["pilot7"]["smoke_test_allowance_usd"]==1
    assert pipeline["profiles"]["pilot7"]["spend_review_points_usd"]==[25,48]
    assert not pipeline["routing"]["alternates"]
    key="smoke-a7002e97d157452281d47d14d836bc48"
    auth={"run_id":RUN,"authorized_by":"May Khalid: explicit chat authorization, 2026-11-24",
          "decision":"CONTINUE_WITH_UNRESOLVED_HOLD","release_hold":False,"reservation":key,
          "receipt_sha256":sha(source/"smoke_receipts"/(key+".json")),"held_usd":0.019586,
          "provider":"anthropic","model":"claude-sonnet-5-5","provider_request_id":"req_011ChM1MMKaDrZauPitV2pKC",
          "rejected_schema_sha256":"fc69280e517b5cc45206c275764728433d27cd3bf7e6e5f219f89ade5ec7c93c",
          "approved_checks":9,"estimated_retest_usd":0.21,"total_cap_usd":50,"smoke_allowance_usd":1,
          "review_points_usd":[25,48],"checkpoint_limit":"CP1; no scientific approval",
          "user_instruction":"Keep the $0.019586 hold unresolved rather than infer a zero charge. Commit all changes, seal a fresh runtime, and perform the nine approved smoke retests.",
          "billing_evidence":"User reports no request-level export is available. Rounded daily Sonnet total $0.0049 is not attributed to this request; unknown hold remains."}
    new_key="smoke-40b97da422624626bfe52134a40465e8"
    auth["additional_authorized_holds"]=[{**auth,"reservation":new_key,
        "receipt_sha256":sha(source/"smoke_receipts"/(new_key+".json")),"held_usd":0.001107,
        "model":"claude-haiku-5-5","provider_request_id":"req_011ChMwemm1jBP7wi9kaej8c",
        "rejected_schema_sha256":"c50908fb9e5bfa4dc2b2fa8bf7695babf07455b8e02b6b78cc6018972fc7d9bc",
        "user_instruction":"Retain both holds and continue corrected checks (explicit researcher reply, 2026-11-24)."}]
    third_key="smoke-cf915e7cd207476399c034b44c539d2a"
    auth["additional_authorized_holds"].append({**{k:v for k,v in auth.items() if k!="additional_authorized_holds"},
        "reservation":third_key,"receipt_sha256":sha(source/"smoke_receipts"/(third_key+".json")),"held_usd":0.037048,
        "provider_request_id":"req_011ChMxNR9guXmuWRanNjcoB",
        "rejected_schema_sha256":"53e8885ee7020e64719fa73bea380d560d4a0fa562cf40cf86add2ff88419e56",
        "user_instruction":"Retain all three holds and continue corrected checks after offline repair; explicit researcher reply 2026-11-24."})
    fourth_key="smoke-06b75cd9b38647d29a3e16fc3e902aa7"
    auth["additional_authorized_holds"].append({**{k:v for k,v in auth.items() if k!="additional_authorized_holds"},
        "reservation":fourth_key,"receipt_sha256":sha(source/"smoke_receipts"/(fourth_key+".json")),"held_usd":0.041668,
        "provider_request_id":"req_011ChNMGzga3FkrjawEPcPZA",
        "rejected_schema_sha256":"cb602653047b74fd9865a64e630c214c4c3931b1df2949acc037cee6dd98f9dc",
        "user_instruction":"Researcher explicitly authorizes all four existing holds retained; no settlement or release; 2026-11-24."})
    fifth_key="smoke-c9789daf1c7c452d8b52fdeefef0f939"
    auth["additional_authorized_holds"].append({**{k:v for k,v in auth.items() if k!="additional_authorized_holds"},
        "reservation":fifth_key,"receipt_sha256":sha(source/"smoke_receipts"/(fifth_key+".json")),"held_usd":0.025262,
        "provider":"openai","model":"gpt-6.1-sol","provider_request_id":"req_5377fd18723845e4b008236100ef5184",
        "rejected_schema_sha256":"6cf8656f20883e59a2f50fedf8410e90fac117d934728039c783c511a34c39c4",
        "continue_without_retry":["audit","availability","functional"],
        "user_instruction":"Retain the fifth unresolved hold; authorize A05-A06 functional check only, no further strict checks or scope."})
    prepared=json.loads((DEST/"docs/pilot7/a05_functional/prepared_plan.json").read_text(encoding="utf-8"))
    assert prepared["combined_remaining_worst_case_usd"]==0.712374
    assert prepared["functional_worst_case_usd"]==0.594 and prepared["prior_success_count"]==9
    check_auth={"run_id":RUN,"approved_by":"May Khalid: explicit chat authorization, 2026-11-24",
        "implementation_commit":"7d98042f2356b5e022ac5de56c6dc8ce46c23b12",
        "fingerprint":prepared["fingerprint"],"additional_cap_usd":0.594,"functional_cap_usd":0.594,
        "strict_cap_usd":0,"baseline_spend_usd":0.0707391,"baseline_hold_usd":0.124671,
        "smoke_cap_usd":1,"pilot_cap_usd":50,"review_points_usd":[25,48],
        "scope_limit":"PAUSED; no scope or scientific approval","strict_first":"A06-SV.schema.json",
        "allowed_actions":["functional"],"functional_only":True,
        "a06_receipt_identity":{"provider":"openai","model":"gpt-6.1-sol","schema_sha256":"157cbeb66719080072638fdd497a2d4f42ee6c1897a1f10c00271e84ca1389b6"},
        "stop_on":["new unresolved hold","required check fails after permitted repair","reviewed cost bound changes"],
        "user_instruction":"Authorize only the already prepared A05-A06 functional check up to $0.594 including bounded repairs; retain all five unresolved holds and receipts. Further strict checks and scope are paused."}
    write(DEST/"pilot_check_authorization.json",check_auth)
    write(DEST/"pilot_retained_hold_authorization.json",auth)
    manifest={"runtime_version":"stage1-v24-pilot7-retained-hold-50usd","git_commit":commit,
              "built_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "source_runtime":str(OLD),"source_manifest_sha256":SOURCE_PIN,
              "operational_overrides":"v16 financial limits retained; automatic truncation retries disabled per user instruction; all five holds preserved; functional check only up to $0.594 additional; strict checks and scope paused",
              "files":{p.relative_to(DEST).as_posix():sha(p) for p in sorted(DEST.rglob("*")) if p.is_file() and p.relative_to(DEST).as_posix()!="records/model_record.jsonl"},
              "mutable_telemetry":{"baseline":"candidate/model_record_baseline.jsonl"}}
    write(DEST/"frozen_runtime_manifest.json",manifest);pin=sha(DEST/"frozen_runtime_manifest.json")
    verify(DEST,manifest)
    target=DEST/"runs"/RUN;shutil.copytree(source,target)
    assert inventory(target)==before
    for name in ["structured_output.json","input/runtime_pin.json","LIVE_LAUNCH_STATUS.json","LIVE_LAUNCH_STATUS.md","smoke_result.json"]:
        src=target/name
        if src.exists():
            dst=target/"migration/v24_previous"/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    # Resume with the verified, hash-bound receipt enrichment already produced by v16.
    write(target/"structured_output.json",{})
    report={"run_id":RUN,"source_runtime":str(OLD),"source_manifest_sha256":SOURCE_PIN,"destination_runtime":str(DEST),
            "manifest_sha256":pin,"commit":commit,"original_run_files_sha256":before,"new_paid_calls":0,
            "authorization":auth,"billing_status":"UNRESOLVED_HOLD_RETAINED","scientific_approvals_added":0}
    write(target/"migration/v24_continuation.json",report)
    write(target/"input/runtime_pin.json",{"run_id":RUN,"runtime":str(DEST),"manifest_sha256":pin,"reviewed_commit":commit})
    assert inventory(source)==before
    for name,digest in before.items():
        if name not in ("structured_output.json","input/runtime_pin.json"):assert sha(target/name)==digest,name
    result={"runtime":str(DEST),"commit":commit,"manifest_sha256":pin,"run_id":RUN,**verify(DEST,manifest)}
    write(REPO/"runs/v24_runtime_pin.json",result)
    print(json.dumps(result,indent=2))
if __name__=="__main__":main()
