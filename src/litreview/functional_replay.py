"""Offline, versioned assessment of archived A05/A06; never dispatches a model."""
from __future__ import annotations
import copy
import jsonschema
from . import a05_functional, source_semantics


def controls():
    def swap(e):
        e['findings'][0]['object_entity_id'], e['findings'][1]['object_entity_id'] = e['findings'][1]['object_entity_id'], e['findings'][0]['object_entity_id']
    def absence(e): e['findings'][1]['warrant_note'] = 'The molecule was absent from tumors (biological absence).'
    def concentration(e): e['findings'][2]['quantities'][0].update(value_type='CONCENTRATION', measured_property='numerical concentration')
    def label(e): e['entities'][0]['type'] = 'ENDOGENOUS_METABOLITE'
    def empty(e): e['findings'] = []
    return {'swapped_specimens': swap, 'biological_absence': absence, 'dose_as_concentration': concentration, 'unsupported_entity_label': label, 'empty_findings': empty}


def assess(extraction, validation):
    source = a05_functional.fixture()
    sections = source['payload']['record']['content']
    from .agents.base import validate
    from .tools import span_check
    validate('A05-KE', extraction)
    if any(not span_check.passed(g) for g in span_check.check_findings(extraction, sections)):
        raise ValueError('Archived extraction fails full source/quantity gates')
    original = copy.deepcopy(extraction)
    corrected, audit = source_semantics.interpret(extraction, sections)
    validate('A05-KE', corrected)
    a05_functional.require_expected(corrected, source['expected'])
    failures = {}
    for name, change in controls().items():
        bad = copy.deepcopy(corrected); change(bad)
        try: a05_functional.require_expected(bad, source['expected'])
        except (ValueError, jsonschema.ValidationError) as exc:
            failures[name] = {'rejected': True, 'reason': str(exc)}
        else: failures[name] = {'rejected': False, 'reason': 'CONTROL ESCAPED'}
    assert extraction == original
    dispositions = {v['finding_id']: v for v in validation['validations']}
    findings = [{'finding_id': f['finding_id'], 'subject_entity_id': f['subject_entity_id'], 'object_entity_id': f.get('object_entity_id'),
                 'predicate': f['predicate'], 'polarity': f['polarity'], 'quotation': f['span'], 'location': f['span_location'],
                 'quantities': f.get('quantities', []), 'interpretation': audit['findings'][f['finding_id']],
                 'archived_a06': dispositions.get(f['finding_id'])} for f in corrected['findings']]
    return corrected, {'rule_version': source_semantics.RULE_VERSION, 'functional_check_version': a05_functional.CHECK_VERSION,
        'verdict': 'FINDING_COVERAGE_PASS_LABEL_DEFECTS_QUARANTINED_REVALIDATION_REQUIRED',
        'source_excerpt': sections, 'expected_findings_omitted': [], 'findings': findings, 'source_audit': audit,
        'raw_extraction_entity_audit_passed': not audit['entity_label_defects'],
        'archived_a06_did_not_report_entity_defects': not validation.get('defect_reports'),
        'negative_controls': failures, 'all_controls_rejected': all(v['rejected'] for v in failures.values()),
        'new_a05_required': False, 'a06_only_required': True,
        'archived_a06_is_new_validation': False, 'paid_dispatches': 0, 'new_spend_usd': 0,
        'corpus_selection': False, 'full_text_extraction_tested': False}


def replay_saved(run_dir, output_dir):
    """Read an existing run, add a distinct versioned replay; retain every original byte."""
    import hashlib, json
    from pathlib import Path
    from . import structured, config
    from .budget import BudgetTracker
    from .agents.base import build_system_prompt, user_parts
    run_dir, output_dir = Path(run_dir), Path(output_dir)
    if output_dir.exists():
        raise ValueError('Replay destination must be fresh; prior replay evidence is immutable')
    originals = {p.relative_to(run_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in run_dir.rglob('*') if p.is_file()}
    base = run_dir/'functional_checks/a05_canonical_json'
    ext = json.loads((base/'work/outputs/A05-KE_FUNCTIONAL_SOURCE_1.json').read_text(encoding='utf-8'))
    val = json.loads((base/'work/outputs/A06-SV_FUNCTIONAL_SOURCE_1_v1.json').read_text(encoding='utf-8'))
    # Reassess the exact original raw response through the full ordinary-JSON
    # acceptance path before interpreting its saved canonical counterpart.
    from .extraction_mode import accept
    raw = (base/'work/outputs/A05-KE_FUNCTIONAL_SOURCE_1.raw0.txt').read_text(encoding='utf-8')
    if accept(raw, a05_functional.fixture()['payload']) != ext:
        raise ValueError('Archived raw/canonical A05 mismatch; no replay accepted')
    corrected, report = assess(ext, val)
    old_gate = json.loads((base/'result.json').read_text(encoding='utf-8'))
    report['original_gate_accepted'] = old_gate['accepted']
    report['original_gate_preserved'] = True
    report['run_id'] = run_dir.name
    budget = BudgetTracker(run_dir)
    previous_record = structured.RECORD
    try:
        structured.RECORD = run_dir/'structured_output.json'
        forecast = a05_functional.plan(budget)
    finally:
        structured.RECORD = previous_record
    model = config.agent_model('A06-SV')
    a06_bound = round(structured.smoke_worst(budget,model.provider,model.model,a05_functional.A06_INPUT_BYTES,a05_functional.A06_OUTPUT_TOKENS)*2,7)
    payload = json.loads((base/'work/data/a06_inputs/FUNCTIONAL_SOURCE_1.json').read_text(encoding='utf-8'))['payload']
    payload['extraction'] = corrected
    payload['source_interpretation'] = report['source_audit']
    schema, schema_hash = structured.slim('A06-SV.schema.json',model.provider)
    input_bound = (len(build_system_prompt('A06-SV').encode()) + sum(len(p['text'].encode()) for p in user_parts(payload,()))
                   + len(json.dumps(schema).encode()) + 1024)
    if input_bound > a05_functional.A06_INPUT_BYTES:
        raise ValueError('Prepared A06-only input exceeds the inherited bound')
    report['verification_plan'] = {'status':'PREPARED_OFFLINE_NOT_AUTHORIZED', 'new_a05_calls':0,
        'a06_provider':model.provider,'a06_model':model.model,'a06_submitted_schema_sha256':schema_hash,
        'a06_only_worst_case_usd':a06_bound,'a06_primary_and_at_most_one_format_repair':True,
        'a06_input_byte_cap':a05_functional.A06_INPUT_BYTES,'a06_prepared_input_bound':input_bound,
        'a06_output_token_cap':a05_functional.A06_OUTPUT_TOKENS,'a06_payload_sha256':source_semantics.digest(payload),
        'required_order':['A06 exact strict check','A06-only corrected-record independent validation'],
        'a06_prerequisite_strict_worst_case_usd': next(structured.smoke_worst(budget,t['provider'],t['model'],len(structured.SMOKE_SYSTEM.encode())+len(json.dumps(t['schema']).encode())+200,structured.SMOKE_MAX_TOKENS) for t in structured.targets() if t['agent']=='A06-SV'),
        'pending_strict_checks':forecast['strict_checks_remaining'],
        'strict_worst_case_usd':forecast['strict_remaining_worst_case_usd'],
        'prior_successes_still_matching':forecast['prior_successes_still_matching'],
        'prior_success_count':forecast['prior_success_count'],
        'recorded_spend_usd':budget.spent(),'outstanding_holds_usd':budget.reserved(),
        'hold_count':len(budget.reservations()),'strict_receipt_count':len(list((run_dir/'smoke_receipts').glob('*.json'))),
        'smoke_remaining_usd':forecast['smoke_remaining_after_spend_and_holds_usd'],
        'exposure_after_all_strict_and_a06_only_usd':round(budget.spent()+budget.reserved()+forecast['strict_remaining_worst_case_usd']+a06_bound,7),
        'remaining_after_all_strict_and_a06_only_usd':round(forecast['smoke_remaining_after_spend_and_holds_usd']-forecast['strict_remaining_worst_case_usd']-a06_bound,7),
        'caps':{'smoke_usd':1,'combined_usd':50,'review_pauses_usd':[25,48]},
        'prices_basis':'Existing configured prices checked 2026-11-23; conservative maximum input/cache-read/cache-write rate. No price or model changes.'}
    output_dir.mkdir(parents=True)
    for name,value in [('report.json',report),('corrected_extraction.json',corrected),('prepared_a06_payload.json',payload),('original_artifact_hashes.json',originals)]:
        (output_dir/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    changed = [name for name,digest in originals.items() if not (run_dir/name).is_file() or hashlib.sha256((run_dir/name).read_bytes()).hexdigest()!=digest]
    if changed:
        raise RuntimeError('Original evidence changed during replay: '+str(changed))
    (output_dir/'preservation.json').write_text(json.dumps({'all_original_files_unchanged':True,'original_files_checked':len(originals),'new_paid_dispatches':0,'original_gate_overwritten':False},indent=2),encoding='utf-8')
    return report


if __name__ == '__main__':
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',required=True,type=Path)
    parser.add_argument('--output-dir',required=True,type=Path)
    args = parser.parse_args()
    report = replay_saved(args.run_dir,args.output_dir)
    print(report['verdict'])
    print(report['verification_plan'])
