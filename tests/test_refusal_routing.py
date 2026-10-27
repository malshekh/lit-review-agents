from types import SimpleNamespace as NS

import pytest

from litreview import config, model_record
from litreview import orchestrator as orch
from litreview.agents import base as agent_base
from litreview.budget import BudgetTracker
from litreview.llm import anthropic_client as ac
from litreview.llm import openai_compatible as oc
from litreview.llm.base import LLMResponse
from litreview.provenance import ProvenanceLog


class _Stream:
    def __init__(self, resp):
        self.resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.resp


def _anthropic(resp, sent):
    return lambda: NS(messages=NS(stream=lambda **kw: sent.update(kw) or _Stream(resp)))


def test_anthropic_no_fallback_effort_and_cache_usage(monkeypatch):
    sent = {}
    resp = NS(content=[NS(type="text", text="{}")], stop_reason="end_turn", stop_details=None,
              usage=NS(input_tokens=100, output_tokens=50, cache_read_input_tokens=900, cache_creation_input_tokens=40))
    monkeypatch.setattr(ac, "_get_client", _anthropic(resp, sent))
    r = ac.complete(system="s", user="u", model="claude-opus-5", max_tokens=10, temperature=0, effort="high")
    assert "fallbacks" not in sent and "betas" not in sent and sent["output_config"] == {"effort": "high"}
    assert (r.input_tokens, r.cached_input_tokens, r.cache_write_tokens) == (100, 900, 40)


def test_anthropic_refusal(monkeypatch):
    resp = NS(content=[], stop_reason="refusal", stop_details=NS(category="bio"),
              usage=NS(input_tokens=5, output_tokens=0, cache_read_input_tokens=None, cache_creation_input_tokens=None))
    monkeypatch.setattr(ac, "_get_client", _anthropic(resp, {}))
    r = ac.complete(system="s", user="u", model="claude-opus-5-5", max_tokens=10, temperature=0)
    assert r.stop_reason == "refusal" and r.refusal_category == "bio" and r.cached_input_tokens == 0


@pytest.mark.parametrize("usage, expect", [
    (NS(prompt_tokens=1000, completion_tokens=10, prompt_tokens_details=NS(cached_tokens=600, cache_write_tokens=100)),
     (300, 600, 100)),                                                        # OpenAI
    (NS(prompt_tokens=1000, completion_tokens=10, prompt_tokens_details=None, cached_tokens=250), (750, 250, 0)),  # Kimi
])
def test_openai_compatible_cache_usage(monkeypatch, usage, expect):
    resp = NS(choices=[NS(message=NS(content="{}", refusal=None), finish_reason="stop")], usage=usage)
    monkeypatch.setattr(oc, "_get_client", lambda p: NS(chat=NS(completions=NS(create=lambda **kw: resp))))
    r = oc.complete(system="s", user="u", model="gpt-6.1-sol", max_tokens=10, temperature=0)
    assert (r.input_tokens, r.cached_input_tokens, r.cache_write_tokens) == expect


def test_openai_refusal_is_detected(monkeypatch):
    resp = NS(choices=[NS(message=NS(content=None, refusal="I can't help with that."), finish_reason="stop")],
              usage=NS(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None))
    monkeypatch.setattr(oc, "_get_client", lambda p: NS(chat=NS(completions=NS(create=lambda **kw: resp))))
    r = oc.complete(system="s", user="u", model="gpt-6.1-sol", max_tokens=10, temperature=0)
    assert r.stop_reason == "refusal" and "can't help" in r.refusal_category


def test_cache_pricing(tmp_path):
    b = BudgetTracker(tmp_path)
    # gpt-6-luna: input 0.10, cached 0.01, write 0.125 per M
    assert b.cost("gpt-6-luna", 1_000_000, 0, 1_000_000, 1_000_000) == pytest.approx(0.10 + 0.01 + 0.125)
    # verified Anthropic rates (pricing page, 2026-10-25): Sonnet 5.5 reads at 0.05x input = $0.10/M
    assert b.cost("claude-sonnet-5-5", 0, 0, 1_000_000, 0) == pytest.approx(0.10)
    # the live test call: 25 uncached, 10,629 read, 4 out on Sonnet 5.5
    assert b.cost("claude-sonnet-5-5", 25, 4, 10629) == pytest.approx(0.0010629 + 0.00005 + 0.00004)  # $0.00115
    # gpt-6-astra has no cache rates: reads billed at input, never undercounted
    assert b.cost("gpt-6-astra", 0, 0, 1_000_000, 0) == pytest.approx(10.00)
    assert b.missing_cache_rates("gpt-6-astra") == ["cached_input", "cache_write"]


def test_long_context_tier_applies_in_both_standard_and_batch_tables(tmp_path):
    """gpt-6.1-sol, pricing page 2026-10-27: over 272k prompt tokens every rate switches, batched or not."""
    b = BudgetTracker(tmp_path)
    assert b.cost("gpt-6.1-sol", 0, 0, 1_000_000, 0) == pytest.approx(0.20)       # cached read, long tier
    assert b.cost("gpt-6.1-sol", 200_000, 0, 0, 0) == pytest.approx(0.40)         # short: $2/M
    assert b.cost("gpt-6.1-sol", 300_000, 100_000) == pytest.approx(1.20 + 1.50)  # long: $4 / $15
    assert b.cost("gpt-6.1-sol", 200_000, 0, batch=True) == pytest.approx(0.20)   # batch short: $1/M
    assert b.cost("gpt-6.1-sol", 300_000, 100_000, batch=True) == pytest.approx(0.60 + 0.75)  # batch long: $2 / $7.50
    assert b.cost("claude-sonnet-5-5", 1_000_000, 1_000_000, 1_000_000, 0, 1_000_000, batch=True)         == pytest.approx(1.00 + 5.00 + 0.05 + 2.00)
    assert b.cost("gpt-6-luna", 1_000_000, 0, batch=True) == pytest.approx(0.10)   # no batch entry: standard rate
    e = b.record("A06-SV", "openai", "gpt-6.1-sol", 200_000, 0, "s", batch_id="batch_1")
    assert e["batch_id"] == "batch_1" and e["cost_usd"] == pytest.approx(0.20)


def test_one_hour_writes_priced_separately_and_never_undercounted(tmp_path):
    b = BudgetTracker(tmp_path)
    assert b.cost("claude-sonnet-5-5", 0, 0, 0, 0, 1_000_000) == pytest.approx(4.00)     # listed 1h rate
    assert b.cost("gpt-6-astra", 0, 0, 0, 0, 1_000_000) == pytest.approx(50.00)          # no rate: output, upper bound
    # Haiku above 100k tokens switches every rate, cache rates included
    assert b.cost("claude-haiku-5-5", 0, 0, 200_000, 0) == pytest.approx(200_000 * 0.05 / 1e6)


def test_cache_telemetry(tmp_path):
    b = BudgetTracker(tmp_path)
    w = b.record("A05-KE", "anthropic", "claude-sonnet-5-5", 25, 4, "s1", cache_write_tokens=10629)
    r = b.record("A05-KE", "anthropic", "claude-sonnet-5-5", 25, 4, "s2", cached_input_tokens=10629)
    assert not w["cache"]["hit"] and w["cache"]["seconds_since_previous_start"] is None
    assert r["cache"]["hit"] and 0 <= r["cache"]["seconds_since_previous_start"] < 60
    assert r["cache"]["effective_input_rate_per_m"] == pytest.approx((25 * 2 + 10629 * 0.10) / 10654, rel=1e-3)
    assert r["cache"]["list_input_rate_per_m"] == 2.00
    plain = b.record("A06-SV", "openai", "gpt-6.1-sol", 10, 10, "s3")
    assert "cache" not in plain
    assert "cache: 1/2 calls hit, 10,629 tokens read, 10,629 written" in b.summary_text()


def test_requested_cache_that_neither_read_nor_wrote_is_logged_as_a_miss(tmp_path):
    b = BudgetTracker(tmp_path)
    b.record("A05-KE", "anthropic", "claude-sonnet-5-5", 25, 4, "s1", cached_input_tokens=10629, cache_requested=True)
    dead = b.record("A05-KE", "anthropic", "claude-sonnet-5-5", 10654, 4, "s2", cache_requested=True)
    assert dead["cache"] == {**dead["cache"], "requested": True, "hit": False, "wrote": False}
    a = b.summary()["by_agent"]["A05-KE"]
    assert (a["cache_calls"], a["cache_hits"], a["cache_no_effect"]) == (2, 1, 1)
    assert "cache: 1/2 calls hit" in b.summary_text() and "1 requested but neither read nor wrote" in b.summary_text()
    assert "cache" not in b.record("A06-SV", "openai", "gpt-6.1-sol", 10, 10, "s3")   # not requested, nothing cached


def test_each_entry_and_the_summary_split_cost_by_token_class(tmp_path):
    b = BudgetTracker(tmp_path)
    e = b.record("A07-SYN", "anthropic", "claude-opus-5", 1_000_000, 1_000_000, "s1", cached_input_tokens=1_000_000,
                 cache_write_tokens=1_000_000, cache_write_1h_tokens=1_000_000, cache_requested=True)
    assert e["cost_parts_usd"] == {"input": 5.00, "cache_write": 16.25, "cache_read": 0.50, "output": 25.00}
    assert e["cost_usd"] == pytest.approx(sum(e["cost_parts_usd"].values()))
    with open(b.log_path, "a", encoding="utf-8") as fh:   # an entry logged before the split existed
        fh.write('{"agent": "A05-KE", "model": "m", "input_tokens": 1, "output_tokens": 1, "cost_usd": 1.0}\n')
    s = b.summary()
    assert s["cost_parts_usd"] == {"input": 5.0, "cache_write": 16.25, "cache_read": 0.5, "output": 25.0}
    assert s["calls_without_cost_parts"] == 1 and s["spent_usd"] == pytest.approx(47.75)
    assert "split: input $5.00, cache write $16.25, cache read $0.50, output $25.00  (+1 earlier" in b.summary_text()


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    r = orch.Run("t")
    r.save_state({"stage": "scope", "status": "READY", "counters": {}})
    (r.dir / "input").mkdir(parents=True, exist_ok=True)
    (r.dir / "input" / "topic_family.txt").write_text("onc", encoding="utf-8")
    return r


def test_refusal_fails_fast_is_recorded_and_reroutes(run, monkeypatch):
    calls = []

    def fake_complete(provider, **kw):
        calls.append(kw["model"])
        return LLMResponse("", "anthropic", kw["model"], 10, 0, "refusal", "bio")
    monkeypatch.setattr(agent_base, "complete", fake_complete)
    alt = config.AgentModel("A07-SYN", "anthropic", "claude-opus-5", 1000, 0.0)
    monkeypatch.setattr(config, "agent_candidates",
                        lambda a: [config.AgentModel(a, "anthropic", "claude-opus-5-5", 1000, 0.0), alt])
    with pytest.raises(agent_base.RefusalError, match="category: bio"):
        run.agent("A07-SYN", {"x": 1}, "A07-SYN_v1")
    assert calls == ["claude-opus-5-5"]                                    # one call, no retry
    assert model_record.refused("onc") == {"claude-opus-5-5": "bio"}
    assert run.route("A07-SYN").model == "claude-opus-5"                  # next call goes to the alternate
    assert run.route("A07-SYN").model == "claude-opus-5" and model_record.refused("other") == {}


def test_all_candidates_refused_stops_before_any_call(run, monkeypatch):
    model_record.add("claude-opus-5", "A07-SYN", "onc", "REFUSED", "old", "s", "bio")
    monkeypatch.setattr(config, "agent_candidates",
                        lambda a: [config.AgentModel(a, "anthropic", "claude-opus-5", 1000, 0.0)])
    monkeypatch.setattr(agent_base, "complete", lambda *a, **k: pytest.fail("must not call the API"))
    with pytest.raises(agent_base.AgentError, match="No qualified model for A07-SYN"):
        run.agent("A07-SYN", {}, "s")


def test_dead_end_names_every_model_tried_and_is_recorded_once(run, monkeypatch):
    model_record.add("claude-opus-5", "A07-SYN", "onc", "REFUSED", "r1", "A07-SYN_job_PLAN", "bio")
    model_record.add("claude-sonnet-5-5", "A05-KE", "onc", "REFUSED", "r1", "A05-KE_R0007", "bio")
    model_record.add("claude-sonnet-5-5", "A05-KE", "onc", "REFUSED", "r2", "A05-KE_R0012", "bio")
    model_record.add("claude-sonnet-5-5", "A09-WRI", "onc", "REFUSED", "r2", "A09-WRI_draft1", None)
    with pytest.raises(orch.NoQualifiedModel) as e:
        run.route("A07-SYN")
    msg = str(e.value)
    assert "No qualified model for A07-SYN in topic family 'onc'" in msg
    assert "- claude-opus-5: refused at A07-SYN (bio), 1x, first in run r1 step A07-SYN_job_PLAN" in msg
    assert ("- claude-sonnet-5-5: refused at A05-KE (bio), 2x, first in run r1 step A05-KE_R0007; "
            "refused at A09-WRI (category not returned), 1x" in msg)
    assert msg.index("claude-opus-5:") < msg.index("claude-sonnet-5-5:")   # routing order
    with pytest.raises(orch.NoQualifiedModel):
        run.route("A07-SYN")
    dead = [x for x in model_record.entries() if x["outcome"] == "NO_QUALIFIED_MODEL"]
    assert len(dead) == 1 and dead[0]["agent"] == "A07-SYN" and "claude-sonnet-5-5" in dead[0]["note"]
    assert model_record.blocked() == {"onc": ["A07-SYN"]}
    assert "(none)" not in model_record.summary()["onc"]                # dead ends are not a model's calls
    assert model_record.refusals("onc")["claude-sonnet-5-5"][0]["agent"] == "A05-KE"   # agent kept per refusal


def test_preflight_stops_a_new_run_before_any_spending(run, monkeypatch):
    model_record.add("claude-opus-5", "A07-SYN", "onc", "REFUSED", "r1", "s", "bio")
    model_record.add("claude-sonnet-5-5", "A05-KE", "onc", "REFUSED", "r1", "s", "bio")
    monkeypatch.setattr(orch, "run_agent", lambda *a, **k: pytest.fail("must not call any agent"))
    monkeypatch.setattr(orch.notify, "send", lambda *a, **k: None)
    status = run.run()
    assert status.startswith("FAILED: No qualified model for A05-KE")    # first blocked agent in pipeline order
    assert run.state()["stage"] == "scope"


def test_preflight_ignores_agents_whose_stages_are_done(run):
    model_record.add("claude-haiku-5-5", "A04-CQ", "onc", "REFUSED", "r1", "s", "bio")
    model_record.add("gpt-6-luna", "A04-CQ", "onc", "REFUSED", "r1", "s", "bio")
    with pytest.raises(orch.NoQualifiedModel, match="A04-CQ"):
        run.preflight_routing()
    run.save_state({"stage": "synthesize", "status": "READY", "counters": {}})
    run.preflight_routing()                                                 # screening is behind this run


def test_completed_call_is_recorded(run, monkeypatch, tmp_path):
    monkeypatch.setattr(orch, "run_agent", lambda *a, **k: {"ok": True})
    run.agent("A02-SP", {}, "A02-SP_scope_v1")
    e = model_record.entries(tmp_path / "model_record.jsonl")[-1]
    assert (e["agent"], e["family"], e["outcome"], e["model"]) == ("A02-SP", "onc", "COMPLETED", "gpt-6.1-sol")


def test_agent_candidates_reads_alternates(monkeypatch):
    real = config.load("pipeline")
    monkeypatch.setattr(config, "load", lambda n: {**real, "routing": {"alternates": {
        "A07-SYN": [{"provider": "anthropic", "model": "claude_strong", "effort": "medium"}]}}} if n == "pipeline" else real)
    c = config.agent_candidates("A07-SYN")
    assert [m.model for m in c] == ["claude-opus-5", "claude-opus-5-5"] and c[1].effort == "medium"
    assert c[1].max_tokens == c[0].max_tokens


def test_run_agent_raises_refusal_without_retry(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(agent_base, "complete",
                        lambda provider, **kw: calls.append(1) or LLMResponse("", "anthropic", kw["model"], 1, 0, "refusal", "bio"))
    with pytest.raises(agent_base.RefusalError):
        agent_base.run_agent("A07-SYN", {}, tmp_path, "s", BudgetTracker(tmp_path), ProvenanceLog(tmp_path))
    assert len(calls) == 1


def test_user_parts_put_cached_keys_first():
    parts = agent_base.user_parts({"review_spec": {"a": 1}, "content_level": "FULL_TEXT", "record": {"r": 2},
                                   "defects": [1]}, ("review_spec", "record"))
    assert [p["cache"] for p in parts] == [True, False]
    assert parts[0]["text"].endswith('{"review_spec":{"a":1},"record":{"r":2}}')
    assert '"content_level":"FULL_TEXT"' in parts[1]["text"] and '"defects":[1]' in parts[1]["text"]
    assert agent_base.user_parts({"x": 1}) == [{"text": '{"x":1}', "cache": False}]


def test_anthropic_cache_markers(monkeypatch):
    sent = {}
    resp = NS(content=[NS(type="text", text="{}")], stop_reason="end_turn", stop_details=None,
              usage=NS(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0))
    monkeypatch.setattr(ac, "_get_client", _anthropic(resp, sent))
    ac.complete(system="SYS", user=[{"text": "paper", "cache": True}, {"text": "rest", "cache": False}],
                model="claude-sonnet-5-5", max_tokens=10, temperature=0, cache_system=True)
    assert sent["system"] == [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]
    assert [("cache_control" in b) for b in sent["messages"][0]["content"]] == [True, False]
    ac.complete(system="SYS", user="plain", model="claude-sonnet-5-5", max_tokens=10, temperature=0)
    assert sent["system"] == "SYS" and "cache_control" not in sent["messages"][0]["content"][0]


def test_json_repair_keeps_cached_prefix_identical(monkeypatch, tmp_path):
    seen = []
    replies = iter(["not json", '{"agent_id": "A05-KE"}'])
    monkeypatch.setattr(agent_base, "complete", lambda provider, **kw: seen.append(kw["user"]) or
                        LLMResponse(next(replies), "anthropic", kw["model"], 1, 1, "end_turn"))
    monkeypatch.setattr(agent_base, "validate", lambda a, o, s=None: None)
    m = config.AgentModel("A05-KE", "anthropic", "claude-sonnet-5-5", 100, 0.0, cache_system=True,
                          cache_payload=("record",))
    agent_base.run_agent("A05-KE", {"record": {"r": 1}, "other": 2}, tmp_path, "s",
                         BudgetTracker(tmp_path), ProvenanceLog(tmp_path), model=m)
    assert seen[1][:2] == seen[0] and len(seen[1]) == 3 and not seen[1][2]["cache"]


def test_openai_joins_blocks(monkeypatch):
    sent = {}
    resp = NS(choices=[NS(message=NS(content="{}", refusal=None), finish_reason="stop")],
              usage=NS(prompt_tokens=1, completion_tokens=1, prompt_tokens_details=None))
    monkeypatch.setattr(oc, "_get_client", lambda p: NS(chat=NS(completions=NS(create=lambda **kw: sent.update(kw) or resp))))
    oc.complete(system="s", user=[{"text": "A", "cache": True}, {"text": "B", "cache": False}],
                model="gpt-6-luna", max_tokens=10, temperature=0, cache_system=True)
    assert sent["messages"][1]["content"] == "A\n\nB"


def test_model_record_is_tracked_and_a_legacy_record_migrates_once(tmp_path, monkeypatch):
    from litreview.paths import RECORDS_DIR, REPO_ROOT
    assert model_record.DEFAULT_RECORD == RECORDS_DIR / "model_record.jsonl"
    assert "records" not in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    new, old = tmp_path / "records" / "model_record.jsonl", tmp_path / "runs" / "model_record.jsonl"
    monkeypatch.setattr(model_record, "RECORD", new)
    monkeypatch.setattr(model_record, "DEFAULT_RECORD", new)
    monkeypatch.setattr(model_record, "LEGACY", old)
    model_record.add("m1", "A04-CQ", "onc", "COMPLETED", "r1", "s")
    shared = new.read_text(encoding="utf-8")
    old.parent.mkdir()
    old.write_text(shared + '{"model": "m2", "family": "onc", "outcome": "REFUSED", "category": "bio"}\n',
                   encoding="utf-8")
    assert model_record.refused("onc") == {"m2": "bio"}            # migrated on first read
    assert len(model_record.entries()) == 2                         # the shared line is not duplicated
    assert not old.exists() and old.with_name("model_record.jsonl.migrated").exists()
    with open(new, "a", encoding="utf-8") as fh:                      # what a union merge can leave behind
        fh.write(shared)
    assert len(model_record.entries()) == 2 and model_record.summary()["onc"]["m1"]["COMPLETED"] == 1


def test_costly_alternate_stops_and_asks_before_any_call(run, monkeypatch):
    """A05 on Opus 5 after a Sonnet 5.5 refusal: priced from this run's own A05 calls, then approved once."""
    for i in range(3):   # A05's real profile: cached system prompt, uncached paper, long output
        run.budget.record("A05-KE", "anthropic", "claude-sonnet-5-5", 30_000, 12_000, f"p{i}",
                          cached_input_tokens=10_600, cache_requested=True)
    model_record.add("claude-sonnet-5-5", "A05-KE", "onc", "REFUSED", "t", "p3", "bio")
    monkeypatch.setattr(agent_base, "complete", lambda *a, **k: pytest.fail("must not call the API"))
    with pytest.raises(orch.Pause, match=r"A05-KE: .*claude-opus-5 would cost 2\.5\dx as much .*approve-alternate t A05-KE"):
        run.agent("A05-KE", {}, "p3")
    pending = run.load("alternate_pending.json")
    assert pending["estimate"]["basis"] == "this run's 3 A05-KE calls on claude-sonnet-5-5"
    assert pending["estimate"]["per_call_alternate_usd"] > 2.5 * pending["estimate"]["per_call_primary_usd"]
    run.approve_alternate("A05-KE")
    assert run.route("A05-KE").model == "claude-opus-5"                     # consent holds for this run
    ev = [e for e in run.prov.events() if e["type"] == "human_decision"][-1]
    assert ev["checkpoint"] == "ALTERNATE_COST" and ev["decision"]["alternate"] == "claude-opus-5"
    with pytest.raises(ValueError):
        run.approve_alternate("A05-KE")                                     # nothing pending any more


def test_cheaper_or_equal_alternates_route_without_asking(run):
    (run.dir / "input" / "topic_family.txt").write_text("other", encoding="utf-8")
    model_record.add("claude-sonnet-5-5", "A12-EDI", "other", "REFUSED", "t", "s", "bio")
    with pytest.raises(orch.Pause, match=r"largest rate ratio"):          # no A12 calls yet: upper bound
        run.route("A12-EDI")
    (run.dir / "input" / "topic_family.txt").write_text("onc", encoding="utf-8")
    model_record.add("claude-opus-5", "A07-SYN", "onc", "REFUSED", "t", "s", "bio")
    model_record.add("gpt-6.1-sol", "A06-SV", "onc", "REFUSED", "t", "s", "cyber")
    assert run.route("A07-SYN").model == "claude-sonnet-5-5"               # cheaper: no question
    assert run.route("A06-SV").model == "kimi-k3.1-pro"                    # same price: no question


def test_provenance_summary_names_every_model_and_flags_mixed_agents(run):
    run.prov.agent_call("A07-SYN", "j_PLAN", "claude-opus-5", "0.6", "o", "OK")
    run.prov.agent_call("A07-SYN", "j_GROUP_G2", "claude-opus-5", "0.6", "", "REFUSED")
    run.prov.agent_call("A07-SYN", "j_GROUP_G2", "claude-sonnet-5-5", "0.6", "o", "OK")
    run.prov.agent_call("A05-KE", "p1", "claude-sonnet-5-5", "0.4", "o", "OK")
    run.prov.tool_run("synthesis_job", "j", {"models_by_turn": {"PLAN": "claude-opus-5", "GROUP_G2": "claude-sonnet-5-5"}})
    s = run._provenance_summary()
    assert s["models_by_agent"]["A07-SYN"] == {"claude-opus-5": 1, "claude-sonnet-5-5": 1}
    assert s["mixed_model_agents"] == ["A07-SYN"] and s["synthesis_models_by_turn"]["GROUP_G2"] == "claude-sonnet-5-5"
    assert s["refusals"] == [{"agent": "A07-SYN", "model": "claude-opus-5", "step": "j_GROUP_G2"}]
