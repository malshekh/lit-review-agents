"""Batch stage: probe, reservations, identity-proven recovery, vendor separation per paper, ingestion,
refusals and repairs. The vendor layer (litreview.llm.batch) is faked; requests and manifests are built by
the real builders."""
import json
import threading
import time

import pytest

from litreview import batch_stage, model_record
from litreview import orchestrator as orch
from litreview.agents import RefusalError
from litreview.budget import BudgetExceeded
from litreview.llm import batch as vendor
from litreview.llm.base import LLMResponse

STEPS = [f"A05-KE_R000{i}" for i in range(1, 6)]


def step_of(cid):
    return cid.split("__")[0]


class FakeVendor:
    """Records every create (custom_ids, manifest hash, metadata); serves scripted results per step."""

    def __init__(self, outcome=None):
        self.created, self.outcome, self.rows, self.covered = [], outcome or {}, [], True
        self.hashes, self.meta, self.files, self.ended = [], [], {}, set()

    def upload(self, provider, data):
        if provider != "openai":
            return None
        fid = f"file-{len(self.files) + 1}"
        self.files[fid] = vendor.sha256(data)
        return fid

    def create(self, provider, reqs, file_id, metadata=None):
        self.created.append([r["custom_id"] for r in reqs])
        self.hashes.append(vendor.sha256(vendor.manifest(reqs)))
        self.meta.append(metadata)
        return f"batch_{len(self.created)}"

    def status(self, provider, bid):
        return {"done": True, "status": "ended", "counts": {}}

    def results(self, provider, bid, model):
        out = []
        for cid in self.created[int(bid.split("_")[1]) - 1]:
            kind = self.outcome.get(step_of(cid), "ok")
            if kind in ("expired", "errored"):
                out.append(vendor.ItemResult(cid, kind, error=kind, retryable=kind == "expired"))
                continue
            text = {"ok": json.dumps({"status": "OK", "id": step_of(cid)}), "bad_json": "{not json"}.get(kind, "")
            stop = {"refused": "refusal", "truncated": "max_tokens"}.get(kind, "end_turn")
            out.append(vendor.ItemResult(cid, "succeeded", LLMResponse(text, provider, model, 1000, 500, stop,
                                                                       "bio" if kind == "refused" else None)))
        return out

    def recent(self, provider, since):
        return [r for r in self.rows if r["created_at"] >= since], self.covered

    def input_sha256(self, file_id):
        return self.files[file_id]

    def result_ids(self, provider, bid):
        if bid not in self.ended:
            return None
        return self.created[int(bid.split("_")[1]) - 1]


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
    for name in ("upload", "create", "status", "results", "recent", "input_sha256", "result_ids"):
        monkeypatch.setattr(batch_stage.batch, name, getattr(fake, name))


def items(steps=STEPS):
    return [(s, {"record": {"record_id": s[-5:]}, "content": "x" * 400}) for s in steps]


def state(run, agent="A05-KE"):
    return json.loads(run.data(f"batches/{agent}.json").read_text())


# --- the normal path ---------------------------------------------------------------------------
def test_probe_then_one_batch_logged_at_batch_rates(run, monkeypatch):
    fake, calls, got = FakeVendor(), [], {}
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, calls)
    run.run_many("A05-KE", items(), lambda s, o: got.__setitem__(s, o))
    assert calls == [(STEPS[0], "claude-sonnet-5-5")]                     # the probe: one real item, interactive
    assert [[step_of(c) for c in b] for b in fake.created] == [STEPS[1:]]  # the rest: one batch
    assert sorted(got) == STEPS and got[STEPS[1]] == {"status": "OK", "id": STEPS[1]}
    entries = [e for e in run.budget.entries() if e.get("batch_id") == "batch_1"]
    assert len(entries) == 4 and entries[0]["cost_usd"] == pytest.approx((1000 * 1.00 + 500 * 5.00) / 1e6)
    rec = state(run)[0]
    assert rec["status"] == "INGESTED" and rec["succeeded"] == 4
    assert rec["estimate"]["output_tokens_per_item"] == 64000             # configured max, not history
    assert sum(e["outcome"] == "COMPLETED" for e in model_record.entries()) == 5      # probe + 4 batched
    run.run_many("A05-KE", items(), lambda s, o: None)                    # rerun: outputs reused, nothing paid
    assert len(fake.created) == 1 and len(calls) == 1


def test_fingerprint_is_frozen_before_create(run, monkeypatch):
    fake = FakeVendor()
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, [])
    run.run_many("A05-KE", items(), lambda s, o: None)
    rec = state(run)[0]
    fp = rec["fingerprint"]
    assert fp["run_id"] == "t" and fp["stage"] == "A05-KE" and fp["submission_id"] == rec["submission_id"]
    assert fp["custom_ids"] == sorted(fake.created[0])                    # deterministic: step + submission nonce
    assert all(c.endswith("__" + rec["submission_id"].split("-")[-1]) for c in fake.created[0])
    assert fp["manifest_sha256"] == fake.hashes[0]                        # the hash of exactly what was sent
    assert vendor.sha256((run.dir / fp["manifest_file"]).read_bytes()) == fp["manifest_sha256"]
    assert fake.meta[0]["submission_id"] == rec["submission_id"]


def test_probe_refusal_submits_nothing(run, monkeypatch):
    fake, calls = FakeVendor(), []
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, calls, refuse={STEPS[0]})
    with pytest.raises(RefusalError):
        run.run_many("A05-KE", items(), lambda s, o: None)
    assert fake.created == [] and not run.data("batches/A05-KE.json").exists()
    assert model_record.refused("onc") == {"claude-sonnet-5-5": "bio"}


# --- reservations ------------------------------------------------------------------------------
def test_projected_cost_at_max_tokens_over_the_cap_is_refused_not_asked(run, monkeypatch):
    fake, calls = FakeVendor(), []
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, calls)
    run.budget.cap = 0.50          # 4 items x 64k max output x $5/M = $1.28 projected
    with pytest.raises(BudgetExceeded, match="chunk of 4 not submitted: projected"):
        run.run_many("A05-KE", items(), lambda s, o: None)
    assert fake.created == [] and not run.data("batches/A05-KE.json").exists()   # no intent, no batch
    assert run.budget.reservations() == {}


def test_a_reservation_held_by_another_batch_blocks_a_second_one(run, monkeypatch):
    fake = FakeVendor()
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, [])
    run.budget.cap = 2.00                                                  # fits alone ($1.28 + input)
    assert run.budget.reserve("A06-SV-other", 1.00, "A06-SV")[0]           # an unsettled batch elsewhere
    with pytest.raises(BudgetExceeded, match="reservations held by unsettled batches"):
        run.run_many("A05-KE", items(), lambda s, o: None)
    assert fake.created == []
    run.budget.release("A06-SV-other")
    run.run_many("A05-KE", items(), lambda s, o: None)
    assert len(fake.created) == 1


def test_concurrent_reservations_cannot_both_pass_the_same_check(run):
    run.budget.cap = 1.00
    results = []
    barrier = threading.Barrier(8)

    def go(i):
        barrier.wait()
        results.append(run.budget.reserve(f"k{i}", 0.60, "A05-KE")[0])
    threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 8                                               # every contender got an answer
    assert results.count(True) == 1 and len(run.budget.reservations()) == 1


def test_reservation_is_held_until_the_batch_settles_and_shrinks_as_costs_log(run, monkeypatch):
    fake = FakeVendor()
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, [])
    seen = []
    original = batch_stage.BatchStage._ingest_one

    def spy(self, rec, step, resp, repair, counts):
        seen.append(run.budget.reserved())
        original(self, rec, step, resp, repair, counts)
    monkeypatch.setattr(batch_stage.BatchStage, "_ingest_one", spy)
    run.run_many("A05-KE", items(), lambda s, o: None)
    assert seen[0] > 1.0 and seen == sorted(seen, reverse=True)            # held, less each logged cost
    assert run.budget.reservations() == {} and run.budget.reserved() == 0  # released once settled


def test_headroom_counts_reservations_for_interactive_calls(run):
    run.budget.cap = 1.00
    run.budget.reserve("x", 1.00, "A06-SV")
    with pytest.raises(BudgetExceeded, match="reserved by unsettled batches"):
        run.budget.ensure_headroom()


# --- recovery by identity ------------------------------------------------------------------------
def _crash_after_create(run, monkeypatch, fake, provider="anthropic"):
    """Submit, then lose the batch ID as if the process died between create and saving it."""
    def create(p, reqs, file_id, metadata=None):
        FakeVendor.create(fake, p, reqs, file_id, metadata)
        raise ConnectionError("lost the response")
    monkeypatch.setattr(batch_stage.batch, "create", create)
    with pytest.raises(ConnectionError):
        run.run_many("A05-KE", items(), lambda s, o: None)
    monkeypatch.setattr(batch_stage.batch, "create", fake.create)
    rec = state(run)[0]
    assert rec["status"] == "INTENT" and rec["batch_id"] is None
    return rec


def test_in_progress_anthropic_candidate_is_never_adopted_or_replaced(run, monkeypatch):
    fake = FakeVendor()
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, [])
    rec = _crash_after_create(run, monkeypatch, fake)
    fake.rows = [{"id": "batch_1", "created_at": rec["intent_at"] + 2, "total": 4, "input_file_id": None}]
    with pytest.raises(orch.Pause, match="cannot be confirmed yet.*Nothing was resubmitted"):
        run.run_many("A05-KE", items(), lambda s, o: None)
    assert len(fake.created) == 1 and state(run)[0]["status"] == "UNRESOLVED"
    assert run.budget.reserved() > 0                                       # still held
    fake.ended.add("batch_1")                                              # it ends: custom_ids now readable
    got = {}
    run.run_many("A05-KE", items(), lambda s, o: got.__setitem__(s, o))
    assert len(fake.created) == 1 and sorted(got) == STEPS                 # adopted and ingested, not resubmitted
    assert state(run)[0]["batch_id"] == "batch_1" and run.budget.reservations() == {}


def test_a_lookalike_batch_is_rejected_on_its_custom_ids(run, monkeypatch):
    fake = FakeVendor()
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, [])
    rec = _crash_after_create(run, monkeypatch, fake)
    fake.created.insert(0, [f"{s}__other" for s in STEPS[1:]])             # same time, same count, not ours
    fake.created[1] = []                                                   # ours was never actually created
    fake.ended |= {"batch_1"}
    fake.rows = [{"id": "batch_1", "created_at": rec["intent_at"] + 1, "total": 4, "input_file_id": None}]
    with pytest.raises(orch.Pause, match="may still have been in flight"):  # window still open
        run.run_many("A05-KE", items(), lambda s, o: None)
    monkeypatch.setattr(batch_stage.time, "time", lambda: rec["intent_at"] + batch_stage.CREATE_WINDOW + 1)
    fake.created = fake.created[:1]
    run.run_many("A05-KE", items(), lambda s, o: None)
    recs = state(run)
    assert recs[0]["status"] == "NOT_CREATED" and recs[1]["status"] == "INGESTED"


def test_incomplete_listing_or_double_creation_stays_unresolved(run, monkeypatch):
    fake = FakeVendor()
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, [])
    rec = _crash_after_create(run, monkeypatch, fake)
    monkeypatch.setattr(batch_stage.time, "time", lambda: rec["intent_at"] + 5000)
    fake.covered = False
    with pytest.raises(orch.Pause, match="did not reach back"):
        run.run_many("A05-KE", items(), lambda s, o: None)
    fake.covered = True
    fake.created.append(list(fake.created[0]))                             # the same submission, created twice
    fake.ended |= {"batch_1", "batch_2"}
    fake.rows = [{"id": f"batch_{i}", "created_at": rec["intent_at"] + i, "total": 4, "input_file_id": None}
                 for i in (1, 2)]
    with pytest.raises(orch.Pause, match="created twice"):
        run.run_many("A05-KE", items(), lambda s, o: None)
    assert len(fake.created) == 2                                          # never a third


def test_openai_recovery_requires_the_input_file_hash(run, monkeypatch):
    fake = FakeVendor()
    install(monkeypatch, fake)
    stage = batch_stage.BatchStage(run, "A06-SV", [], lambda s, o: None)
    fp = {"submission_id": "A06-SV-abc", "manifest_sha256": "h1", "custom_ids": []}
    rec = {"intent_at": 1000.0, "provider": "openai", "count": 4, "input_file_id": "file-1", "fingerprint": fp}
    fake.files = {"file-1": "h1", "file-2": "h2"}
    fake.rows = [{"id": "batch_9", "created_at": 1003.0, "total": 0, "input_file_id": "file-1",
                  "metadata": {"submission_id": "A06-SV-abc", "manifest_sha256": "h1"}}]
    assert stage._recover(rec) == ("ADOPT", "batch_9")
    fake.files["file-1"] = "tampered"                                      # ours by file ID, not by content:
    assert stage._recover(rec)[0] == "UNRESOLVED"                          # an anomaly, never NOT_CREATED


def test_a_record_without_a_fingerprint_is_never_adopted(run, monkeypatch):
    fake = FakeVendor()
    install(monkeypatch, fake)
    stage = batch_stage.BatchStage(run, "A05-KE", [], lambda s, o: None)
    fake.created = [STEPS[1:]]
    fake.ended = {"batch_1"}
    fake.rows = [{"id": "batch_1", "created_at": 1003.0, "total": 4, "input_file_id": None}]
    rec = {"intent_at": 1000.0, "provider": "anthropic", "count": 4, "input_file_id": None}
    assert stage._recover(rec)[0] == "UNRESOLVED"


# --- vendor separation per paper ------------------------------------------------------------------
def test_a06_routes_each_paper_on_the_vendor_of_its_extraction(run, monkeypatch):
    fake, calls = FakeVendor(), []
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, calls)
    run.save_state({"stage": "validate", "status": "READY", "counters": {}})
    steps = [f"A06-SV_R000{i}_v1" for i in range(1, 8)]
    by_gpt = {steps[5], steps[6]}                                          # A05 fell back to GPT-6.1 for two papers
    exclude = lambda s: frozenset({"openai" if s in by_gpt else "anthropic"})   # noqa: E731
    with pytest.raises(orch.Pause, match="is on openai, the vendor that produced the work it audits"):
        run.run_many("A06-SV", [(s, {"x": 1}) for s in steps], lambda s, o: None, exclude=exclude)
    run.approve_alternate("A06-SV")
    run.run_many("A06-SV", [(s, {"x": 1}) for s in steps], lambda s, o: None, exclude=exclude)
    batched = {step_of(c) for b in fake.created for c in b}
    assert batched and not batched & by_gpt                                # GPT-extracted papers never enter a GPT batch
    assert {s for s, m in calls if m == "kimi-k3.1-pro"} == by_gpt         # they go to the other vendor


def test_vendor_rule_is_checked_again_before_upload(run, monkeypatch):
    fake = FakeVendor()
    install(monkeypatch, fake)
    from litreview import config
    m = config.agent_candidates("A06-SV")[0]
    stage = batch_stage.BatchStage(run, "A06-SV", [("A06-SV_R0001_v1", {"x": 1})], lambda s, o: None,
                                   exclude=lambda s: frozenset({"openai"}))
    with pytest.raises(batch_stage.VendorSeparationError, match="not submitted"):
        stage._submit(m, ["A06-SV_R0001_v1"])
    assert fake.created == [] and fake.files == {} and run.budget.reservations() == {}


def test_extraction_vendor_is_the_last_logged_call(run):
    run.budget.record("A05-KE", "anthropic", "claude-sonnet-5-5", 10, 10, step="A05-KE_R0001")
    run.budget.record("A05-KE", "openai", "gpt-6.1-sol", 10, 10, step="A05-KE_R0002")   # refused here first...
    run.budget.record("A05-KE", "anthropic", "claude-opus-5", 10, 10, step="A05-KE_R0002")  # ...then the alternate
    assert run._extraction_vendor("R0001") == "anthropic" and run._extraction_vendor("R0002") == "anthropic"
    (run.dir / "outputs" / "A05-KE_R0001_reextract.json").write_text("{}")
    run.budget.record("A05-KE", "openai", "gpt-6.1-sol", 10, 10, step="A05-KE_R0001_reextract")
    assert run._extraction_vendor("R0001") == "openai"                     # the kept re-extraction counts
    with pytest.raises(orch.AgentError, match="cannot tell which vendor"):
        run._extraction_vendor("R0009")


# --- ingestion -----------------------------------------------------------------------------------
def test_interrupted_ingestion_never_logs_a_cost_twice(run, monkeypatch):
    fake, calls = FakeVendor(), []
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, calls)
    run.run_many("A05-KE", items(), lambda s, o: None)
    rec = state(run)[0]
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
    assert [[step_of(c) for c in b] for b in fake.created] == [STEPS[1:], [STEPS[3], STEPS[4]]]
    assert fake.created[0][0].split("__")[1] != fake.created[1][0].split("__")[1]   # a new submission, new IDs


def test_refusals_inside_a_batch_route_to_the_alternate_as_a_mixed_model_stage(run, monkeypatch):
    fake, calls = FakeVendor(), []
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


# --- savings reporting ------------------------------------------------------------------------------
def test_cache_savings_are_reported_apart_from_the_batch_discount(run):
    b = run.budget
    b.record("A05-KE", "anthropic", "claude-sonnet-5-5", 1000, 2000, step="s1", cached_input_tokens=10000,
             cache_write_1h_tokens=10000, batch_id="b1")
    v = b.summary()["savings_usd"]
    # batch table: input 1.00, cache read 0.05, 1h write 2.00 per M
    assert v["cache_read_saved"] == pytest.approx(10000 * 0.95 / 1e6, abs=1e-4)
    assert v["cache_write_1h_premium"] == pytest.approx(10000 * 1.00 / 1e6, abs=1e-4)
    assert v["cache_net"] == pytest.approx(v["cache_read_saved"] - v["cache_write_1h_premium"], abs=1e-4)
    std = (1000 * 2 + 2000 * 10 + 10000 * 0.10 + 10000 * 4.00) / 1e6
    assert v["batch_discount"] == pytest.approx(std / 2, abs=1e-4)
    assert "Batch discount, separately" in b.summary_text()


# --- chunks ----------------------------------------------------------------------------------------
STEPS7 = [f"A05-KE_R000{i}" for i in range(1, 8)]


def _chunk_run(run, monkeypatch, cap, in_flight):
    fake, events = FakeVendor(), []
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, [])
    monkeypatch.setitem(run.cfg["batch"], "chunk_size", 2)
    monkeypatch.setitem(run.cfg["batch"], "max_chunks_in_flight", in_flight)
    run.budget.cap = cap
    create, finish = fake.create, batch_stage.BatchStage._finish

    def spy_create(*a, **k):
        events.append(("create", round(run.budget.reserved(), 2)))
        return create(*a, **k)

    def spy_finish(self, rec):
        events.append(("settle", None))
        finish(self, rec)
    monkeypatch.setattr(batch_stage.batch, "create", spy_create)
    monkeypatch.setattr(batch_stage.BatchStage, "_finish", spy_finish)
    got = {}
    run.run_many("A05-KE", items(STEPS7), lambda s, o: got.__setitem__(s, o))
    return fake, events, got


def test_chunks_each_reserve_their_worst_case_and_settle_before_the_next(run, monkeypatch):
    # a chunk of 2 reserves about $0.64 (2 x 64k at $5/M): one fits under $1.00, two do not
    fake, events, got = _chunk_run(run, monkeypatch, cap=1.00, in_flight=2)
    assert [[step_of(c) for c in b] for b in fake.created] == [STEPS7[1:3], STEPS7[3:5], STEPS7[5:7]]
    assert [e[0] for e in events] == ["create", "settle"] * 3              # waits instead of refusing
    assert sorted(got) == STEPS7 and run.budget.reservations() == {}
    recs = state(run)
    assert len({r["submission_id"] for r in recs}) == 3                    # own fingerprint per chunk
    assert len({r["fingerprint"]["manifest_sha256"] for r in recs}) == 3


def test_chunks_run_side_by_side_when_headroom_and_config_allow(run, monkeypatch):
    fake, events, _ = _chunk_run(run, monkeypatch, cap=5.00, in_flight=2)
    assert [e[0] for e in events][:3] == ["create", "create", "settle"]
    assert events[1][1] > 0.6                                              # the first chunk's reservation still held


def test_a_chunk_that_cannot_fit_alone_stops_the_stage(run, monkeypatch):
    fake = FakeVendor()
    install(monkeypatch, fake)
    fake_interactive(monkeypatch, [])
    monkeypatch.setitem(run.cfg["batch"], "chunk_size", 2)
    run.budget.cap = 0.30
    with pytest.raises(BudgetExceeded, match="chunk of 2 not submitted"):
        run.run_many("A05-KE", items(STEPS7), lambda s, o: None)
    assert fake.created == [] and run.budget.reservations() == {}
    assert not (run.data("batches") / "manifests").exists() or not any((run.data("batches") / "manifests").iterdir())
