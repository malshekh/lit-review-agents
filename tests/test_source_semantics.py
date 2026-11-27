import copy
import hashlib
import json
from pathlib import Path
import pytest
import jsonschema
from litreview import a05_functional, source_semantics as semantics, functional_replay, evidence
from litreview import orchestrator as orch, model_record
from litreview.agents.base import validate

FIXTURE = Path(__file__).parent / 'fixtures/functional_v2'


def archived():
    return tuple(json.loads((FIXTURE / name).read_text(encoding='utf-8')) for name in ('a05.json','a06.json'))


def test_archived_replay_preserves_inputs_and_rejects_all_negative_controls():
    ext, val = archived(); before = copy.deepcopy((ext, val))
    corrected, report = functional_replay.assess(ext, val)
    assert (ext, val) == before
    assert report['expected_findings_omitted'] == [] and report['all_controls_rejected']
    assert not report['raw_extraction_entity_audit_passed']
    assert {x['entity_id'] for x in report['source_audit']['entity_label_defects']} == {'E1','E4'}
    assert corrected['contexts'] == ext['contexts']  # preserve shared context
    assert report['findings'][0]['interpretation']['specimen'] == 'plasma'
    assert report['findings'][1]['interpretation']['specimen'] == 'tumors'
    assert report['findings'][1]['interpretation']['detection_outcome'] == 'NOT_DETECTED_UNDER_REPORTED_CONDITIONS'
    assert corrected['findings'][1]['polarity'] == 'NEGATIVE'
    assert report['findings'][0]['interpretation']['comparator'] == 'NOT_APPLICABLE'
    assert report['findings'][2]['interpretation']['comparator'] == 'NONE_REPORTED'
    validate('A05-KE', corrected)
    assert evidence.finding_fingerprints(ext) != evidence.finding_fingerprints(corrected)
    with pytest.raises(jsonschema.ValidationError, match='Unsupported entity labels'):
        a05_functional.require_expected(ext, a05_functional.fixture()['expected'])


def test_production_handoff_and_writer_receive_corrected_interpretation(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, 'RUNS_DIR', tmp_path)
    monkeypatch.setattr(model_record, 'RECORD', tmp_path/'models.jsonl')
    run = orch.Run('offline'); run.save_state({'profile':'pilot7','stage':'validate','counters':{}})
    ext, val = archived()
    monkeypatch.setattr(run, '_extraction_vendor', lambda *a: 'anthropic')
    seen = []
    def replay(agent, items, callback, **kwargs):
        assert agent == 'A06-SV'
        for step, payload in items:
            seen.append(copy.deepcopy(payload))
            assert kwargs['exclude'](step) == frozenset({'anthropic'})
            assert len(payload['source_interpretation']['entity_label_defects']) == 2
            assert payload['extraction']['entities'][0]['type'] == 'MOLECULE'
            assert payload['extraction']['findings'][1]['polarity'] == 'NEGATIVE'
            validate('A06-SV', val)
            # Plumbing test ONLY: archived response is not a fresh scientific reading.
            callback(step, copy.deepcopy(val))
    monkeypatch.setattr(run, 'run_many', replay)
    result = a05_functional.handoff(run, ext, a05_functional.fixture())
    assert len(seen) == 1 and len(result['validations']) == 3
    projected = run._validated_findings([{'record_id':ext['record_id']}])
    assert projected[1]['source_interpretation']['specimen_entity_id'] == 'E3'
    assert projected[1]['polarity'] == 'NEGATIVE'
    from litreview.bridge import finding_record
    packet = finding_record(projected[1])
    assert packet['source_interpretation']['detection_outcome'] == 'NOT_DETECTED_UNDER_REPORTED_CONDITIONS'
    assert packet['source_interpretation']['comparator'] == 'NOT_APPLICABLE'
    assert all(e['type'] not in semantics.PROTECTED_LABELS for f in projected for e in f['entities'].values())
    assert run.load('source_semantics/original_extractions/FUNCTIONAL_SOURCE_1.json') == ext
    assert run.budget.spent() == 0


def test_changed_interpretation_cannot_reuse_archived_a06_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, 'RUNS_DIR', tmp_path)
    run = orch.Run('stale'); ext, val = archived(); rid = ext['record_id']
    run.save('extractions/'+rid+'.json', ext)
    sections = a05_functional.fixture()['payload']['record']['content']
    run.save('fulltext/'+rid+'.json', sections)
    from litreview.scientific_validation import source_fingerprint
    val['_finding_fingerprints'] = evidence.finding_fingerprints(ext)
    val['_source_fingerprint'] = source_fingerprint(sections)
    run.save('validations/'+rid+'.json', val)
    findings = run._validated_findings([{'record_id':rid}])
    assert all(f['eligibility']['status'] == 'REVALIDATION_REQUIRED' for f in findings)


def test_label_evidence_needs_exact_entity_binding_and_archived_lookup_hash(tmp_path):
    entity = {'entity_id':'E4','mention':'DSF','type':'APPROVED_DRUG'}
    quote = 'DSF is an FDA-approved drug.'
    row = {'entity_id':'E4','label':'APPROVED_DRUG','quote':quote,'kind':'SOURCE_QUOTATION','section':'Abstract'}
    assert semantics.label_supported(entity, {'Abstract':quote}, [row])
    assert not semantics.label_supported(entity, {'Abstract':quote}, [{**row,'entity_id':'E1'}])
    path = tmp_path/'lookup.txt'; path.write_text(quote,encoding='utf-8')
    lookup = {**row,'kind':'RECORDED_LOOKUP','archive_path':'lookup.txt','source_url':'https://example.org/record','archive_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    assert semantics.label_supported(entity, {}, semantics.load_evidence(tmp_path,[lookup]))
    assert not semantics.load_evidence(tmp_path,[{**lookup,'archive_sha256':'bad'}])
    assert not semantics.load_evidence(tmp_path,[{**lookup,'archive_path':'../outside.txt'}])
    assert not semantics.label_supported(entity, {'Abstract':'DSF was used.'}, [row])


def test_null_is_not_mapped_for_statistical_comparison_or_untested_specimen():
    ext, _ = archived(); f = ext['findings'][1]
    f.update(predicate='NO_SIGNIFICANT_DIFFERENCE', polarity='NULL')
    corrected, audit = semantics.interpret(ext,a05_functional.fixture()['payload']['record']['content'])
    assert corrected['findings'][1]['polarity'] == 'NULL'
    assert 'detection_outcome' not in audit['findings']['F2']
    f.update(predicate='DETECTED_IN', span='Tumors were not tested.')
    with pytest.raises(ValueError,match='ambiguous or untested'):
        semantics.interpret(ext, {'Abstract':a05_functional.fixture()['payload']['record']['content']['Abstract'] + ' ' + f['span']})


def test_unproven_approval_flag_and_negated_evidence_cannot_bypass_label_gate():
    ext, _ = archived(); ext['entities'][3]['drug_status_verified'] = True
    corrected, audit = semantics.interpret(ext, a05_functional.fixture()['payload']['record']['content'])
    assert 'drug_status_verified' not in corrected['entities'][3]
    quote = 'DSF is not an FDA-approved drug.'
    e = {'entity_id':'E4','mention':'DSF','type':'APPROVED_DRUG'}
    row = {'entity_id':'E4','label':'APPROVED_DRUG','quote':quote,'kind':'SOURCE_QUOTATION','section':'Abstract'}
    assert not semantics.label_supported(e, {'Abstract':quote}, [row])


def test_replay_saved_is_read_only_for_original_run_and_checks_raw_acceptance(tmp_path):
    ext, val = archived()
    run = tmp_path/'20261123-214928'
    base = run/'functional_checks/a05_canonical_json'
    outputs = base/'work/outputs'; outputs.mkdir(parents=True)
    inputs = base/'work/data/a06_inputs'; inputs.mkdir(parents=True)
    for filename, value in [('A05-KE_FUNCTIONAL_SOURCE_1.json',ext),('A06-SV_FUNCTIONAL_SOURCE_1_v1.json',val)]:
        (outputs/filename).write_text(json.dumps(value),encoding='utf-8')
    raw = outputs/'A05-KE_FUNCTIONAL_SOURCE_1.raw0.txt'
    raw.write_text(json.dumps(ext),encoding='utf-8')
    (base/'result.json').write_text(json.dumps({'accepted':False}),encoding='utf-8')
    (inputs/'FUNCTIONAL_SOURCE_1.json').write_text(json.dumps({'payload':{'mode':'PER_PAPER','extraction':ext,'paper_text':a05_functional.fixture()['payload']['record']['content']}}),encoding='utf-8')
    before = {p.relative_to(run):p.read_bytes() for p in run.rglob('*') if p.is_file()}
    report = functional_replay.replay_saved(run,tmp_path/'replay')
    assert report['original_gate_accepted'] is False and report['new_spend_usd']==0
    assert all((run/name).read_bytes()==value for name,value in before.items())
    with pytest.raises(ValueError,match='fresh'):
        functional_replay.replay_saved(run,tmp_path/'replay')
    raw.write_text('{}',encoding='utf-8')
    with pytest.raises(jsonschema.ValidationError):
        functional_replay.replay_saved(run,tmp_path/'bad-replay')
