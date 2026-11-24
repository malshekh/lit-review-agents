"""Audited offline continuation of smoke receipts; never modifies the source run or releases unknown holds."""
from __future__ import annotations
import hashlib,json,runpy,shutil
from pathlib import Path
import yaml
from . import structured,smoke_validation
from .budget import BudgetTracker
from .runtime_integrity import verify,sha

def inventory(folder):
    folder=Path(folder).resolve()
    files=[p for p in sorted(folder.rglob('*')) if p.is_file()]
    if any(p.is_symlink() or not p.resolve().is_relative_to(folder) for p in files):raise ValueError('run inventory path escapes source')
    return {p.relative_to(folder).as_posix():sha(p) for p in files}

def migrate(source: Path, destination: Path, run_id: str, source_pin: str, destination_pin: str) -> dict:
    source,destination=Path(source).resolve(),Path(destination).resolve()
    if source==destination:raise ValueError('sealed runtime cannot be migrated in place')
    if sha(source/'frozen_runtime_manifest.json')!=source_pin or sha(destination/'frozen_runtime_manifest.json')!=destination_pin:
        raise ValueError('pinned manifest hash mismatch')
    old=json.loads((source/'frozen_runtime_manifest.json').read_text(encoding='utf-8'))
    new=json.loads((destination/'frozen_runtime_manifest.json').read_text(encoding='utf-8'))
    verify(source,old);verify(destination,new)
    origin=source/'runs'/run_id;target=destination/'runs'/run_id
    if not origin.resolve().is_relative_to(source/'runs'):raise ValueError('unsafe continuation target')
    if target.exists():
        completed=target/'migration/continuation.json'
        if completed.exists():
            report=json.loads(completed.read_text(encoding='utf-8'))
            if report['source_manifest_sha256']==source_pin and report['destination_manifest_sha256']==destination_pin:
                return report  # no copy, no budget reset, no request repeated
        raise ValueError('partial or incompatible continuation exists; preserve it and reconcile before retrying')
    before=inventory(origin)
    state=json.loads((origin/'state.json').read_text(encoding='utf-8'))
    assert state['profile']=='pilot7'
    old_cfg=yaml.safe_load((source/'config/pipeline.yaml').read_text(encoding='utf-8'))
    new_cfg=yaml.safe_load((destination/'config/pipeline.yaml').read_text(encoding='utf-8'))
    for cfg in (old_cfg,new_cfg):
        assert cfg['profiles']['pilot7']['spend_cap_usd']==50
        assert cfg['profiles']['pilot7']['spend_review_points_usd']==[25,48]
        assert cfg['profiles']['pilot7']['smoke_test_allowance_usd']==1
        assert not cfg['routing']['alternates']
    assert old_cfg['agents']==new_cfg['agents'] and old_cfg['models']==new_cfg['models']
    assert old_cfg['providers']==new_cfg['providers']
    # Validate old code against its sealed inventory before deterministic reconstruction.
    legacy=runpy.run_path(str(source/'src/litreview/tools/contract.py'))
    logs=[json.loads(x) for x in (origin/'smoke_tests.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
    evidence={};rows=[]
    current={(r['provider'],r['model'],r['schema_file']):r for r in structured.schema_inventory()}
    for path in sorted((origin/'smoke_receipts').glob('*.json')):
        raw=path.read_bytes();receipt=json.loads(raw)
        if receipt['state']!='RECEIVED':
            rows.append({'receipt':path.name,'status':'UNRECONCILED_HOLD_PRESERVED'});continue
        matches=[r for r in logs if all(r.get(k)==receipt.get(k) for k in ('provider','model','schema_sha256'))]
        if len(matches)!=1:raise ValueError('ambiguous historical smoke receipt')
        row=matches[0];name=row['schema_file']
        shape,_=legacy['for_structured_output'](json.loads((source/'schemas'/name).read_text(encoding='utf-8')))
        if smoke_validation.schema_hash(shape)!=receipt['schema_sha256']:raise ValueError('historical submitted-schema hash mismatch')
        proof={'submitted_schema':shape,'stop_reason':row.get('stop_reason'),'schema_file':name,
               'source_manifest_sha256':source_pin,'source_smoke_log_sha256':sha(origin/'smoke_tests.jsonl')}
        evidence[hashlib.sha256(raw).hexdigest()]=proof
        _,assessment=smoke_validation.receipt_evidence(path,evidence)
        now=current.get((receipt['provider'],receipt['model'],name),{})
        reusable=assessment['accepted'] and not now.get('problems',True) and now.get('schema_sha256')==receipt['schema_sha256']
        rows.append({'receipt':path.name,'provider':receipt['provider'],'model':receipt['model'],'schema_file':name,
                     'assessment':assessment,'eligible_reuse':reusable,'current_contract_problems':now.get('problems',[])})
    shutil.copytree(origin,target)
    if inventory(target)!=before:raise ValueError('continuation copy did not preserve every original byte')
    archive=target/'migration/v15_original';archive.mkdir(parents=True)
    for name in ['structured_output.json','input/runtime_pin.json','smoke_result.json','LIVE_LAUNCH_STATUS.json','LIVE_LAUNCH_STATUS.md']:
        path=target/name
        if path.exists():
            saved=archive/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,saved)
    (target/'smoke_receipt_enrichment.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    (target/'structured_output.json').write_text('{}\n',encoding='utf-8')
    previous=structured.RECORD
    try:
        structured.RECORD=target/'structured_output.json'
        structured.recover_smoke_receipts(BudgetTracker(target))
    finally:structured.RECORD=previous
    # Financial state and original receipts are invariants, even when shape approvals are incompatible.
    for name,digest in before.items():
        if name in ('structured_output.json','input/runtime_pin.json'):continue
        if sha(target/name)!=digest:raise ValueError('source artifact changed in continuation: '+name)
    if inventory(origin)!=before:raise ValueError('source run changed during migration')
    report={'run_id':run_id,'source_runtime':str(source),'source_manifest_sha256':source_pin,
       'destination_runtime':str(destination),'destination_manifest_sha256':destination_pin,
       'source_commit':old['git_commit'],'destination_commit':new['git_commit'],
       'authorization':'Explicit researcher instruction: preserve this run, its $50 total and $1 smoke cap; no scientific checkpoint approval',
       'original_run_files_sha256':before,'receipt_reassessment':rows,
       'eligible_reuse_count':sum(r.get('eligible_reuse',False) for r in rows),
       'recorded_spend_usd':sum(e.get('cost_usd') or 0 for e in BudgetTracker(target).entries()),
       'outstanding_reservations':BudgetTracker(target).reservations(),
       'billing_reconciliation':'BLOCKED: HTTP 400 error and request ID saved, but no independent billing evidence. Unknown hold retained.',
       'new_paid_calls':0,'scientific_approvals_added':0,'status':'BLOCKED_RECONCILIATION_AND_PROVIDER_CONTRACTS'}
    (target/'input/runtime_pin.json').write_text(json.dumps({'runtime':str(destination),'manifest_sha256':destination_pin,'reviewed_commit':new['git_commit'],'run_id':run_id},indent=2)+'\n',encoding='utf-8')
    (target/'migration/continuation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report
