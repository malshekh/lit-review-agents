"""Batch stage: probe, projected-cost refusal, intent recovery, reattach, ingestion, refusals and repairs.
The vendor layer (litreview.llm.batch) is faked; requests are built by the real builders."""
import json

import pytest

from litreview import batch_stage, model_record
from litreview import orchestrator as orch
from litreview.agents import RefusalError
from litreview.budget import BudgetExceeded
from litreview.llm import batch as vendor
from litreview.llm.base import LLMResponse

STEPS = [f"A05-KE_R000{i}" for i in range(1, 6)]


class FakeVendor:
    """Records every create; serves scripted results per custom_id."""

    def __init__(self, outcome=None, recent=None):
        self.created, self.outcome, self.recent_rows = [], outcome or {}, recent or []

    def upload(self, provider, reqs):
        return "file-1" if provider == "openai" else None

    def create(self, provider, reqs, file_id):
        self.created.append([r["custom_id"] for r in reqs])
        return f"batch_{len(self.created)}"

    def status(self, provider, bid):
        return {"done": True, "status": "ended", "counts": {}}

    def results(self, provider, bid, model):
        out = []
        for cid in self.created[int(bid.split("_")[1]) - 1]:
            kind = self.outcome.get(cid, "ok")
            if kind in ("expired", "errored"):
                out.append(vendor.ItemResult(cid, kind, error=kind, retryable=kind == "expired"))
                continue
            text = {"ok": json.dumps({"status": "OK", "id": cid}), "bad_json": "{not json"}.get(kind, "")
            stop = {"refused": "refusal", "truncated": "max_tokens"}.get(kind, "end_turn")
            out.append(vendor.ItemResult(cid, "succeeded", LLMResponse(text, provider, model, 1000, 500, stop,
                                                                       "bio" if kind == "refused" else None)))
        return out

    def recent(self, provider, limit=20):
        return self.recent_rows


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    monkeypatch.setattr(batch_stage, "validate", lambda *a, **k: None)
    monkeypatch.setattr(batch_stage.time, "sleep", lambda s: None)
    r = orch.Run("t")
    r.save_state({"stage": "extract", "status": "READY", "counters": {}})
    (r.dir / "input").mkdir(parents=True, exist_ok=True)
    (r.dir / "input" / "topic_family.txt").write_text("onc", encoding="utf-8")
    (r.dir / "outputs").mkdir(parents=True, exist_ok=True)
    return r


def fake_interactive(monkeypatch, calls, refuse=()):
    def run_agent(agent_id, payload, run_dir, step, budget, prov, model=None, schema_file=None):
        calls.append((step, model.model))
        if step in refuse:
            raise RefusalError("declined", model.model, "bio")
        out = {"status": "OK", "id": step, "interactive": True}
        (run_dir / "outputs" / f"{step}.json").write_text(json.dumps(out), encoding="utf-8")
        return out
    monkeypatch.setattr(orch, "run_agent", run_agent)


def install(monkeypatch, fake):
    for name in ("upload", "create", "status", "results", "recent"):
        monkeypatch.setattr(batch_stage.batch, name, getattr(fake, name))


def items():
    return [(s, {"record": {"record_id": s[-5:]}, "content": "x" * 400}) for s in STEPS]


def test_probe_then_one_batch_logged_at_batch_rates(run, monkeypatch):
    fake, calls, got = FakeVendor(), [], {}
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, calls)
    run.run_many("A05-KE", items(), lambda s, o: got.__setitem__(s, o))
    assert calls == [(STEPS[0], "claude-sonnet-5-5")]                     # the probe: one real item, interactive
    assert fake.created == [STEPS[1:]]                                    # the rest: one batch
    assert sorted(got) == STEPS and got[STEPS[1]] == {"status": "OK", "id": STEPS[1]}
    entries = [e for e in run.budget.entries() if e.get("batch_id") == "batch_1"]
    assert len(entries) == 4 and entries[0]["cost_usd"] == pytest.approx((1000 * 1.00 + 500 * 5.00) / 1e6)
    rec = json.loads(run.data("batches/A05-KE.json").read_text())[0]
    assert rec["status"] == "INGESTED" and rec["succeeded"] == 4 and rec["estimate"]["projected_usd"] > 0
    assert sum(e["outcome"] == "COMPLETED" for e in model_record.entries()) == 5      # probe + 4 batched
    run.run_many("A05-KE", items(), lambda s, o: None)                    # rerun: outputs reused, nothing paid
    assert len(fake.created) == 1 and len(calls) == 1


def test_probe_refusal_submits_nothing(run, monkeypatch):
    fake, calls = FakeVendor(), []
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, calls, refuse={STEPS[0]})
    with pytest.raises(RefusalError):
        run.run_many("A05-KE", items(), lambda s, o: None)
    assert fake.created == [] and not run.data("batches/A05-KE.json").exists()
    assert model_record.refused("onc") == {"claude-sonnet-5-5": "bio"}


def test_projected_cost_over_the_remaining_cap_is_refused_not_asked(run, monkeypatch):
    fake, calls = FakeVendor(), []
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, calls)
    run.budget.cap = 0.50          # 4 items x 64k max output x $5/M = $1.28 projected
    with pytest.raises(BudgetExceeded, match="batch of 4 not submitted: projected"):
        run.run_many("A05-KE", items(), lambda s, o: None)
    assert fake.created == [] and not run.data("batches/A05-KE.json").exists()   # no intent, no batch


def _intent(run, **kw):
    run.data("batches").mkdir(parents=True, exist_ok=True)
    rec = {"intent_at": 1000.0, "status": "INTENT", "provider": "anthropic", "model": "claude-sonnet-5-5",
           "steps": STEPS[1:], "count": 4, "input_file_id": None, "batch_id": None, "estimate": {},
           "prompt_chars": {}, "ingested": [], "cache_requested": True, **kw}
    run.data("batches/A05-KE.json").write_text(json.dumps([rec]))


def test_crash_before_the_id_was_saved_reattaches_by_time_and_count(run, monkeypatch):
    fake, calls, got = FakeVendor(), [], {}
    fake.created = [STEPS[1:]]                                            # the batch the crashed run created
    fake.recent_rows = [{"id": "batch_1", "created_at": 1003.0, "total": 4, "input_file_id": None},
                        {"id": "other", "created_at": 1003.0, "total": 7, "input_file_id": None}]
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, calls)
    run.save("x.json", {})
    (run.dir / "outputs" / f"{STEPS[0]}.json").write_text('{"status": "OK"}')
    _intent(run)
    run.run_many("A05-KE", items(), lambda s, o: got.__setitem__(s, o))
    assert len(fake.created) == 1 and calls == [] and sorted(got) == STEPS   # recovered, not resubmitted
    assert json.loads(run.data("batches/A05-KE.json").read_text())[0]["batch_id"] == "batch_1"


def test_ambiguous_recovery_stops_and_no_match_means_never_created(run, monkeypatch):
    fake = FakeVendor(recent=[{"id": "a", "created_at": 1001.0, "total": 4, "input_file_id": None},
                              {"id": "b", "created_at": 1002.0, "total": 4, "input_file_id": None}])
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, [])
    _intent(run)
    with pytest.raises(orch.Pause, match="cannot tell which batch"):
        run.run_many("A05-KE", items(), lambda s, o: None)
    fake.recent_rows = []
    run.run_many("A05-KE", items(), lambda s, o: None)
    recs = json.loads(run.data("batches/A05-KE.json").read_text())
    assert recs[0]["status"] == "NOT_CREATED" and recs[1]["status"] == "INGESTED"


def test_openai_recovery_matches_the_uploaded_input_file(run, monkeypatch):
    fake = FakeVendor(recent=[{"id": "batch_9", "created_at": 9999.0, "total": 0, "input_file_id": "file-1"}])
    install(monkeypatch, fake)
    _intent(run, provider="openai", input_file_id="file-1")
    stage = batch_stage.BatchStage(run, "A06-SV", [], lambda s, o: None)
    assert stage._recover(json.loads(run.data("batches/A05-KE.json").read_text())[0]) == "batch_9"


def test_interrupted_ingestion_never_logs_a_cost_twice(run, monkeypatch):
    fake, calls = FakeVendor(), []
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, calls)
    run.run_many("A05-KE", items(), lambda s, o: None)
    rec = json.loads(run.data("batches/A05-KE.json").read_text())[0]
    rec.update(status="SUBMITTED", ingested=[])                           # as if the process died mid-ingestion
    run.data("batches/A05-KE.json").write_text(json.dumps([rec]))
    for s in STEPS[1:]:
        (run.dir / "outputs" / f"{s}.json").unlink()
    run.run_many("A05-KE", items(), lambda s, o: None)
    assert len([e for e in run.budget.entries() if e.get("batch_id")]) == 4 and len(fake.created) == 1


def test_failures_repair_interactively_expired_items_are_resubmitted(run, monkeypatch):
    fake, calls = FakeVendor({STEPS[1]: "bad_json", STEPS[2]: "truncated", STEPS[3]: "expired",
                              STEPS[4]: "expired"}), []
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, calls)
    monkeypatch.setitem(run.cfg["batch"], "min_items", 2)
    original = fake.results

    def results(provider, bid, model):   # the resubmitted batch succeeds
        if bid != "batch_1":
            fake.outcome = {}
        return original(provider, bid, model)
    monkeypatch.setattr(batch_stage.batch, "results", results)
    run.run_many("A05-KE", items(), lambda s, o: None)
    assert [s for s, _ in calls] == [STEPS[0], STEPS[1], STEPS[2]]        # probe + two interactive repairs
    assert fake.created == [STEPS[1:], [STEPS[3], STEPS[4]]]              # expired items: a second batch, no probe


def test_refusals_inside_a_batch_route_to_the_alternate_as_a_mixed_model_stage(run, monkeypatch):
    fake, calls = FakeVendor({STEPS[2]: "refused", STEPS[3]: "refused"}), []
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, calls)
    run.save_state({"stage": "validate", "status": "READY", "counters": {}})
    steps = [s.replace("A05-KE", "A06-SV") for s in STEPS]
    fake.outcome = {steps[2]: "refused", steps[3]: "refused"}
    with pytest.raises(orch.Pause, match="kimi-k3.1-pro would cost 2.0x"):   # Kimi has no batch: full price
        run.run_many("A06-SV", [(s, {"x": 1}) for s in steps], lambda s, o: None)
    assert model_record.refused("onc") == {"gpt-6.1-sol": "bio"}
    run.approve_alternate("A06-SV")
    run.run_many("A06-SV", [(s, {"x": 1}) for s in steps], lambda s, o: None)
    assert calls[1:] == [(steps[2], "kimi-k3.1-pro"), (steps[3], "kimi-k3.1-pro")]   # alternate (no batch: Kimi)
    assert all((run.dir / "outputs" / f"{s}.json").exists() for s in steps)


def test_openai_batch_body_parses_like_an_interactive_response():
    from litreview.llm import openai_compatible as oc
    body = {"id": "x", "object": "chat.completion", "created": 1, "model": "gpt-6.1-sol",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 10, "total_tokens": 1010,
                      "prompt_tokens_details": {"cached_tokens": 600}}}
    r = oc.parse_completion(body, "openai", "gpt-6.1-sol")
    assert (r.input_tokens, r.cached_input_tokens, r.output_tokens, r.stop_reason) == (400, 600, 10, "stop")
