"""The A06 instability test and human review of disagreements.

A repeat replays the exact input of the original whole-paper call, so any disagreement is the model's; a
finding whose two readings give it different roles is quarantined, and where roles agree the more cautious
reading stands. Every human decision on a disagreement carries its cause, and the reading a decision keeps
is the one the finding carries everywhere (disposition, constraints and eligibility alike)."""
import copy

import pytest

from litreview import evidence as ev
from litreview import model_record
from litreview import orchestrator as orch
from litreview.tools import cost_projection as cp

WRONG = {"normalization_state": "RESOLVED", "normalization_source": "OLS4/CHEBI", "normalized_id": "CHEBI:81585",
         "approved_name": "cis-11-Methyl-2-dodecenoic acid"}


def _run(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    run = orch.Run("t")
    run.save_state({"stage": "validate", "status": "READY", "counters": {}})
    run.save("selected_corpus.json", [{"record_id": "R0001"}])
    run.save("fulltext/R0001.json", {"Abstract": "We repurposed disulfiram (DSF) against glioblastoma. " +
        ' '.join(f'DSF suppressed growth ({i}).' for i in (1,2,3))})
    run.save("extractions/R0001.json", {
        "record_id": "R0001",
        "entities": [{"entity_id": "E1", "mention": "DSF", "type": "APPROVED_DRUG", **WRONG},
                     {"entity_id": "E2", "mention": "growth", "type": "PHENOTYPE", "normalization_state": "UNRESOLVED"}],
        "findings": [{"finding_id": f"F{i}", "subject_entity_id": "E1", "object_entity_id": "E2", "predicate": "DECREASES",
                      "span": f"DSF suppressed growth ({i}).", "context_id": "C1"} for i in (1, 2, 3)],
        "contexts": [{"context_id": "C1", "fields": {}}]})
    monkeypatch.setattr(run, "_extraction_vendor", lambda rid, entries=None: "anthropic")
    run.cfg = {**run.cfg, "validation": {"instability_test": True}, "batch": {"enabled": False}}
    return run


def _v(fid, disposition, constraints=(), gate2="ALIGNED"):
    return {"finding_id": fid, "gate1": "PASSED", "gate2": gate2, "disposition": disposition,
            "constraints": list(constraints), "plain_language_limit": f"{fid} {disposition}"}


def _doc(*vals):
    present = {v['finding_id'] for v in vals}
    return {"record_id": "R0001", "validations": list(vals) +
        [_v(f'F{i}', 'SUPPORTED') for i in (1,2,3) if f'F{i}' not in present]}


def _finding(run, fid):
    return next(f for f in run._validated_findings(run.load("selected_corpus.json")) if f["finding_id"] == f"R0001:{fid}")


# ------------------------------------------------------------------ review decisions
def test_keep_old_restores_the_old_reading_everywhere_not_only_its_status(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    run._save_validation("R0001", _doc(_v("F1", "SUPPORTED_FOR_OBSERVATION", ["observed, not shown to be causal"])))
    run._save_validation("R0001", _doc(_v("F1", "DOES_NOT_ESTABLISH", ["new reading"])))   # lost its role
    assert _finding(run, "F1")["eligibility"]["status"] == "QUARANTINED"
    run.decide_review("R0001:F1", "KEEP_OLD", "span and abstract read: the observation stands", "BIOLOGICAL_INTERPRETATION")
    f = _finding(run, "F1")
    assert f["disposition"] == "SUPPORTED_FOR_OBSERVATION" and ev.status_of(f) == "SUPPORTING"
    assert f["constraints"] == ["observed, not shown to be causal"]
    assert f["plain_language_limit"] == "F1 SUPPORTED_FOR_OBSERVATION"


def test_a_decision_needs_a_cause_and_holding_keeps_the_finding_out(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    run._save_validation("R0001", _doc(_v("F1", "BLOCKED_ALIGNMENT", gate2="ENTITY_MISMATCH")))
    run._save_validation("R0001", _doc(_v("F1", "SUPPORTED_WITH_CONSTRAINTS")))
    with pytest.raises(ValueError, match="cause"):
        run.decide_review("R0001:F1", "KEEP_QUARANTINED", "four passes do not overturn a whole-paper block")
    with pytest.raises(ValueError, match="decision must be"):
        run.decide_review("R0001:F1", "MERGE", "n", "EXTRACTION_ERROR")
    run.classify_review("R0001:F1", "EXTRACTION_ERROR", "object is the drug, the span is about its cytotoxicity")
    run.decide_review("R0001:F1", "KEEP_QUARANTINED", "four passes do not overturn a whole-paper block")
    item = run.load("validation_review.json")[0]
    assert (item["decision"], item["cause"], item["cause_by"]) == ("KEEP_QUARANTINED", "EXTRACTION_ERROR", "human")
    assert ev.status_of(_finding(run, "F1")) == "QUARANTINED"
    assert ev.review_by_cause(run.load("validation_review.json")) == {
        "EXTRACTION_ERROR": {"QUARANTINED_KEEP_QUARANTINED": 1}}


# ------------------------------------------------------------------ the instability test
def test_compare_repeat_quarantines_role_changes_and_keeps_the_more_cautious_reading():
    original = _doc(_v("F1", "BLOCKED_ALIGNMENT", gate2="ENTITY_MISMATCH"), _v("F2", "SUPPORTED"),
                    _v("F3", "SUPPORTED_WITH_CONSTRAINTS", ["orig"]), _v("F4", "BLOCKED_PROVENANCE"))
    repeat = _doc(_v("F1", "SUPPORTED_WITH_CONSTRAINTS"), _v("F2", "SUPPORTED_WITH_CONSTRAINTS", ["rep"]),
                  _v("F3", "SUPPORTED"), _v("F4", "BLOCKED_PROVENANCE"))
    rows, items = ev.compare_repeat("R0001", original, repeat)
    got = {i["local_id"]: (i["direction"], i["action"], i["cause"]) for i in items}
    assert got == {"F1": ("IMPROVED", "QUARANTINED", "UNEXPLAINED_MODEL_VARIANCE"),
                   "F2": ("NARROWED", "APPLIED", "UNEXPLAINED_MODEL_VARIANCE"),
                   "F3": ("IMPROVED", "KEPT", "UNEXPLAINED_MODEL_VARIANCE")}
    effective = ev.effective_validations(original, {i["local_id"]: i for i in items})
    assert effective["F2"]["constraints"] == ["rep"] and effective["F3"]["constraints"] == ["orig"]
    agreement = ev.repeat_agreement(rows)
    assert agreement["blocked_findings"]["disposition"] == {"n": 2, "agree": 1, "rate": 0.5}
    assert agreement["all_findings"]["role"] == {"n": 4, "agree": 3, "rate": 0.75}


def test_the_repeat_replays_the_original_input_exactly_even_after_an_identity_was_stripped(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    ext = run.load("extractions/R0001.json")
    payload = {"mode": "PER_PAPER", "review_spec": {}, "extraction": copy.deepcopy(ext), "gate1_results": [],
               "paper_text": run.load("fulltext/R0001.json")}
    run._save_a06_input("R0001", "A06-SV_R0001_v1", payload)
    # the original reading reports a normalization conflict: code strips the identity from the extraction file
    run._save_validation("R0001", {**_doc(_v("F1", "BLOCKED_ALIGNMENT", gate2="ENTITY_MISMATCH"), _v("F2", "SUPPORTED"),
                                          _v("F3", "SUPPORTED")),
                                   "normalization_conflicts": [{"entity_id": "E1", "reason": "DSF is disulfiram here"}]})
    assert run.load("extractions/R0001.json")["entities"][0]["normalization_state"] == "CONFLICT"
    sent = []

    def agent(agent_id, p, step, **kw):
        sent.append((agent_id, step, p))
        return _doc(_v("F1", "SUPPORTED_WITH_CONSTRAINTS"), _v("F2", "SUPPORTED"), _v("F3", "SUPPORTED"))
    monkeypatch.setattr(run, "agent", agent)
    run._instability_test(run.load("selected_corpus.json"))
    assert [(a, s) for a, s, _ in sent] == [("A06-SV", "A06-SV_R0001_repeat")]
    assert sent[0][2] == payload                                       # the identity A06 originally saw, unchanged
    assert sent[0][2]["extraction"]["entities"][0]["normalized_id"] == "CHEBI:81585"
    report = run.load("instability_test.json")
    assert report["granularity"] == "whole paper vs whole paper"
    assert report["agreement"]["blocked_findings"]["role"] == {"n": 1, "agree": 0, "rate": 0.0}
    assert report["papers"]["R0001"]["original"]["step"] == "A06-SV_R0001_v1"
    assert ev.status_of(_finding(run, "F1")) == "QUARANTINED"          # different roles: a human decides
    assert run.load("validations/R0001.json")["validations"][0]["disposition"] == "BLOCKED_ALIGNMENT"   # not replaced
    sent.clear()
    run._instability_test(run.load("selected_corpus.json"))           # resumable: never paid twice
    assert sent == []


def test_a_paper_whose_conditions_changed_is_skipped_not_compared(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    run._save_a06_input("R0001", "A06-SV_R0001_v1", {"mode": "PER_PAPER"})
    saved = run.load("a06_inputs/R0001.json")
    run.save("a06_inputs/R0001.json", {**saved, "system_prompt_sha256": "0" * 64})   # the prompt was revised since
    run._save_validation("R0001", _doc(_v("F1", "BLOCKED_ALIGNMENT")))
    monkeypatch.setattr(run, "agent", lambda *a, **k: pytest.fail("no call when the conditions differ"))
    run._instability_test(run.load("selected_corpus.json"))
    assert "system_prompt_sha256" in run.load("instability_test.json")["skipped"]["R0001"]


def test_a_replay_input_that_no_longer_matches_its_hash_is_never_replayed(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    run._save_a06_input("R0001", "A06-SV_R0001_v1", {"mode": "PER_PAPER", "paper_text": {"Abstract": "original"}})
    saved = run.load("a06_inputs/R0001.json")
    run.save("a06_inputs/R0001.json", {**saved, "payload": {**saved["payload"], "paper_text": {"Abstract": "edited"}}})
    run._save_validation("R0001", _doc(_v("F1", "BLOCKED_ALIGNMENT")))
    monkeypatch.setattr(run, "agent", lambda *a, **k: pytest.fail("a mismatched input is not the original input"))
    run._instability_test(run.load("selected_corpus.json"))
    report = run.load("instability_test.json")
    assert "comparison invalid" in report["invalid"]["R0001"] and report["papers"] == {}


def test_a_mismatch_found_after_the_repeat_invalidates_the_comparison(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    run._save_a06_input("R0001", "A06-SV_R0001_v1", {"mode": "PER_PAPER", "paper_text": {"Abstract": "original"}})
    run._save_validation("R0001", _doc(_v("F1", "BLOCKED_ALIGNMENT"), _v("F2", "SUPPORTED")))
    run.save("validation_repeats/R0001.json", _doc(_v("F1", "SUPPORTED"), _v("F2", "SUPPORTED")))   # repeat already ran
    saved = run.load("a06_inputs/R0001.json")
    run.save("a06_inputs/R0001.json", {**saved, "payload": {"mode": "PER_PAPER"}})                # then the input changed
    monkeypatch.setattr(run, "agent", lambda *a, **k: pytest.fail("no call"))
    run._instability_test(run.load("selected_corpus.json"))
    report = run.load("instability_test.json")
    assert "R0001" in report["invalid"] and report["papers"] == {}
    assert report["agreement"]["all_findings"]["role"]["n"] == 0                 # nothing counted
    assert not [i for i in run.load("validation_review.json", []) if i.get("kind") == "REPEAT"]
    assert ev.status_of(_finding(run, "F1")) != "QUARANTINED"                  # no review item from an invalid pair


def test_papers_with_no_blocked_finding_are_not_repeated(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    run._save_a06_input("R0001", "A06-SV_R0001_v1", {"mode": "PER_PAPER"})
    run._save_validation("R0001", _doc(_v("F1", "SUPPORTED"), _v("F2", "DOES_NOT_ESTABLISH")))
    monkeypatch.setattr(run, "agent", lambda *a, **k: pytest.fail("nothing blocked, nothing to repeat"))
    run._instability_test(run.load("selected_corpus.json"))


# ------------------------------------------------------------------ spend
RATES = {"reference_run": "ref", "per_paper": {
    "ABSTRACT": {"papers": 10, "p90_usd": 0.6, "a06_p90_usd": 0.2, "findings_p90": 18},
    "FULL_TEXT": {"papers": 10, "p90_usd": 2.0, "a06_p90_usd": 0.7, "findings_p90": 41}},
    "per_theme": {"themes": 10, "p90_usd": 0.1}, "themes_per_paper": 2.3}


def test_the_projection_prices_one_repeat_per_paper(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    sel = [{"record_id": "R0007", "pmcid": "PMC1"}, {"record_id": "R0008"}, {"record_id": "R0009"}]
    on = cp.for_selection(RATES, sel, run.dir, run.budget, run.route, run.cfg)
    off = cp.for_selection(RATES, sel, run.dir, run.budget, run.route, {**run.cfg, "validation": {}})
    line = next(x for x in on["lines"] if "instability" in x["stage"])
    assert line["usd"] == pytest.approx(0.7 + 2 * 0.2) and line["basis"] == "MEASURED_P90"
    assert on["projected_total_usd"] == pytest.approx(off["projected_total_usd"] + 1.1, abs=0.01)


def test_committed_a07_turns_are_not_priced_again():
    from litreview import config
    from litreview.budget import BudgetTracker
    import tempfile
    from pathlib import Path
    b, cfg = BudgetTracker(Path(tempfile.mkdtemp())), config.load("pipeline")
    route = lambda a, ex=frozenset(): config.agent_candidates(a)[0]
    from litreview.tools import forecast
    full = cp.downstream(b, route, cfg, 120)[0]
    rest = cp.downstream(b, route, cfg, 120, a07_done=3)[0]
    expected = 2 + forecast.A07_GROUP_CALLS(120) + -(-forecast.A07_PROPOSITIONS_PER_FINDING * 120 // 32)
    assert rest["usd"] == pytest.approx(full["usd"] * (1 - 3 / expected), abs=0.001)
    assert rest["calls"] < full["calls"]


@pytest.mark.projection_guard
def test_a_stopped_a07_job_supersedes_the_projection_until_it_is_redone(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    run.save("cost_projection.json", {"verdict": "WITHIN_CAP", "projected_total_usd": 30, "cap_usd": 35})
    monkeypatch.setattr(orch, "run_agent", lambda *a, **k: {"ok": True})
    assert run.agent("A06-SV", {}, "A06-SV_x") == {"ok": True}
    run._supersede_projection("A07 job stopped: GROUP_G2 truncated at max_tokens")
    with pytest.raises(orch.Pause, match="superseded"):
        run.agent("A07-SYN", {}, "A07-SYN_jobx_GROUP_G2")


def test_a_new_run_records_the_code_it_starts_from(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    run_id = orch.new_run("topic")
    import json
    v = json.loads((tmp_path / run_id / "input" / "code_version.json").read_text(encoding="utf-8"))
    assert set(v) == {"commit", "clean", "recorded_at"} and (v["commit"] is None or len(v["commit"]) == 40)
