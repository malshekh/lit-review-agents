"""Spend controls after CP2: the runtime gate before any batch (spent + committed + projected + reserve against
batch.gate_usd), re-projection when a worst-case line is overrun, and a projection that covers every stage
still ahead of the run."""
import json

import pytest
from test_batch_stage import FakeVendor, fake_interactive, install, items

from litreview import batch_stage, model_record
from litreview import orchestrator as orch
from litreview.budget import BatchGateRefused
from litreview.tools import cost_projection as cp

RATES = {"reference_run": "ref", "per_paper": {
    "ABSTRACT": {"papers": 10, "p90_usd": 0.6, "a06_p90_usd": 0.2, "findings_p90": 18},
    "FULL_TEXT": {"papers": 10, "p90_usd": 2.0, "a06_p90_usd": 0.7, "findings_p90": 41}},
    "per_theme": {"themes": 10, "p90_usd": 0.1}, "themes_per_paper": 2.3}


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    monkeypatch.setattr(batch_stage, "validate", lambda *a, **k: None)
    monkeypatch.setattr(batch_stage.time, "sleep", lambda s: None)
    monkeypatch.setattr(cp, "load_rates", lambda: RATES)
    r = orch.Run("t")
    r.save_state({"stage": "extract", "status": "READY", "counters": {}})
    (r.dir / "input").mkdir(parents=True, exist_ok=True)
    (r.dir / "input" / "topic_family.txt").write_text("onc", encoding="utf-8")
    (r.dir / "outputs").mkdir(parents=True, exist_ok=True)
    r.save("selected_corpus.json", [{"record_id": "R0001", "pmcid": "PMC1"}, {"record_id": "R0002"}])
    r.cfg = {**r.cfg, "validation": {"instability_test": True}}
    return r


def _log(run, agent, usd, time="2026-10-29T12:00:00"):
    with open(run.dir / "costs.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"time": time, "agent": agent, "step": f"{agent}_x", "provider": "p", "model": "m",
                             "input_tokens": 1, "output_tokens": 1, "cost_usd": usd}) + "\n")


def _projection(run, *lines, created="2026-10-29T11:00:00"):
    run.save("cost_projection.json", {"created": created, "verdict": "WITHIN_CAP", "lines": list(lines),
                                      "projected_total_usd": 1, "cap_usd": 35})


# ------------------------------------------------------------------ the runtime gate
@pytest.mark.projection_guard
def test_the_gate_stops_a_batch_before_anything_is_uploaded(run, monkeypatch):
    run.cfg = {**run.cfg, "batch": {**run.cfg["batch"], "gate_usd": 1.00}}
    fake, calls = FakeVendor(), []
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, calls)
    monkeypatch.setattr(orch.Run, "_require_projection", lambda self: None)
    with pytest.raises(BatchGateRefused, match=r"over the \$1.00 gate"):
        run.run_many("A05-KE", items(), lambda s, o: None)
    assert fake.created == [] and len(calls) == 1                       # the probe ran; no batch was created
    gate = [e for e in run.prov.events() if e["type"] == "tool_run" and e["tool"] == "batch_gate"]
    assert gate[-1]["summary"]["verdict"] == "STOP"


@pytest.mark.projection_guard
def test_the_gate_counts_the_batch_once_and_unsettled_batches_as_committed(run):
    # a gate above this run's projection, so the arithmetic is checked on a PASS (the A07 envelope and the
    # section-by-section A09 line put two papers over $150 at worst case)
    run.cfg = {**run.cfg, "batch": {**run.cfg["batch"], "gate_usd": 1000.00}}
    run.budget.reserve("other", 2.0, "A05-KE")                         # held by an unsettled batch
    _log(run, "A02-SP", 1.5)
    g = run._batch_gate("A05-KE", ["A05-KE_R0001"], 3.0)
    lines = {x["stage"]: x for x in g["projection_lines"]}
    # R0001 is in this batch: its extraction is the reserve; its validation is still ahead
    assert lines["A05-KE + A06-SV per paper"]["calls"] == 1 and lines["A05-KE + A06-SV per paper"]["usd"] == 0.6
    assert lines["A06-SV per paper (extracted, not validated)"]["usd"] == 0.7
    assert lines["A06-SV whole-paper repeat (instability test)"]["usd"] == pytest.approx(0.9)
    assert {"A07-SYN", "A10-RV", "A12-EDI"} <= set(lines)
    assert (g["spent_usd"], g["committed_usd"], g["reserve_usd"]) == (1.5, 2.0, 3.0)
    assert g["total_usd"] == pytest.approx(1.5 + 2.0 + g["projected_usd"] + 3.0, abs=0.01)
    assert g["verdict"] == ("PASS" if g["total_usd"] <= 1000 else "STOP") and g["limit_usd"] == 1000.0


@pytest.mark.projection_guard
def test_no_gate_configured_means_no_batch(run):
    run.cfg = {**run.cfg, "batch": {k: v for k, v in run.cfg["batch"].items() if k != "gate_usd"}}
    with pytest.raises(BatchGateRefused, match="gate_usd is not set"):
        run._batch_gate("A05-KE", ["A05-KE_R0001"], 1.0)


# ------------------------------------------------------------------ worst-case line overrun
@pytest.mark.projection_guard
def test_spend_over_a_worst_case_line_supersedes_the_projection_before_the_next_call(run, monkeypatch):
    run.save_state({"stage": "draft", "status": "READY", "counters": {}})
    _projection(run, {"stage": "A09-WRI", "basis": "WORST_CASE", "calls": 3, "usd": 1.00})
    _log(run, "A09-WRI", 1.25)
    monkeypatch.setattr(orch, "run_agent", lambda *a, **k: pytest.fail("no call after an overrun"))
    with pytest.raises(orch.Pause, match="over its worst-case line"):
        run.agent("A09-WRI", {}, "A09-WRI_v2")
    assert run.load("cost_projection.json")["verdict"] == "SUPERSEDED"


@pytest.mark.projection_guard
def test_a_call_beyond_the_lines_call_count_is_stopped_before_it_is_paid(run, monkeypatch):
    run.save_state({"stage": "draft", "status": "READY", "counters": {}})
    _projection(run, {"stage": "A09-WRI", "basis": "WORST_CASE", "calls": 1, "usd": 5.00})
    _log(run, "A09-WRI", 0.10, time="2026-10-29T10:00:00")             # before the projection: not counted
    monkeypatch.setattr(orch, "run_agent", lambda *a, **k: {"ok": True})
    assert run.agent("A09-WRI", {}, "A09-WRI_v1") == {"ok": True}
    _log(run, "A09-WRI", 0.10)
    with pytest.raises(orch.Pause, match="calls since the projection"):
        run.agent("A09-WRI", {}, "A09-WRI_v2")


# ------------------------------------------------------------------ the projection after CP2
def test_the_projection_covers_every_stage_still_ahead(run):
    run.save("validated_findings.json", [{"finding_id": f"R0001:F{i}"} for i in range(10)])
    run.save_state({"stage": "draft", "status": "READY", "counters": {}})
    stages = [x["stage"] for x in cp.remaining_for_run(run)["lines"]]
    assert stages == ["A09-WRI", "A10-RV", "A11-RC", "A12-EDI"]          # A07 and A08 are behind the run
    run.save_state({"stage": "done", "status": "COMPLETE", "counters": {}})
    assert cp.remaining_for_run(run)["lines"] == []


def test_a07_projection_covers_bounded_calls_and_retrieval_without_cache_assumptions(tmp_path):
    from litreview import config
    from litreview.budget import BudgetTracker
    from litreview.tools import forecast
    b, cfg = BudgetTracker(tmp_path), config.load("pipeline")
    route = lambda a, ex=frozenset(): config.agent_candidates(a)[0]
    line = cp.downstream(b, route, cfg, 1996)[0]
    adverse, calls = forecast.a07(1996, cfg, b, route, None)
    base = forecast.a07(1996, cfg, b, route, cfg["forecast"]["scenarios"]["baseline"])[0]
    assert line["basis"] == "CALIBRATED_FORECAST" and line["calls"] == calls          # every retrieval round counted
    assert line["usd"] == pytest.approx(base * (1 + cfg["forecast"]["uncertainty_margin"]), abs=.001)
    assert line["adverse_usd"] == pytest.approx(adverse, abs=.001) and adverse > line["usd"]
    # the calibration reproduces the measured production requests it was fitted on (docs/a07_efficiency), from above
    measured = 416_714 + 2_905_938 + 889_123 + 92_275
    fitted = sum(f(1996) for f in forecast.A07_INPUT.values())
    assert measured <= fitted <= measured * 1.10
