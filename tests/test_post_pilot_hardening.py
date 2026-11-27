"""Post-pilot reliability and price controls: preflight, profiles, price gate, receipts, reservations, effort,
repair import and the batch paths."""
import datetime
import json
from types import SimpleNamespace as NS

import pytest

from litreview import budget as budget_mod
from litreview import config, model_record, preflight
from litreview import orchestrator as orch
from litreview.agents import base as agent_base
from litreview.budget import BudgetExceeded, BudgetTracker, StageCapReached, StalePrice
from litreview.llm import openai_compatible as oc
from litreview.llm.base import LLMResponse


# ------------------------------------------------------------------------------ preflight (item 9)
@pytest.mark.parametrize("name", ["ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "OPENAI_BASE_URL"])
def test_pipeline_refuses_to_start_when_a_provider_endpoint_is_redirected(name, tmp_path, monkeypatch):
    monkeypatch.setenv(name, "https://api.moonshot.ai/anthropic")
    with pytest.raises(preflight.PreflightRefused, match=name):
        preflight.require_start()
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    run = orch.Run("t")
    run.save_state({"stage": "scope", "status": "READY", "counters": {}})
    with pytest.raises(preflight.PreflightRefused):
        run.run()
    assert run.state()["status"] == "READY" and not run.budget.entries()      # nothing started
    from litreview import cli
    assert cli.main(["run", "t"]) == 2                                          # the CLI reports it, exit code 2
    assert cli.main(["status", "t"]) == 0                                       # reading is still allowed


def test_clients_never_build_on_a_redirected_endpoint_and_pin_their_own(monkeypatch):
    from litreview.llm import anthropic_client
    monkeypatch.setattr(anthropic_client, "_client", None)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "kimi-token")
    with pytest.raises(preflight.PreflightRefused):
        anthropic_client._get_client()
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert str(anthropic_client._get_client().base_url).rstrip("/") == "https://api.anthropic.com"
    monkeypatch.setattr(anthropic_client, "_client", None)
    monkeypatch.setattr(oc, "_clients", {})
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MOONSHOT_API_KEY", "test-key")
    assert str(oc._get_client("openai").base_url).rstrip("/") == "https://api.openai.com/v1"
    assert "moonshot" in str(oc._get_client("kimi").base_url)
    monkeypatch.setattr(oc, "_clients", {})


def test_a_whitespace_only_variable_is_not_a_redirect():
    assert preflight.endpoint_problems({"ANTHROPIC_BASE_URL": "  "}) == []


# ------------------------------------------------------------------- archive guard (item 29)
def test_nothing_inside_an_archived_pilot_runs_or_is_imported(tmp_path, monkeypatch):
    archive = tmp_path / "archive" / "pilot-2026-11"
    run_dir = archive / "v10" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (archive / preflight.ARCHIVE_MARKER).write_text(json.dumps({"closeout": "PILOT_CLOSEOUT.md"}), encoding="utf-8")
    assert preflight.archived_root(run_dir) == archive.resolve() and preflight.archived_root(tmp_path) is None
    with pytest.raises(preflight.PreflightRefused, match="archived pilot"):
        preflight.require_start(run_dir)
    monkeypatch.setattr(orch, "RUNS_DIR", archive / "v10" / "runs")
    run = orch.Run("r1")
    run.save_state({"stage": "scope", "status": "READY", "counters": {}})
    with pytest.raises(preflight.PreflightRefused):
        run.run()
    from litreview.repair_import import ImportRefused, import_output
    with pytest.raises(ImportRefused, match="archived pilot"):
        import_output(run, "s", "A05-KE", tmp_path / "x.json", "May", "reason")


# ---------------------------------------------------------------- price table and gate (item 32)
def test_every_price_entry_has_a_source_and_a_check_date_and_no_other_table_exists():
    prices = config.load("prices")
    for model, p in prices.items():
        assert p.get("source", "").startswith("https://") and datetime.date.fromisoformat(str(p["checked"])), model
        if not model.startswith("_"):
            assert p.get("input") is not None and p.get("output") is not None, model
    used = {m.model for a in config.load("pipeline")["agents"] for m in config.agent_candidates(a)}
    assert used <= set(prices)
    assert "gpt-5-mini" not in json.dumps(config.load("pipeline")) and "gpt-5-mini" not in prices   # shutdown 2026-12-11
    for model in ("gpt-6.1-sol-batch", "claude-sonnet-5-5-batch", "claude-opus-5-batch"):
        assert prices[model]["input"] == prices[model.removesuffix("-batch")]["input"] / 2


def test_no_price_is_hard_coded_in_the_package():
    """prices.yaml is the only price table: no source file states a per-million rate as a number."""
    import re
    from litreview.paths import REPO_ROOT
    rate = re.compile(r"(?<![\w.])(?:rates?|price|cost)\w*\s*=\s*\{[^}]*\"(?:input|output)\"\s*:\s*\d")
    offenders = [str(f.relative_to(REPO_ROOT)) for f in (REPO_ROOT / "src").rglob("*.py")
                 if rate.search(f.read_text(encoding="utf-8"))]
    assert offenders == []


def test_a_price_older_than_30_days_refuses_the_model(tmp_path, monkeypatch):
    b = BudgetTracker(tmp_path)
    b.check_priced("claude-opus-5")                                   # checked 2026-11-23: within 30 days
    b.check_priced("kimi-k3.1-pro")                                   # verified by the researcher 2026-11-23
    with pytest.raises(StalePrice, match=r"kimi-k3'.*last checked 2026-10-16 \(38 days ago; limit 30\)"):
        b.check_priced("kimi-k3")                                     # not re-verified: refused before any call
    assert preflight.price_problems() == []                          # every model an agent can route to is current
    monkeypatch.setenv("LITREVIEW_TEST_TODAY", "2026-12-24")
    with pytest.raises(StalePrice, match="31 days ago"):
        b.check_priced("claude-opus-5")
    assert budget_mod.price_problem({"m": {"input": 1, "output": 2}}, "m", 30) == \
        "'m' in config/prices.yaml has no source or checked date"
    assert b.cost("kimi-k3.1-pro", 0, 0, 0, 1_000_000, 1_000_000) == pytest.approx(2.00 + 4.00)   # 5-minute and 1-hour writes


# -------------------------------------------------------------------------- profiles (item 34)
def test_profiles_set_cap_review_points_and_stage_caps(tmp_path, monkeypatch):
    pilot = config.run_settings()
    assert (pilot["profile"], pilot["spend_cap_usd"], pilot["spend_review_points_usd"]) == ("pilot", 35.0, [25.0])
    run_block = config.load("pipeline")["run"]
    assert (run_block["spend_cap_usd"], run_block["spend_review_usd"]) == (35.0, 25.0)   # the staged pilot reads these
    ms = config.run_settings("manuscript")
    assert (ms["target_usd"], ms["spend_review_points_usd"], ms["spend_cap_usd"]) == (150.0, [120.0, 150.0], 200.0)
    assert ms["stage_caps_usd"] == "derived"                         # sub-caps come from the run's own projection at CP2
    assert config.run_settings("sample")["non_representative"] is True
    with pytest.raises(ValueError, match="Unknown spend profile 'big'"):
        config.run_settings("big")
    (tmp_path / "state.json").write_text(json.dumps({"profile": "manuscript"}), encoding="utf-8")
    monkeypatch.setenv("LITREVIEW_PROFILE", "pilot")                 # the run's recorded profile wins over the shell
    b = BudgetTracker(tmp_path)
    assert (b.profile, b.cap, b.review_points) == ("manuscript", 200.0, [120.0, 150.0])


def test_a_stage_cannot_borrow_from_a_later_stage(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"profile": "manuscript"}), encoding="utf-8")
    assert BudgetTracker(tmp_path).stage_caps == {}                                  # before CP2: no projection, no sub-caps
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "stage_caps.json").write_text(json.dumps({"caps_usd": {"A07": 30.0, "A08-A09": 20.0}}))
    b = BudgetTracker(tmp_path)
    b.record("A07-SYN", "anthropic", "claude-opus-5", 1_000_000, 900_000, "s1")      # $27.50 of the $30 A07 sub-cap
    assert b.reserve("k1", 2.0, "A07-SYN")[0]                                        # 29.50: fits
    with pytest.raises(StageCapReached, match=r"stage A07, over its \$30.00 sub-cap"):
        b.reserve("k2", 1.0, "A07-SYN")                                              # 30.50: stops, although $170 remain
    assert b.reserve("k3", 1.0, "A09-WRI")[0]                                        # another stage is unaffected
    assert isinstance(StageCapReached("x"), BudgetExceeded)


def test_spend_review_pauses_at_each_point_in_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(orch.notify, "send", lambda *a, **k: False)
    run = orch.Run("t")
    run.save_state({"stage": "draft", "status": "READY", "counters": {}, "profile": "manuscript"})
    run.budget = BudgetTracker(run.dir)
    paused = []
    monkeypatch.setattr(run, "pause_for_checkpoint", lambda cp: paused.append(cp))
    approved = set()
    monkeypatch.setattr(orch.checkpoints, "review_approved", lambda d, cp, digest: digest if digest in approved else None)
    written = []
    monkeypatch.setattr(orch.checkpoints, "write_spend_review", lambda d, digest, detail: written.append((digest, detail)))
    run.budget.record("A05-KE", "anthropic", "claude-opus-5", 10_000_000, 2_600_000, "s")   # $115
    run._spend_review("A07-SYN", "x", 1.0)
    assert paused == []                                                                     # 116 < 120
    run._spend_review("A07-SYN", "x", 6.0)
    assert paused == ["CP_SPEND"] and written[-1][1]["review_point_usd"] == 120.0
    approved.add(written[-1][0])
    run._spend_review("A07-SYN", "x", 6.0)
    assert paused == ["CP_SPEND"]                                                           # $120 approved: continues
    run._spend_review("A07-SYN", "x", 40.0)
    assert paused == ["CP_SPEND", "CP_SPEND"] and written[-1][1]["review_point_usd"] == 150.0   # the target is a second stop


# ----------------------------------------------------------- reasoning effort (items 21, 28)
def test_kimi_requests_carry_the_agents_reasoning_effort():
    """K3.1 Pro reasons at `max` when the field is omitted; the wrapper never sent it."""
    body = oc.chat_params("s", "u", "kimi-k3.1-pro", 16000, 0.3, provider="kimi", effort="high")
    assert body["reasoning_effort"] == "high" and "temperature" not in body
    a11 = config.agent_model("A11-RC")
    assert (a11.provider, a11.effort) == ("kimi", "high")
    allowed = config.load("pipeline")["providers"]["kimi"]["reasoning_effort"]["allowed"]
    assert a11.effort in allowed and "medium" not in allowed
    with pytest.raises(ValueError, match="does not accept reasoning effort 'medium'"):
        oc.chat_params("s", "u", "kimi-k3.1-pro", 16000, 0.3, provider="kimi", effort="medium")


def test_complete_and_batch_send_effort_and_temperature_is_never_sent(monkeypatch):
    sent = {}
    resp = NS(choices=[NS(message=NS(content="{}", refusal=None), finish_reason="stop")],
              usage=NS(prompt_tokens=1, completion_tokens=1, prompt_tokens_details=None))
    monkeypatch.setattr(oc, "_get_client", lambda p: NS(chat=NS(completions=NS(create=lambda **kw: sent.update(kw) or resp))))
    oc.complete(system="s", user="u", model="kimi-k3.1-pro", max_tokens=10, temperature=0.9, provider="kimi",
                effort="low", trace={"agent": "A11-RC"})
    assert sent["reasoning_effort"] == "low" and "temperature" not in sent and "trace" not in sent
    from litreview.llm import batch
    line = batch.request("openai", "c1", "s", "u", "gpt-6.1-sol", 10, 0.7, effort="medium")
    assert line["body"]["reasoning_effort"] == "medium" and "temperature" not in line["body"]
    for provider in ("anthropic", "openai", "kimi"):
        assert config.load("pipeline")["providers"][provider]["send_temperature"] is False
    assert not (orch.Path(oc.__file__).parent / "openai_client.py").exists()   # the unused wrapper that did send it


def test_every_agent_on_a_reasoning_provider_sets_an_effort_the_provider_accepts():
    providers = config.load("pipeline")["providers"]
    for agent in config.load("pipeline")["agents"]:
        for m in config.agent_candidates(agent):
            allowed = (providers[m.provider].get("reasoning_effort") or {}).get("allowed")
            if allowed and m.effort:
                assert m.effort in allowed, (agent, m.model, m.effort)
    assert config.agent_model("A11-RC").effort                      # Kimi never falls back to its `max` default
    reserve = config.load("pipeline")["admission"]["reasoning_reserve_tokens"]
    assert reserve["kimi"] == 32000    # kept: it is not established that Kimi counts reasoning inside the cap


def test_the_router_gives_every_provider_the_trace(monkeypatch):
    """The sample launcher decides by the trace which calls a route may serve; OpenAI calls arrived without one
    and were all refused."""
    from litreview.llm import router, tracing
    seen = {}
    monkeypatch.setattr(tracing, "traced_call", lambda fn, **k: fn())
    monkeypatch.setitem(router._PROVIDERS, "openai", lambda **kw: seen.update(kw) or "ok")
    assert router.complete("openai", trace={"agent": "A08-OL", "run_id": "r"}, system="s", user="u", model="m",
                           max_tokens=1, temperature=0) == "ok"
    assert seen["trace"] == {"agent": "A08-OL", "run_id": "r"}


# ------------------------------------------- reservations and receipts on the standard path (items 18, 25)
@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    monkeypatch.setattr(orch.notify, "send", lambda *a, **k: False)
    r = orch.Run("t")
    r.save_state({"stage": "extract", "status": "READY", "counters": {}})
    (r.dir / "input").mkdir(parents=True, exist_ok=True)
    (r.dir / "input" / "topic_family.txt").write_text("onc", encoding="utf-8")
    monkeypatch.setattr(r, "_context_check", lambda *a: {"input_counted": 100, "input_byte_bound": 100,
                                                         "output_reserve": 100, "step": a[2]})
    monkeypatch.setattr(r, "_context_actual", lambda *a: None)
    monkeypatch.setattr(agent_base, "validate", lambda a, o, s=None: None)
    monkeypatch.setattr(orch.corpus_policy, "resolve", lambda run: None)
    return r


def _model(monkeypatch, replies):
    calls, held = [], []
    it = iter(replies)

    def complete(provider, **kw):
        calls.append(kw)
        text, stop = next(it)
        return LLMResponse(text, provider, kw["model"], 100, 50, stop)
    monkeypatch.setattr(agent_base, "complete", complete)
    return calls, held


def test_every_send_is_reserved_first_and_released_after(run, monkeypatch):
    calls, _ = _model(monkeypatch, [('{"a": 1}', "end_turn")])
    seen = []
    reserve = run.budget.reserve
    monkeypatch.setattr(run.budget, "reserve", lambda key, usd, agent, note="": seen.append((key, usd, len(calls)))
                        or reserve(key, usd, agent, note))
    assert run.agent("A05-KE", {"x": 1}, "A05-KE_R0001") == {"a": 1}
    assert len(seen) == 1 and seen[0][2] == 0 and seen[0][1] > 0          # held before the provider was called
    assert run.budget.reservations() == {}                                # settled: nothing left held
    entry = run.budget.entries()[0]
    assert entry["reservation_key"] == seen[0][0]


def test_a_call_that_does_not_fit_is_refused_before_it_is_sent(run, monkeypatch):
    calls, _ = _model(monkeypatch, [('{"a": 1}', "end_turn")])
    run.budget.cap = 0.01
    with pytest.raises(BudgetExceeded, match="this call reserves"):
        run.agent("A05-KE", {"x": 1}, "A05-KE_R0001")
    assert calls == [] and run.budget.entries() == []


def test_a_truncation_retry_gets_its_own_larger_reservation(run, monkeypatch):
    calls, _ = _model(monkeypatch, [("{", "max_tokens"), ('{"a": 1}', "end_turn")])
    amounts = []
    reserve = run.budget.reserve
    monkeypatch.setattr(run.budget, "reserve", lambda key, usd, agent, note="": amounts.append(usd)
                        or reserve(key, usd, agent, note))
    assert run.agent("A05-KE", {"x": 1, "content_level": "ABSTRACT"}, "A05-KE_R0001") == {"a": 1}
    assert [c["max_tokens"] for c in calls] == [24000, 36000]             # the abstract cap, then 1.5x
    assert len(amounts) == 2 and amounts[1] > amounts[0] and run.budget.reservations() == {}


def test_a_resume_reuses_the_accepted_output_and_pays_nothing(run, monkeypatch):
    calls, _ = _model(monkeypatch, [('{"a": 1}', "end_turn"), ('{"a": 2}', "end_turn")])
    first = run.agent("A05-KE", {"x": 1}, "A05-KE_R0001")
    again = run.agent("A05-KE", {"x": 1}, "A05-KE_R0001")                 # same step, same request: the receipt
    assert first == again == {"a": 1} and len(calls) == 1 and len(run.budget.entries()) == 1
    assert run.agent("A05-KE", {"x": 2}, "A05-KE_R0001") == {"a": 2}      # a different request is a new call
    assert len(calls) == 2


def test_an_output_edited_after_acceptance_is_not_silently_reused(run, monkeypatch):
    _model(monkeypatch, [('{"a": 1}', "end_turn")])
    run.agent("A05-KE", {"x": 1}, "A05-KE_R0001")
    (run.dir / "outputs" / "A05-KE_R0001.json").write_text('{"a": 99}', encoding="utf-8")
    with pytest.raises(orch.Pause, match="no longer matches its receipt"):
        run.agent("A05-KE", {"x": 1}, "A05-KE_R0001")


# ----------------------------------------------------------------------- repair import (item 24)
def test_repair_import_validates_audits_and_is_used_without_a_second_payment(run, monkeypatch, tmp_path):
    from litreview.repair_import import ImportRefused, import_output
    import jsonschema

    def validate(agent, out, schema=None):
        if "mode" not in out:
            raise jsonschema.ValidationError("'mode' is a required property")
    monkeypatch.setattr(agent_base, "validate", validate)
    monkeypatch.setattr("litreview.repair_import.validate", validate)
    calls, _ = _model(monkeypatch, [('{"themes": ["T1"]}', "end_turn")])
    monkeypatch.setitem(run.cfg["loops"], "max_json_repair_attempts", 0)
    with pytest.raises(agent_base.AgentError, match="'mode' is a required property"):
        run.agent("A07-SYN", {"mode": "PLAN"}, "A07-SYN_PLAN")
    fixed = tmp_path / "fixed.json"
    fixed.write_text('{"themes": ["T1"]}', encoding="utf-8")
    with pytest.raises(ImportRefused, match="still fails the schema"):
        import_output(run, "A07-SYN_PLAN", "A07-SYN", fixed, "May Khalid", "added the mode key")
    fixed.write_text('{"themes": ["T1"], "mode": "PLAN"}', encoding="utf-8")
    with pytest.raises(ImportRefused, match="--by"):
        import_output(run, "A07-SYN_PLAN", "A07-SYN", fixed, "", "added the mode key")
    audit = import_output(run, "A07-SYN_PLAN", "A07-SYN", fixed, "May Khalid", "added the mode key")
    assert audit["changed_paths"] == ["$.mode (added)"] and audit["repaired_by"] == "May Khalid"
    decision = [e for e in run.prov.events() if e["type"] == "human_decision"][-1]
    assert decision["checkpoint"] == "REPAIR_IMPORT" and decision["actor"] == "HUMAN"
    out = run.agent("A07-SYN", {"mode": "PLAN"}, "A07-SYN_PLAN")          # the same request, after the import
    assert out == {"themes": ["T1"], "mode": "PLAN"} and len(calls) == 1 and len(run.budget.entries()) == 1
    with pytest.raises(ImportRefused, match="already has an accepted output"):
        import_output(run, "A07-SYN_PLAN", "A07-SYN", fixed, "May Khalid", "again")


def test_a_truncated_reply_cannot_be_completed_by_hand(run, monkeypatch, tmp_path):
    from litreview.repair_import import ImportRefused, import_output
    _model(monkeypatch, [("{", "max_tokens"), ("{", "max_tokens")])
    with pytest.raises(agent_base.AgentError, match="truncated"):
        run.agent("A05-KE", {"x": 1}, "A05-KE_R0001")
    f = tmp_path / "f.json"
    f.write_text("{}", encoding="utf-8")
    with pytest.raises(ImportRefused, match="truncated at its output cap"):
        import_output(run, "A05-KE_R0001", "A05-KE", f, "May", "finished it")
    with pytest.raises(ImportRefused, match="nothing to repair"):
        import_output(run, "A05-KE_R0002", "A05-KE", f, "May", "never ran")


# --------------------------------------------------------------- batch paths (items 16, 17, 26)
def test_batch_path_with_min_items_3(tmp_path, monkeypatch):
    """Config is back at min_items 3: two pending items after the probe run one by one; three go through a batch."""
    import test_batch_stage as tb
    from litreview import batch_stage
    assert config.load("pipeline")["batch"]["min_items"] == 3 and config.load("pipeline")["batch"]["enabled"] is True
    for n, batched in ((3, 0), (4, 3)):                                   # n items: 1 probe + (n - 1) pending
        monkeypatch.setattr(orch, "RUNS_DIR", tmp_path / str(n))
        monkeypatch.setattr(model_record, "RECORD", tmp_path / str(n) / "model_record.jsonl")
        monkeypatch.setattr(batch_stage, "validate", lambda *a, **k: None)
        monkeypatch.setattr(batch_stage.time, "sleep", lambda s: None)
        r = orch.Run("t")
        r.save_state({"stage": "extract", "status": "READY", "counters": {}})
        (r.dir / "input").mkdir(parents=True, exist_ok=True)
        (r.dir / "input" / "topic_family.txt").write_text("onc", encoding="utf-8")
        (r.dir / "outputs").mkdir(parents=True, exist_ok=True)
        fake, calls, got = tb.FakeVendor(), [], {}
        tb.install(monkeypatch, fake)
        tb.fake_interactive(monkeypatch, calls)
        steps = tb.STEPS[:n]
        r.run_many("A05-KE", tb.items(steps), lambda s, o: got.__setitem__(s, o))
        assert sorted(got) == sorted(steps)
        assert [len(b) for b in fake.created] == ([batched] if batched else [])
        assert len(calls) == n - batched and r.budget.reservations() == {}


def test_a_truncated_batch_item_keeps_its_reply_and_is_redone_at_a_larger_cap(tmp_path, monkeypatch):
    import test_batch_stage as tb
    from litreview import batch_stage
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    monkeypatch.setattr(batch_stage, "validate", lambda *a, **k: None)
    monkeypatch.setattr(batch_stage.time, "sleep", lambda s: None)
    r = orch.Run("t")
    r.save_state({"stage": "extract", "status": "READY", "counters": {}})
    (r.dir / "input").mkdir(parents=True, exist_ok=True)
    (r.dir / "input" / "topic_family.txt").write_text("onc", encoding="utf-8")
    (r.dir / "outputs").mkdir(parents=True, exist_ok=True)
    fake = tb.FakeVendor()
    tb.install(monkeypatch, fake)
    fake.outcome = {tb.STEPS[2]: "truncated", tb.STEPS[3]: "bad_json"}
    seen = []

    def run_agent(agent_id, payload, run_dir, step, budget, prov, model=None, schema_file=None, **kw):
        seen.append((step, model.max_tokens, kw.get("truncation_retries"), kw.get("repair_from")))
        out = {"status": "OK", "id": step}
        (orch.Path(run_dir) / "outputs" / f"{step}.json").write_text(json.dumps(out), encoding="utf-8")
        return out
    monkeypatch.setattr(orch, "run_agent", run_agent)
    got = {}
    r.run_many("A05-KE", tb.items(), lambda s, o: got.__setitem__(s, o))
    assert sorted(got) == sorted(tb.STEPS)
    redo = {s: (cap, retries, repair) for s, cap, retries, repair in seen}
    assert redo[tb.STEPS[2]][:2] == (72000 if False else min(int(48000 * 1.5), 64000), 0)   # one larger-cap retry
    assert redo[tb.STEPS[3]][2] is not None and redo[tb.STEPS[3]][2][0] == "{not json"       # repaired from its reply
    assert (r.dir / "outputs" / f"{tb.STEPS[2]}.batch.raw.txt").exists()                     # the paid reply is kept


# ------------------------------------------------- records, measurement and billing (items 30, 31, 33, 36, 46)
def test_a_refusal_stands_until_a_person_clears_it_and_a_new_one_stands_again(tmp_path, monkeypatch):
    rec = tmp_path / "model_record.jsonl"
    clock = iter(["2026-11-01T10:00:00", "2026-11-23T10:00:00", "2026-11-24T10:00:00"])
    monkeypatch.setattr(model_record.time, "strftime", lambda fmt: next(clock))
    model_record.add("claude-opus-5-5", "A07-SYN", "onc", "REFUSED", "r1", "s1", None, path=rec)
    assert model_record.refused("onc", rec) == {"claude-opus-5-5": "unspecified"}
    with pytest.raises(ValueError, match="who decided"):
        model_record.clear("claude-opus-5-5", "onc", "", "retest passed", path=rec)
    model_record.clear("claude-opus-5-5", "onc", "May Khalid", "one-mode retest of GROUP completed", path=rec)
    assert model_record.refused("onc", rec) == {} and model_record.refusals("onc", rec) == {}
    assert model_record.summary(rec)["onc"]["claude-opus-5-5"]["REFUSED"] == 1      # the history is kept
    model_record.add("claude-opus-5-5", "A09-WRI", "onc", "REFUSED", "r2", "s2", "bio", path=rec)
    assert model_record.refused("onc", rec) == {"claude-opus-5-5": "bio"}


def _cost_run(tmp_path, sample):
    d = tmp_path / ("sample" if sample else "full")
    (d / "outputs").mkdir(parents=True)
    (d / "input").mkdir()
    if sample:
        (d / "input" / "a07_a09_sample.json").write_text("{}", encoding="utf-8")
    rows = [("A07-SYN", "A07-SYN_jobx_GROUP_G0001", 5000), ("A07-SYN", "A07-SYN_jobx_GROUP_G0002", 7000),
            ("A07-SYN", "A07-SYN_jobx_GROUP_G0003", 6000), ("A07-SYN", "A07-SYN_jobx_GROUP_G0004", 16000),
            ("A09-WRI", "A09-WRI_S1", 9000), ("A05-KE", "A05-KE_R0001", 20000)]
    (d / "costs.jsonl").write_text("\n".join(json.dumps({"agent": a, "step": s, "output_tokens": o, "cost_usd": 0.1})
                                             for a, s, o in rows), encoding="utf-8")
    for _, s, _ in rows:
        (d / "outputs" / f"{s}.json").write_text("{}", encoding="utf-8")
    (d / "outputs" / "A07-SYN_jobx_GROUP_G0004.truncated0.json").write_text("{}", encoding="utf-8")
    return d


def test_output_shares_are_measured_from_completed_calls_and_never_from_a_sample(tmp_path):
    from litreview.tools import output_shares
    with pytest.raises(output_shares.NotRepresentative, match="NON-REPRESENTATIVE"):
        output_shares.measure(_cost_run(tmp_path, True))
    measured = output_shares.measure(_cost_run(tmp_path, False))
    assert measured["cells"]["A07-SYN.GROUP"] == {"calls": 3, "mean": 6000, "p90": 7000, "max": 7000}   # truncated call left out
    assert "A05-KE" not in str(measured["cells"])
    table = tmp_path / "output_shares.json"
    table.write_text(json.dumps({"expected_output_tokens": {"A07-SYN.GROUP": {"tokens": 1, "basis": "ASSUMED"},
                                                           "A09-WRI.A09_SECTION": {"tokens": 8000, "basis": "ASSUMED"}}}))
    assert output_shares.write(measured, table) == ["A07-SYN.GROUP"]            # one A09 call is not a measurement
    after = json.loads(table.read_text())["expected_output_tokens"]
    assert after["A07-SYN.GROUP"]["tokens"] == 7000 and after["A07-SYN.GROUP"]["basis"] == "MEASURED"
    assert after["A09-WRI.A09_SECTION"]["basis"] == "ASSUMED"


def test_the_forecast_no_longer_moves_with_the_output_caps_and_prices_the_real_theme_calls(tmp_path):
    from litreview.tools import forecast
    s = config.load("pipeline")["forecast"]["scenarios"]["baseline"]
    assert forecast.expected_output("A07-SYN.GROUP", 12000, s) == forecast.expected_output("A07-SYN.GROUP", 16000, s) == 6000
    assert forecast.expected_output("A07-SYN.GROUP", 16000, None) == 16000       # the strict worst case is the cap
    assert forecast.expected_output("NOT-RECORDED", 10000, s) == 10000 * s["output"]
    b = BudgetTracker(tmp_path)
    route = lambda a, ex=frozenset(): config.agent_candidates(a)[0]             # noqa: E731
    import copy
    unpaged = copy.deepcopy(config.load("pipeline"))
    unpaged["validation"]["theme_paging"]["enabled"] = False
    usd, calls, warnings = forecast.a06_themes(1581, 120, unpaged, b, route, s)
    assert calls == config.load("pipeline")["themes"]["primary_max"] + 1 == 9   # not 279 (papers x themes per paper)
    assert any("would truncate" in w for w in warnings) and any("long-context" in w for w in warnings)
    paged_usd, paged_calls, paged_warnings = forecast.a06_themes(1581, 120, config.load("pipeline"), b, route, s)
    assert paged_warnings == [] and paged_calls > 9 and paged_usd < usd       # packets plus one reconciliation per theme
    small, small_calls, quiet = forecast.a06_themes(300, 28, config.load("pipeline"), b, route, s)
    assert quiet == [] and small < paged_usd and small_calls == 9             # a theme that fits is one call


def test_billing_reconciliation_flags_a_gap_over_five_percent(tmp_path, capsys):
    import importlib.util
    from litreview.paths import REPO_ROOT
    spec = importlib.util.spec_from_file_location("reconcile_billing", REPO_ROOT / "scripts" / "reconcile_billing.py")
    rb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rb)
    rows = [{"provider": "anthropic", "model": "claude-opus-5", "cost_usd": 10.0, "started_at": 1795000000.0},
            {"provider": "openai", "model": "gpt-6.1-sol", "cost_usd": 4.0, "started_at": 1795003600.0},
            {"provider": "openai", "model": "gpt-6.1-sol", "cost_usd": None}]
    (tmp_path / "costs.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    (tmp_path / "reservations.json").write_text(json.dumps({"call-abc": {"usd": 0.4}}), encoding="utf-8")
    assert rb.main([str(tmp_path), "--billed", "anthropic=10.30", "openai=4.10"]) == 0          # 2.9% and 2.4%
    assert rb.main([str(tmp_path), "--billed", "anthropic=11.00", "openai=4.00"]) == 1          # 9.1% more billed
    out = capsys.readouterr().out
    assert "BILLED_MORE_THAN_LOGGED" in out and "reservation(s) still held" in out and "no price" in out
    report = json.loads((tmp_path / "billing_reconciliation.json").read_text())
    assert report["providers"][0]["gap_usd"] == 1.0 and report["held_reservations"] == {"call-abc": 0.4}
    assert rb.main([str(tmp_path)]) == 2                                                         # nothing to compare
    csv_file = tmp_path / "export.csv"
    csv_file.write_text("date,model,Cost (USD)\n2026-11-24,claude-opus-5,$6.00\n2026-11-24,claude-opus-5,3.90\n")
    assert rb.main([str(tmp_path), "--csv", f"anthropic={csv_file}", "--billed", "openai=4.0"]) == 0


def test_tests_directory_holds_no_script_that_can_reach_a_provider():
    """Scripts that count tokens or call a provider live in scripts/live/, never beside the tests CI collects."""
    from litreview.paths import REPO_ROOT
    risky = ("load_dotenv", ".count_tokens(")   # loading real keys, or calling a provider endpoint
    offenders = sorted(f.name for f in (REPO_ROOT / "tests").glob("*.py")
                       if f.name != "test_post_pilot_hardening.py" and any(r in f.read_text(encoding="utf-8") for r in risky))
    assert offenders == []
    assert {f.name for f in (REPO_ROOT / "scripts" / "live").glob("*.py")} >= {
        "a07_efficiency_report.py", "a07_validation_audit.py", "bridge_capacity_audit.py", "model_window_probe.py"}
    workflow = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY"):
        assert f'{key}: ""' in workflow


def test_tier_policy_limits_full_text_and_the_instability_retest_to_core(run):
    assert run.cfg["extraction"]["full_text_tiers"] == ["CORE"] and run.cfg["validation"]["instability_tiers"] == ["CORE"]
    assert run._tier_allows("extraction", "full_text_tiers", {"tier": "CORE"})
    assert not run._tier_allows("extraction", "full_text_tiers", {"tier": "SUPPORTING"})
    assert run._tier_allows("extraction", "missing_key", {"tier": "CONTEXT"})    # no policy: every paper


def test_batch_results_are_matched_by_request_id_not_by_returned_order(tmp_path, monkeypatch):
    """Providers may return batch results in any order (Anthropic says so explicitly), and a result can be missing.
    Each result must reach the step whose request it answers; a missing one is redone, never misattributed."""
    import test_batch_stage as tb
    from litreview import batch_stage
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    monkeypatch.setattr(batch_stage, "validate", lambda *a, **k: None)
    monkeypatch.setattr(batch_stage.time, "sleep", lambda s: None)
    r = orch.Run("t")
    r.save_state({"stage": "extract", "status": "READY", "counters": {}})
    (r.dir / "input").mkdir(parents=True, exist_ok=True)
    (r.dir / "input" / "topic_family.txt").write_text("onc", encoding="utf-8")
    (r.dir / "outputs").mkdir(parents=True, exist_ok=True)
    fake, calls, got = tb.FakeVendor(), [], {}
    tb.install(monkeypatch, fake)
    tb.fake_interactive(monkeypatch, calls)
    original = fake.results

    def shuffled(provider, bid, model):
        out = list(reversed(original(provider, bid, model)))
        return out[1:]                                                      # reversed, and one result never arrives
    monkeypatch.setattr(batch_stage.batch, "results", shuffled)
    r.run_many("A05-KE", tb.items(), lambda s, o: got.__setitem__(s, o))
    assert sorted(got) == sorted(tb.STEPS)
    assert all(out["id"] == step for step, out in got.items() if out.get("status") == "OK")   # each to its own step
    batched = [e["step"] for e in r.budget.entries() if e.get("batch_id")]
    assert len(batched) == len(set(batched)) == len(tb.STEPS) - 2          # probe + the missing one ran interactively


@pytest.fixture(autouse=True)
def _generic_transport_legacy_mode(monkeypatch):
    """These generic recovery/routing tests use tiny non-scientific JSON fixtures and exercise legacy retry policy.
    The ordinary canonical mode and its no-increase policy have dedicated nonempty integration tests.
    """
    from litreview import config as mode_config
    monkeypatch.setitem(mode_config.load('pipeline')['extraction'],'generation_mode','anthropic_strict_legacy')
