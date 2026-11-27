"""Audited A06-only continuation of the existing pilot; no A05 generation."""
from __future__ import annotations
import dataclasses, hashlib, json, math, re
from pathlib import Path
from . import a05_functional, config, structured, smoke_validation
from .source_semantics import digest

PREPARED = 'docs/pilot7/source_semantics_v2/raw_validated'
RESULT = 'functional_checks/a06_source_semantics_v2/result.json'
STEP = 'A06-SV_FUNCTIONAL_SOURCE_1_semantics_v2'


def write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def authorize(run, root):
    from .retained_hold import blocking_holds
    auth=json.loads((root/'pilot_semantics_authorization.json').read_text(encoding='utf-8'))
    if auth['run_id']!=run.id:raise ValueError('Wrong authorized run')
    if not math.isclose(run.budget.reserved(),auth['baseline_hold_usd'],abs_tol=1e-9) or blocking_holds(run.budget,root/'pilot_retained_hold_authorization.json'):
        raise ValueError('New or changed unresolved hold; stop')
    if run.budget.spent()-auth['baseline_spend_usd']>auth['additional_cap_usd']+1e-9:
        raise ValueError('Additional allowance exceeded')
    if a05_functional.smoke_spent(run.budget)+run.budget.reserved()>1+1e-9:raise ValueError('Smoke cap exceeded')
    if run.budget.cap!=50 or run.budget.review_points!=[25,48]:raise ValueError('Pilot limits changed')
    run.budget.operational_ceiling=min(1,auth['baseline_spend_usd']+auth['baseline_hold_usd']+auth['additional_cap_usd'])
    return auth


def prepared(root):
    folder=root/PREPARED
    report=json.loads((folder/'report.json').read_text(encoding='utf-8'))
    payload=json.loads((folder/'prepared_a06_payload.json').read_text(encoding='utf-8'))
    if digest(payload)!=report['verification_plan']['a06_payload_sha256']:raise ValueError('Prepared payload hash changed')
    return payload,report


def scientific_assessment(response):
    problems=[]; labels=[]
    rows={v['finding_id']:v for v in response.get('validations',[])}
    if set(rows)!={'F1','F2','F3'}:problems.append('Incomplete three-finding coverage')
    for fid,row in rows.items():
        if row.get('gate1')!='PASSED' or row.get('gate2')!='ALIGNED' or row.get('disposition') not in ('SUPPORTED','SUPPORTED_WITH_CONSTRAINTS','SUPPORTED_FOR_OBSERVATION'):
            problems.append(fid+': independent scientific assessment failed')
    for eid,label in [('E1','ENDOGENOUS_METABOLITE'),('E4','APPROVED_DRUG')]:
        matches=[w.split('|',4) for w in response.get('warnings',[]) if w.startswith('LABEL_ASSESSMENT|'+eid+'|'+label+'|')]
        if len(matches)!=1 or len(matches[0])!=5 or not matches[0][4].strip():
            problems.append('Missing explicit label assessment: '+label);continue
        _,_,_,decision,reason=matches[0]
        labels.append({'entity_id':eid,'label':label,'decision':decision,'reason':reason})
        if decision not in ('UNSUPPORTED','INSUFFICIENT_EVIDENCE'):problems.append('Source does not establish quarantined label: '+label)
    def text(fid):return json.dumps(rows.get(fid,{})).lower()
    if 'plasma' not in text('F1'):problems.append('F1 specimen limitation missing')
    if 'tumor' not in text('F2') or not re.search(r'(?:not|cannot|neither).{0,100}absen',text('F2')):problems.append('F2 non-detection/specimen/non-absence limit missing')
    if not (re.search(r'radiation|\brt\b',text('F3')) and re.search(r'temozolomide|\btmz\b',text('F3')) and '375' in text('F3')):problems.append('F3 reported dose/combination regimen missing')
    if any(d.get('severity') in ('MAJOR','CRITICAL') for d in response.get('defect_reports',[])):problems.append('Independent validator reports a major scientific defect')
    return {'accepted':not problems,'problems':problems,'label_decisions':labels,'finding_dispositions':rows}


def structure_only_repair(run_dir):
    """A repair may change JSON structure; it may not change the assessment."""
    audit=run_dir/'outputs'/f'{STEP}.repair.audit.json'
    if not audit.exists():return
    from .agents.base import parse_json
    try:before=parse_json((run_dir/'outputs'/f'{STEP}.raw0.txt').read_text(encoding='utf-8'))
    except (ValueError,TypeError) as exc:raise ValueError('Cannot prove malformed response repair preserves science; stop') from exc
    after=json.loads((run_dir/'outputs'/f'{STEP}.json').read_text(encoding='utf-8'))
    for key in ('validations','warnings','limitations','defect_reports','normalization_conflicts','source_inconsistencies'):
        if before.get(key)!=after.get(key):raise ValueError('Format repair changed scientific assessment: '+key)


def functional(run, root):
    from .agents.base import run_agent, validate
    from .job_ledger import Ledger, RunLock
    auth=authorize(run,root); payload,report=prepared(root)
    archived=json.loads((root/PREPARED/'original_artifact_hashes.json').read_text())
    for name,expected in archived.items():
        if name.startswith('functional_checks/a05_canonical_json/'):
            if hashlib.sha256((run.dir/name).read_bytes()).hexdigest()!=expected:raise ValueError('Archived A05/A06 evidence changed')
    if digest(payload)!=auth['source_payload_sha256']:raise ValueError('Authorized payload identity changed')
    shape,sha=structured.slim('A06-SV.schema.json','openai')
    if sha!=report['verification_plan']['a06_submitted_schema_sha256']:raise ValueError('Reviewed A06 schema changed')
    if not any(t['schema_file']=='A06-SV.schema.json' and t['already_verified'] for t in structured.targets()):raise ValueError('A06 strict check must pass first')
    result_path=run.dir/RESULT
    if result_path.exists():
        result=json.loads(result_path.read_text(encoding='utf-8'))
        if result['accepted'] and all(hashlib.sha256((run.dir/p).read_bytes()).hexdigest()==h for p,h in result['artifacts'].items()):return result
        raise ValueError('Existing failed or altered A06 recheck; do not repeat')
    m=dataclasses.replace(config.agent_model('A06-SV'),max_tokens=2500,cache_system=False,cache_payload=())
    if m.provider!='openai' or m.model!='gpt-6.1-sol':raise ValueError('Reviewed model changed')
    bound=structured.smoke_worst(run.budget,m.provider,m.model,64000,2500)*2
    if not math.isclose(bound,auth['a06_cap_usd'],abs_tol=1e-9):raise ValueError('Reviewed cost bound changed')
    identity=digest({'payload':digest(payload),'schema':sha,'prompt':__import__('litreview.agents.base',fromlist=['build_system_prompt']).build_system_prompt('A06-SV')})
    with RunLock(run.dir):
        response=run_agent('A06-SV',payload,run.dir,STEP,run.budget,run.prov,model=m,repair_limit=1,truncation_retries=0,
                           dispatch_guard=a05_functional.dispatch_guard(run.budget,'A06-SV',STEP),ledger=Ledger(run.dir),request_id=identity)
        structure_only_repair(run.dir)
        validate('A06-SV',response)
        result=scientific_assessment(response)
        result.update(run_id=run.id,payload_sha256=digest(payload),schema_sha256=sha,request_identity=identity,
                      archived_a05_reused=True,new_a05_calls=0,scientific_checkpoint_approved=False,full_text_extraction_tested=False)
        result['artifacts']={p.relative_to(run.dir).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (run.dir/'outputs').glob(STEP+'*') if p.is_file()}
        result['actual_cost_usd']=sum(e.get('cost_usd') or 0 for e in run.budget.entries() if e.get('step')==STEP)
        write(result_path,result)
    return result


def smoke(run,root,a06_only=False):
    auth=authorize(run,root)
    if not a06_only:
        if not json.loads((run.dir/RESULT).read_text())['accepted']:raise ValueError('A06 scientific recheck did not pass')
    original=structured.targets
    selected=[t for t in original() if not t['already_verified'] and ((t['schema_file']=='A06-SV.schema.json')==a06_only)]
    expected={x['schema_file']:x for x in auth['strict_targets']}
    for t in selected:
        if t['schema_file'] not in expected or any(t[k]!=expected[t['schema_file']][k] for k in ('provider','model','schema_sha256')):raise ValueError('Strict target changed')
    try:
        structured.targets=lambda:selected
        estimate,_=structured.smoke_estimate(run.budget)
        strict_spent=sum(e.get('cost_usd') or 0 for e in run.budget.entries()[auth['baseline_entry_count']:] if e.get('agent')=='smoke-test')
        if estimate+strict_spent>auth['strict_cap_usd']+1e-9:raise ValueError('Strict cost bound exceeded')
        result=structured.smoke_test(run.budget,estimate+1e-12,auth['approved_by'],retained_hold_authorization=root/'pilot_retained_hold_authorization.json')
    finally:structured.targets=original
    write(run.dir/('a06_strict_result.json' if a06_only else 'remaining_strict_result.json'),result)
    authorize(run,root)
    if result['accepted']!=result['tested']:raise ValueError('Required strict check failed; stop')
    return result


def main(root,action,run_id):
    from . import orchestrator,model_record,preflight
    from .runtime_integrity import verify,sha
    from .runtime_identity import require_execution_context
    root=Path(root);require_execution_context();preflight.require_clean_endpoints()
    verify(root,json.loads((root/'frozen_runtime_manifest.json').read_text()))
    run=orchestrator.Run(run_id)
    pin=json.loads((run.dir/'input/runtime_pin.json').read_text())
    if pin['manifest_sha256']!=sha(root/'frozen_runtime_manifest.json'):raise ValueError('Runtime pin mismatch')
    model_record.RECORD=run.dir/'model_record.jsonl';structured.RECORD=run.dir/'structured_output.json'
    authorize(run,root)
    structured.recover_smoke_receipts(run.budget)
    if action=='audit':return {'spent':run.budget.spent(),'held':run.budget.reserved(),'strict_estimate':structured.smoke_estimate(run.budget)[0],'payload_sha256':digest(prepared(root)[0])}
    if action=='a06-strict':return smoke(run,root,True)
    if action=='a06-only':return functional(run,root)
    if action=='remaining-strict':return smoke(run,root)
    if action!='scope':raise ValueError('Unknown action')
    result=json.loads((run.dir/RESULT).read_text())
    if not result['accepted'] or not all(hashlib.sha256((run.dir/p).read_bytes()).hexdigest()==h for p,h in result['artifacts'].items()):raise ValueError('Independent recheck not verified')
    if not all(t['already_verified'] for t in structured.targets()):raise ValueError('Strict checks incomplete')
    if run.state()['stage'] not in ('scope','cp1') or (run.dir/'checkpoints/CP1_approved.json').exists():raise ValueError('CP1-only execution refused')
    # Paid pilot scope is separately authorized; release only the smoke-specific
    # operational ceiling, retaining the $50 cap and $25/$48 review pauses.
    run.budget.operational_ceiling=50
    run.run(until='search')
    return {'state':run.state(),'spent_usd':run.budget.spent(),'held_usd':run.budget.reserved(),'checkpoint':'CP1; no approval'}
