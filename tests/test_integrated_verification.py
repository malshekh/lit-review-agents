"""Integration counterexamples; scripted judgments do not prove scientific discovery."""
import copy
import pytest
from litreview import orchestrator as orch
from litreview.tools import span_check
from test_verification_job import job


@pytest.mark.parametrize('change', [dict(status='INCOMPLETE'),
    dict(status='COMPLETE', findings_unaccounted=['R0001:F1']),
    dict(status='COMPLETE', coverage_incomplete_item_ids=['M1'])])
def test_incomplete_synthesis_rejected_before_registry_or_provider(tmp_path, monkeypatch, change):
    monkeypatch.setattr(orch, 'RUNS_DIR', tmp_path)
    run = orch.Run('integration')
    monkeypatch.setattr(run, '_findings', lambda: pytest.fail('must stop before reading evidence'))
    with pytest.raises(orch.Pause, match='incomplete synthesis'):
        run._verification_registry(change)


def test_transitive_plan_binding_preserves_complete_proposition_and_source(tmp_path):
    j, _ = job(tmp_path)
    p = j.package['propositions'][0]
    p.update(constraints=['Only the copper-containing arm at 1 uM'],
        context_qualifiers={'model': 'U87 in vitro', 'arm': 'DSF plus copper'},
        evidence_qualifiers={'certainty': 'may', 'attribution': 'secondhand'},
        scientific_limitations=['Shared cohort; not independent replication'],
        reconciliation_issue_ids=['X1'], source_item_ids=['M1'])
    j.package['source_items'] = {'M1': {'source': {'span': 'Original source evidence'}}}
    j.plan['items'] = [{'item_id': 'B1', 'proposition_ids': ['P1']}]
    # Rebuild indexes as production does on a new verification version.
    from litreview.tools import verification_scope
    from litreview import evidence
    j.idx = verification_scope._index(j.package, j.plan)
    j.evidence_idx = evidence._named(j.package, j.plan)
    o = copy.deepcopy(next(o for o in j.occurrences if o['item_ids'] == ['P1']))
    o['item_ids'] = ['B1']
    payload = j.local_payload([o])
    assert payload['occurrences'][0]['propositions']['P1'][0] == p
    assert payload['synthesis_source_items'] == j.package['source_items']
    assert payload['findings']  # Full original finding, not just its compact index.


def test_upstream_gate1_counterexample_remains_visible(tmp_path, monkeypatch):
    """Documents an upstream defect without changing A06 rules in this task."""
    monkeypatch.setattr(orch, 'RUNS_DIR', tmp_path)
    run = orch.Run('gate1-counterexample')
    ext = {'findings': [{'finding_id': 'F1', 'span': 'Invented effect at 1000 mM',
        'quantities': [], 'primary_theme_id': 'T1'}], 'entities': [], 'contexts': []}
    run.save('extractions/R0001.json', ext)
    run.save('validations/R0001.json', {'validations': [
        {'finding_id': 'F1', 'disposition': 'SUPPORTED', 'constraints': []}]})
    assert not span_check.check_findings(ext, {'results': 'No such effect reported'})[0]['span_found']
    findings = run._validated_findings([{'record_id': 'R0001'}])
    assert findings[0]['eligibility']['status'] == 'SUPPORTING'


def test_a06_schema_accepts_complete_without_any_finding_dispositions():
    import json
    import jsonschema
    from litreview.paths import SCHEMAS_DIR
    schema = json.loads((SCHEMAS_DIR/'A06-SV.schema.json').read_text())
    jsonschema.validate({'agent_id':'A06-SV','prompt_version':'audit','status':'COMPLETE',
        'warnings':[],'limitations':[],'mode':'PER_PAPER'}, schema)


def test_capacity_fixture_uses_real_proposition_tags_and_5000_words(tmp_path):
    from a10_capacity_simulation import fixture
    from litreview.tools import tags
    from litreview.verification_job import inventory
    j, _ = job(tmp_path)
    from test_synthesis_bounded import corpus
    from litreview.synthesis_registry import EvidenceRegistry
    registry = EvidenceRegistry(corpus(12))
    package = {'propositions': [{'proposition_id': f'P{i}', 'evidence': [
        {'finding_id': f'R{i:04d}:F1', 'role': 'SUPPORTING'}]} for i in range(1,13)]}
    m, tables = fixture(registry, package)
    assert sum(len(tags.strip_tags(s['text_markdown']).split()) for s in m['sections']) == 5000
    assert sum(bool(o['item_ids']) for o in inventory(m, tables)) >= 200


def test_cross_theme_shared_study_and_adversarial_details_remain_retrievable(tmp_path):
    j, _ = job(tmp_path)
    first = j.registry.findings['R0001:F1']
    second = j.registry.findings['R0002:F1']
    first.update(predicate='SYNERGIZES_WITH', modality='HEDGED', attributed_to='R0002', span='Reported synergy at 1 uM',
                 quantities=[{'raw_value':'1', 'unit':'uM'}])
    second.update(predicate='ANTAGONIZES', span='Reported antagonism at 1000 mM', quantities=[{'raw_value':'1000', 'unit':'mM'}])
    ids, sources, props = j.retrieve([{'finding_ids': ['R0001:F1','R0002:F1']}])
    detail = j.registry.details(ids)
    assert {f['predicate'] for f in detail['findings']} == {'SYNERGIZES_WITH','ANTAGONIZES'}
    assert detail['contexts'] and all(f['span'] for f in detail['findings'])
    independence = j.registry.independence(ids)
    assert independence['papers'] == 2
    assert independence['known_study_ids'] == ['SAME_STUDY']
    assert independence['independent_studies'] is None
    assert first['primary_theme_id'] != second['primary_theme_id']
