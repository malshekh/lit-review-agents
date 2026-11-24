"""Context utilisation per call (researcher's decision of 2026-10-30): (input + reserved output) / window, from the
provider's count where available and the byte bound otherwise, both logged; warn at the warn threshold, stop for a
recorded approval at the review threshold; per-model, operational defaults; the hard ceiling unchanged."""
import dataclasses
import json

import pytest

from litreview import checkpoints, config, context_watch
from litreview import orchestrator as orch
from litreview.admission import AdmissionRefused, assess
from litreview.agents.base import build_system_prompt, user_parts

CFG = config.load("pipeline")


def model(window_model="claude-opus-5", provider="anthropic", max_tokens=1000):
    return dataclasses.replace(config.agent_model("A09-WRI"), model=window_model, provider=provider,
                               max_tokens=max_tokens)


def cfg_with(window, models=None, default=None):
    adm = {**CFG["admission"], "context_windows": {**CFG["admission"]["context_windows"], "test-model": window}}
    cu = {**CFG["context_utilisation"], "models": models or {}, **({"default": default} if default else {})}
    return {**CFG, "admission": adm, "context_utilisation": cu}


def rec_for(payload, cfg, counter=None, m=None):
    m = m or model("test-model")
    system = build_system_prompt("A09-WRI")
    return context_watch.measure("A09-WRI", "s1", system, user_parts(payload), payload, m, cfg, counter)


def test_thresholds_are_configured_per_model_and_labelled_operational_defaults():
    assert CFG["context_utilisation"]["default"] == {"warn": 0.80, "review": 0.90}
    th = context_watch.thresholds("kimi-k3.1-pro", cfg_with(10, {"kimi-k3.1-pro": {"review": 0.85}}))
    assert th["warn"] == 0.80 and th["review"] == 0.85 and "not a reliability guarantee" in th["label"]
    with pytest.raises(ValueError):
        context_watch.thresholds("x", cfg_with(10, {"x": {"warn": 0.95, "review": 0.9}}))


def test_byte_bound_is_the_fallback_and_the_provider_count_decides_when_present():
    payload = {"text": "x" * 5000}
    m = model("test-model")
    bound_only = rec_for(payload, cfg_with(8000), m=m)
    assert bound_only["basis"] == "BYTE_BOUND" and bound_only["input_counted"] is None
    assert bound_only["utilisation"] == bound_only["utilisation_byte_bound"]
    counted = rec_for(payload, cfg_with(8000), counter=lambda s, u, mm: 1200, m=m)
    assert counted["basis"] == "PROVIDER_COUNT" and counted["input_counted"] == 1200
    assert counted["utilisation"] == round((1200 + counted["output_reserve"]) / 8000, 4)
    assert counted["utilisation_byte_bound"] == bound_only["utilisation_byte_bound"]      # both logged

    def broken(*a):
        raise RuntimeError("count endpoint down")
    fallback = rec_for(payload, cfg_with(8000), counter=broken, m=m)
    assert fallback["basis"] == "BYTE_BOUND" and "count endpoint down" in fallback["count_error"]
    unknown = rec_for(payload, CFG, m=model("no-such-model"))
    assert unknown["level"] == "WINDOW_UNKNOWN" and unknown["utilisation"] is None


def test_levels_follow_the_thresholds():
    payload = {"text": "x" * 100}
    base = rec_for(payload, cfg_with(10 ** 6))["input_byte_bound"] + 1000      # input bound + max_tokens
    assert rec_for(payload, cfg_with(int(base / 0.5)))["level"] == "OK"
    assert rec_for(payload, cfg_with(int(base / 0.82)))["level"] == "WARN"
    assert rec_for(payload, cfg_with(int(base / 0.95)))["level"] == "REVIEW"


def test_actual_utilisation_from_provider_usage():
    r = rec_for({"text": "x" * 4000}, cfg_with(10000), counter=lambda *a: 1500)
    a = context_watch.actual(r, {"input_tokens": 1000, "cached_input_tokens": 400, "cache_write_tokens": 100})
    assert a["input_tokens_actual"] == 1500 and a["utilisation_actual"] == round((1500 + 1000) / 10000, 4)
    assert a["counted_over_actual"] == 1.0 and a["byte_bound_over_actual"] == round(r["input_byte_bound"] / 1500, 3)


def _run(tmp_path, monkeypatch, window, routed="test-model"):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    run = orch.Run("ctx")
    run.cfg = cfg_with(window)
    calls = []

    def fake_run_agent(agent_id, payload, run_dir, step, budget, prov, model=None, **kw):
        calls.append(step)
        budget.record(agent_id, model.provider, model.model, 900, 10, step=step)
        return {"status": "COMPLETE"}
    monkeypatch.setattr(orch, "run_agent", fake_run_agent)
    monkeypatch.setattr(run, "route", lambda a, ex=frozenset(): model(routed))
    monkeypatch.setattr(orch.model_record, "add", lambda *a, **k: None)
    return run, calls


def events(run, tool):
    return [e["summary"] for e in run.prov.events() if e["type"] == "tool_run" and e["tool"] == tool]


def test_warn_logs_both_figures_and_proceeds(tmp_path, monkeypatch):
    payload = {"text": "y" * 2000}
    probe = rec_for(payload, cfg_with(10 ** 6))
    run, calls = _run(tmp_path, monkeypatch, int((probe["input_byte_bound"] + 1000) / 0.83))
    run.agent("A09-WRI", payload, "A09-WRI_s1")
    assert calls == ["A09-WRI_s1"]
    rec = events(run, "context_utilisation")[-1]
    assert rec["level"] == "WARN" and rec["basis"] == "BYTE_BOUND" and rec["utilisation_byte_bound"] >= 0.80
    assert "input_counted" in rec and rec["thresholds"]["label"].startswith("OPERATIONAL_DEFAULT")
    assert events(run, "context_utilisation_actual")[-1]["input_tokens_actual"] == 900


def test_review_stops_for_a_recorded_approval_of_that_exact_request(tmp_path, monkeypatch):
    payload = {"text": "z" * 2000}
    probe = rec_for(payload, cfg_with(10 ** 6))
    run, calls = _run(tmp_path, monkeypatch, int((probe["input_byte_bound"] + 1000) / 0.93))
    with pytest.raises(orch.Pause, match="CP_CONTEXT"):
        run.agent("A09-WRI", payload, "A09-WRI_s1")
    assert calls == []                                                    # nothing dispatched
    d = checkpoints.cp_dir(run.dir)
    with pytest.raises(checkpoints.DecisionIncomplete, match="approve_request"):
        checkpoints.approve(run.dir, "CP_CONTEXT", run.prov)
    decision = json.loads((d / "CP_CONTEXT_decision.json").read_text(encoding="utf-8"))
    decision["approve_request"] = True
    (d / "CP_CONTEXT_decision.json").write_text(json.dumps(decision), encoding="utf-8")
    checkpoints.approve(run.dir, "CP_CONTEXT", run.prov)
    run.agent("A09-WRI", payload, "A09-WRI_s1")
    assert calls == ["A09-WRI_s1"]
    assert events(run, "context_utilisation")[-1]["approved"] is True
    assert any(e["type"] == "human_decision" and e["checkpoint"] == "CP_CONTEXT" for e in run.prov.events())
    with pytest.raises(orch.Pause, match="CP_CONTEXT"):                 # another request needs its own approval
        run.agent("A09-WRI", {"text": "w" * 2000}, "A09-WRI_s2")


def test_the_hard_admission_ceiling_is_unchanged():
    """Admission still uses the byte bound against the full window, whatever the warning thresholds say."""
    m = model("test-model")
    payload = {"text": "q" * 20000}
    lenient = cfg_with(5000, default={"warn": 0.98, "review": 0.99})
    a = assess("A09-WRI", payload, m, lenient["admission"], {})
    assert a["fits"] is False and a["input_bound"] + a["output_reserve"] > a["window"]
    with pytest.raises(AdmissionRefused, match="no context window"):
        assess("A09-WRI", payload, model("no-such-model"), lenient["admission"], {})


# ------------------------------------------------------------------ the spend review point (CP_SPEND)
def test_spend_review_point_pauses_once_and_the_cap_does_not_move(tmp_path, monkeypatch):
    run, calls = _run(tmp_path, monkeypatch, 10 ** 6, routed="claude-opus-5")     # priced: $5 / $25 per M
    run.cfg = {**run.cfg, "run": {**run.cfg["run"], "spend_review_usd": 25.00}}
    assert CFG["run"]["spend_review_usd"] == 25.00 and CFG["run"]["spend_cap_usd"] == 35.00
    run.budget.record("A05-KE", "anthropic", "claude-sonnet-5-5", 1_000_000, 0, step="earlier")   # $2 spent
    run.budget.reserve("held", 22.50, "A07-SYN")                                                 # $22.50 held
    run.agent("A09-WRI", {"text": "a"}, "A09-WRI_ok")                         # worst case keeps it under $25
    assert calls == ["A09-WRI_ok"]
    with pytest.raises(orch.Pause, match="CP_SPEND"):
        run.agent("A09-WRI", {"text": "b" * 400_000}, "A09-WRI_big")         # would pass $25: stops first
    assert calls == ["A09-WRI_ok"]
    review = events(run, "spend_review_point")[-1]
    assert review["committed_after_usd"] > 25.00 and review["cap_usd"] == 35.00
    d = checkpoints.cp_dir(run.dir)
    decision = json.loads((d / "CP_SPEND_decision.json").read_text(encoding="utf-8"))
    decision["approve_continue"] = True
    (d / "CP_SPEND_decision.json").write_text(json.dumps(decision), encoding="utf-8")
    checkpoints.approve(run.dir, "CP_SPEND", run.prov)
    run.agent("A09-WRI", {"text": "b" * 400_000}, "A09-WRI_big")
    run.agent("A09-WRI", {"text": "c" * 400_000}, "A09-WRI_big2")             # approved once for this point
    assert calls[-2:] == ["A09-WRI_big", "A09-WRI_big2"] and run.budget.cap == 35.00
    assert any(e["type"] == "human_decision" and e["checkpoint"] == "CP_SPEND" for e in run.prov.events())


def test_a_reserved_call_counts_its_reservation_toward_the_review_point(tmp_path, monkeypatch):
    run, calls = _run(tmp_path, monkeypatch, 10 ** 6, routed="claude-opus-5")
    run.cfg = {**run.cfg, "run": {**run.cfg["run"], "spend_review_usd": 25.00}}
    run.budget.reserve("a09-key", 25.50, "A09-WRI")
    with pytest.raises(orch.Pause, match="CP_SPEND"):
        run.agent("A09-WRI", {"text": "d"}, "A09-WRI_r", reservation_key="a09-key")
    assert calls == []
