"""Complete provider contracts, the list form of A03's compiled queries, the A12 unit merge, and settling an
uncertain smoke hold on attested billing evidence (never on an assumption that it was free)."""
import json
from pathlib import Path

import jsonschema
import pytest

from litreview import bridge, structured
from litreview.budget import BudgetTracker
from litreview.orchestrator import compiled_queries
from litreview.paths import SCHEMAS_DIR
from litreview.tools import contract

REPAIRED = ("A02-SP.schema.json", "A03-LM.schema.json", "A04-CQ.schema.json", "A06-SV.schema.json",
            "A08-OL.schema.json", "A10-RV.bounded.schema.json", "A12-EDI.schema.json", "A12-EDI.unit.schema.json")


def schema(name):
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def test_every_configured_strict_contract_is_complete():
    rows = structured.schema_inventory()
    assert rows and all(not r["problems"] for r in rows), [r for r in rows if r["problems"]]


@pytest.mark.parametrize("name", REPAIRED)
@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_repaired_contracts_fit_either_provider(name, provider):
    contract.for_structured_output(schema(name), provider)   # raises on any incompatibility


def _a06(mode, **over):
    doc = {"agent_id": "A06-SV", "prompt_version": "0.9", "status": "COMPLETE", "warnings": [], "limitations": [],
           "mode": mode, "record_id": None, "validations": [], "defect_reports": [], "defect_count": 0,
           "normalization_conflicts": [], "source_inconsistencies": [], "theme": None, "conflicts": [],
           "independence": [], "evidence_reach": None, "cross_packet_candidates": [],
           "packet_conflicts_not_retained": [], "retrieval_requests": []}
    return {**doc, **over}


def test_a06_one_contract_keeps_the_two_modes_apart():
    s = schema("A06-SV.schema.json")
    reach = {"systems_covered": [], "systems_missing": [], "main_constraints": [], "summary": "x"}
    jsonschema.validate(_a06("PER_PAPER", record_id="R1"), s)
    jsonschema.validate(_a06("PER_THEME", theme="T1", evidence_reach=reach), s)
    for bad in (_a06("PER_PAPER"),                                         # no record
                _a06("PER_PAPER", record_id="R1", theme="T1"),             # the other mode's identity
                _a06("PER_PAPER", record_id="R1", retrieval_requests=["F1"]),
                _a06("PER_THEME", theme="T1"),                             # no evidence reach
                _a06("PER_THEME", theme="T1", evidence_reach=reach, defect_count=2),
                _a06("PER_THEME", theme="T1", evidence_reach=reach, extra=1)):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, s)


def test_compiled_queries_list_form_legacy_map_and_duplicates():
    assert compiled_queries({"compiled": [{"source": "pubmed", "query": "a[tiab]"},
                                          {"source": "openalex", "query": "b"}]}) == {"pubmed": "a[tiab]", "openalex": "b"}
    assert compiled_queries({"compiled": {"pubmed": "a[tiab]"}}) == {"pubmed": "a[tiab]"}
    assert compiled_queries({}) == {}
    with pytest.raises(ValueError, match="compiled twice"):
        compiled_queries({"family_id": "QF1", "compiled": [{"source": "pubmed", "query": "a"},
                                                           {"source": "pubmed", "query": "b"}]})


def test_a12_unit_nulls_never_erase_front_matter():
    m = {"title": "T", "abstract": "A", "sections": [{"section_id": "S1", "heading": "h", "text_markdown": "x"}]}
    front = {"title": "New title", "abstract": None, "sections": []}
    s1 = {"title": None, "abstract": None, "sections": [{"section_id": "S1", "heading": "h", "text_markdown": "y"}]}
    out = bridge.merge_units(m, {"FRONT": front, "S1": s1})
    assert out["title"] == "New title" and out["abstract"] == "A" and out["sections"][0]["text_markdown"] == "y"


# ------------------------------------------------------------------ settling an uncertain smoke hold
@pytest.fixture
def held(tmp_path):
    budget = BudgetTracker(tmp_path)
    key = "smoke-0123456789abcdef"
    ok, _ = budget.reserve(key, 0.019586, "smoke-test", "live schema check")
    assert ok
    (tmp_path / "smoke_receipts").mkdir()
    (tmp_path / "smoke_receipts" / f"{key}.json").write_text(json.dumps(   # the older receipt form: no provider/model
        {"state": "DISPATCHED", "reservation": key, "target": "A05-KE.schema.json"}), encoding="utf-8")
    return budget, key


def test_a_hold_is_listed_and_not_settled_without_evidence_or_a_name(held):
    budget, key = held
    assert [h["reservation"] for h in structured.unsettled_smoke_holds(budget)] == [key]
    for kw in ({"evidence": "", "by": "May"}, {"evidence": "console usage", "by": " "}):
        with pytest.raises(ValueError):
            structured.settle_smoke_hold(budget, key, 0, **kw)
    with pytest.raises(ValueError, match="negative"):
        structured.settle_smoke_hold(budget, key, -1, "console usage", "May")
    assert key in budget.reservations() and not budget.entries()


def test_attested_settlement_logs_the_amount_and_releases_the_hold(held):
    budget, key = held
    with pytest.raises(ValueError, match="provider and model"):
        structured.settle_smoke_hold(budget, key, 0.0, "console", "May")
    done = structured.settle_smoke_hold(budget, key, 0.0, "Console usage for the request window shows no charge",
                                        "May", provider_request_id="req_X", provider="anthropic",
                                        model="claude-sonnet-5-5")
    assert done["billed_usd"] == 0.0 and done["held_usd"] == 0.019586 and done["previous_state"] == "DISPATCHED"
    assert key not in budget.reservations()
    [entry] = budget.entries()
    assert entry["step"] == key and entry["cost_usd"] == 0.0 and entry["attested_settlement"]["attested_by"] == "May"
    assert (entry["provider"], entry["model"]) == ("anthropic", "claude-sonnet-5-5")
    receipt = json.loads((budget.log_path.parent / "smoke_receipts" / f"{key}.json").read_text(encoding="utf-8"))
    assert receipt["state"] == "SETTLED_BY_ATTESTATION" and receipt["settlement"]["provider_request_id"] == "req_X"
    with pytest.raises(ValueError):   # once only
        structured.settle_smoke_hold(budget, key, 0.0, "again", "May", provider="anthropic", model="m")


def test_a_billed_amount_counts_as_spend(held):
    budget, key = held
    before = budget.spent()
    structured.settle_smoke_hold(budget, key, 0.0123, "provider invoice line", "May", provider="anthropic",
                                 model="claude-sonnet-5-5")
    assert budget.spent() == pytest.approx(before + 0.0123)


def test_a_received_reply_or_a_mismatched_request_id_is_not_settled_by_attestation(held):
    budget, key = held
    path = budget.log_path.parent / "smoke_receipts" / f"{key}.json"
    path.write_text(json.dumps({"state": "ERROR_RESPONSE", "reservation": key, "provider_request_id": "req_A",
                                "provider": "anthropic", "model": "claude-sonnet-5-5"}), encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        structured.settle_smoke_hold(budget, key, 0, "console", "May", provider_request_id="req_B")
    with pytest.raises(ValueError, match="differs"):
        structured.settle_smoke_hold(budget, key, 0, "console", "May", model="claude-opus-5")
    path.write_text(json.dumps({"state": "RECEIVED", "reservation": key}), encoding="utf-8")
    with pytest.raises(ValueError, match="RECEIVED"):
        structured.settle_smoke_hold(budget, key, 0, "console", "May")
    assert key in budget.reservations()


def test_anthropic_nullable_enum_uses_equivalent_typed_branches():
    from litreview.tools.structured_contract import problems
    local={"type":"object","properties":{"role":{"type":["string","null"],"enum":["PRIMARY","CONTEXT",None]}},
           "required":["role"],"additionalProperties":False}
    assert any("list-valued type" in x for x in problems(local,"anthropic"))
    wire,_=contract.for_structured_output(local,"anthropic")
    assert wire["properties"]["role"]=={"anyOf":[{"type":"string","enum":["PRIMARY","CONTEXT"]},{"type":"null"}]}
    for value in ["PRIMARY","CONTEXT",None,"OTHER",0,False,[],{}]:
        assert jsonschema.Draft202012Validator(local).is_valid({"role":value})==jsonschema.Draft202012Validator(wire).is_valid({"role":value})
    assert contract.for_structured_output(local,"openai")[0]==local
