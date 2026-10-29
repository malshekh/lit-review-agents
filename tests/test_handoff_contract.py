"""The A05/A06 -> A07 handoff contract: hedging, secondary attribution and the direction of an interaction
survive serialization into what A07 and A10 receive."""
import json
from pathlib import Path

import jsonschema
import pytest

from litreview import handoff, model_record
from litreview import orchestrator as orch
from litreview import synthesis_input as si
from litreview.tools import verification_scope as vs

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "A05-KE.schema.json").read_text(encoding="utf-8"))
RUN = Path(__file__).resolve().parents[1] / "runs" / "20261025-100039" / "data"


def finding(fid, predicate, obj="E2", **kw):
    return {"finding_id": fid, "subject_entity_id": "E1", "predicate": predicate, "object_entity_id": obj,
            "polarity": "POSITIVE", "direction": "NOT_APPLICABLE", "modality": "ASSERTED",
            "assertion_type": "REPORTED_RESULT", "origin": "EXPLICIT", "span": f"span {fid}", "context_id": "C1",
            "warrant_note": "w", "attributed_to": None, **kw}


EXT = {"record_id": "R0001", "prompt_version": "0.5", "contexts": [{"context_id": "C1", "fields": {"system": "CELL_LINE"}}],
       "entities": [{"entity_id": "E1", "mention": "DSF + galunisertib", "type": "OTHER_SPECIFIED"},
                    {"entity_id": "E2", "mention": "viability", "type": "PHENOTYPE"}],
       "findings": [finding("F1", "INCREASES", modality="REPORTED_BY_OTHERS", attributed_to="ref [15] as printed"),
                    finding("F2", "DECREASES", modality="HEDGED", assertion_type="AUTHORS_INTERPRETATION",
                            direction="DECREASE"),
                    finding("F3", "SYNERGIZES_WITH"), finding("F4", "ANTAGONIZES"),
                    finding("F5", "OTHER_SPECIFIED", predicate_detail="reverses the anti-proliferative effect of"),
                    finding("F6", "OBSERVED_OUTCOME", obj=None)]}


def _corpus(tmp_path, monkeypatch, ext=EXT):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "mr.jsonl")
    run = orch.Run("t")
    run.save("selected_corpus.json", [{"record_id": "R0001"}])
    run.save("extractions/R0001.json", ext)
    run.save("validations/R0001.json", {"validations": [
        {"finding_id": f["finding_id"], "gate2": "ALIGNED", "disposition": "SUPPORTED_WITH_CONSTRAINTS",
         "plain_language_limit": "l", "constraints": []} for f in ext["findings"]]})
    findings = run._validated_findings(run.load("selected_corpus.json"))
    frozen = si.build_corpus({}, [{"record_id": "R0001"}], findings, {}, [], None)
    a07 = {f["finding_id"]: f for f in json.loads(json.dumps(frozen, ensure_ascii=False))["validated_findings"]}
    return findings, a07


def test_reported_by_others_survives_to_a07_and_a10(tmp_path, monkeypatch):
    findings, a07 = _corpus(tmp_path, monkeypatch)
    assert (a07["R0001:F1"]["modality"], a07["R0001:F1"]["attributed_to"]) == ("REPORTED_BY_OTHERS", "ref [15] as printed")
    full, _, _ = vs.scope({"sections": [{"text_markdown": "x ⟦P1⟧."}]}, {},
                          {"propositions": [{"proposition_id": "P1", "supporting_finding_ids": ["R0001:F1"]}]}, findings)
    assert full[0]["modality"] == "REPORTED_BY_OTHERS" and full[0]["attributed_to"] == "ref [15] as printed"


def test_hedged_survives_to_a07(tmp_path, monkeypatch):
    _, a07 = _corpus(tmp_path, monkeypatch)
    f = a07["R0001:F2"]
    assert (f["modality"], f["assertion_type"], f["direction"]) == ("HEDGED", "AUTHORS_INTERPRETATION", "DECREASE")


def test_synergy_and_antagonism_stay_distinguishable(tmp_path, monkeypatch):
    findings, a07 = _corpus(tmp_path, monkeypatch)
    assert (a07["R0001:F3"]["predicate"], a07["R0001:F4"]["predicate"]) == ("SYNERGIZES_WITH", "ANTAGONIZES")
    assert a07["R0001:F5"]["predicate_detail"] == "reverses the anti-proliferative effect of"
    assert a07["R0001:F6"]["object"] is None and handoff.contract_problems(findings) == []


@pytest.mark.skipif(not RUN.exists(), reason="run 20261025-100039 not present")
def test_run_20261025_meaning_survives_serialization(monkeypatch):
    """On real data: every REPORTED_BY_OTHERS and HEDGED finding arrives at A07 as such, and the legacy
    synergy/antagonism pair (R0030 F11/F12, both OTHER_SPECIFIED POSITIVE) is told apart by what is sent."""
    run = orch.Run("20261025-100039")
    findings = run._validated_findings(run.load("selected_corpus.json"))
    frozen = json.loads(json.dumps(si.build_corpus({}, run.load("selected_corpus.json"), findings, {}, [], None)))
    a07 = {f["finding_id"]: f for f in frozen["validated_findings"]}
    source = {f"{p.stem}:{f['finding_id']}": f for p in (RUN / "extractions").glob("*.json")
              for f in json.loads(p.read_text(encoding="utf-8"))["findings"]}
    for mod in ("REPORTED_BY_OTHERS", "HEDGED"):
        want = {k for k, f in source.items() if f.get("modality") == mod}
        assert want and {k for k, f in a07.items() if f["modality"] == mod} == want
    assert all(a07[k]["attributed_to"] == f.get("attributed_to") for k, f in source.items())
    syn, ant = a07["R0030:F11"], a07["R0030:F12"]
    assert syn["predicate_detail_source"] == ant["predicate_detail_source"] == handoff.LEGACY_DETAIL
    assert "synerg" in syn["warrant_note"].lower() and "antagonis" in ant["warrant_note"].lower()
    assert handoff.contract_problems(findings) == []


def test_the_schema_requires_a_named_relation_and_a_real_object():
    def out(*fs):
        return {"agent_id": "A5-KE", "prompt_version": "0.5", "status": "COMPLETE", "warnings": [], "limitations": [],
                "record_id": "R1", "content_level": "ABSTRACT", "study_profile": {}, "entities": [], "contexts": [],
                "author_stated_limitations": [], "findings": list(fs)}
    jsonschema.validate(out(finding("F1", "ANTAGONIZES"), finding("F2", "MAXIMUM_TOLERATED_DOSE", obj=None),
                            finding("F3", "OTHER_SPECIFIED", predicate_detail="biphasic change in")), SCHEMA)
    for bad in (finding("F1", "OTHER_SPECIFIED"), finding("F1", "OTHER_SPECIFIED", predicate_detail=""),
                finding("F1", "INHIBITS", obj=None), finding("F1", "SYNERGISES")):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(out(bad), SCHEMA)
    assert handoff.extraction_problems({"findings": [finding("F1", "OTHER_SPECIFIED")]})


def test_a_new_extraction_without_a_named_relation_fails_the_handoff(tmp_path, monkeypatch):
    ext = {**EXT, "findings": [finding("F1", "OTHER_SPECIFIED")]}
    findings, _ = _corpus(tmp_path, monkeypatch, ext)
    assert handoff.contract_problems(findings) == ["R0001:F1: OTHER_SPECIFIED with no relation named"]
    legacy = {**ext, "prompt_version": "0.4"}                     # an older extraction is marked, not failed
    findings, a07 = _corpus(tmp_path, monkeypatch, legacy)
    assert handoff.contract_problems(findings) == [] and a07["R0001:F1"]["predicate_detail_source"] == handoff.LEGACY_DETAIL
