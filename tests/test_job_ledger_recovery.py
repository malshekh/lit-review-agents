"""The job ledger, crash recovery between its states, the run lock, and repair preservation."""
import json

import pytest

from litreview import config, job_ledger, model_record
from litreview import orchestrator as orch
from litreview.agents import base as agent_base
from litreview.llm.base import LLMResponse


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
    calls = []
    it = iter(replies)

    def complete(provider, **kw):
        calls.append(kw)
        r = next(it)
        if isinstance(r, BaseException):
            raise r
        text, stop = r
        return LLMResponse(text, provider, kw["model"], 100, 50, stop)
    monkeypatch.setattr(agent_base, "complete", complete)
    return calls


def states(run, step):
    return [e["state"] for e in job_ledger.Ledger(run.dir).events(step)]


def test_a_successful_call_passes_through_every_state_in_order(run, monkeypatch):
    _model(monkeypatch, [('{"a": 1}', "end_turn")])
    run.agent("A05-KE", {"x": 1}, "A05-KE_R0001")
    assert states(run, "A05-KE_R0001") == ["PREPARED", "RESERVED", "DISPATCHED", "RESPONSE_SAVED", "ACCOUNTED",
                                           "VALIDATED", "COMMITTED"]
    assert (run.dir / "outputs" / "A05-KE_R0001.response0.json").exists()


class Crash(BaseException):
    """Stands for the process dying: not an Exception, so nothing in the pipeline catches it."""


def test_crash_after_the_reply_arrives_but_before_accounting_loses_nothing_and_resends_nothing(run, monkeypatch):
    calls = _model(monkeypatch, [('{"a": 1}', "end_turn")])
    record = run.budget.record
    monkeypatch.setattr(run.budget, "record", lambda *a, **k: (_ for _ in ()).throw(Crash()))
    with pytest.raises(Crash):
        run.agent("A05-KE", {"x": 1}, "A05-KE_R0001")
    assert states(run, "A05-KE_R0001")[-1] == "RESPONSE_SAVED" and run.budget.entries() == []
    monkeypatch.setattr(run.budget, "record", record)            # the process restarts
    assert run.agent("A05-KE", {"x": 1}, "A05-KE_R0001") == {"a": 1}
    assert len(calls) == 1                                       # the provider was called once, ever
    assert len(run.budget.entries()) == 1 and run.budget.entries()[0]["output_tokens"] == 50   # and its cost is logged once
    assert run.budget.reservations() == {}                       # the hold of the crashed attempt is settled
    assert states(run, "A05-KE_R0001")[-3:] == ["ACCOUNTED", "VALIDATED", "COMMITTED"]


def test_crash_while_a_request_is_in_flight_is_ambiguous_and_is_not_resent(run, monkeypatch):
    calls = _model(monkeypatch, [Crash(), ('{"a": 1}', "end_turn")])
    with pytest.raises(Crash):
        run.agent("A05-KE", {"x": 1}, "A05-KE_R0001")
    assert states(run, "A05-KE_R0001")[-1] == "DISPATCHED"
    with pytest.raises(orch.Pause, match="may have\\s+completed and been billed"):
        run.agent("A05-KE", {"x": 1}, "A05-KE_R0001")
    assert len(calls) == 1                                       # not resent while its status is unknown
    ledger = job_ledger.Ledger(run.dir)
    assert [e["step"] for e in ledger.ambiguous()] == ["A05-KE_R0001"]
    with pytest.raises(ValueError, match="who checked"):
        ledger.resolve("A05-KE_R0001", False, "", "")
    event = ledger.resolve("A05-KE_R0001", False, "May Khalid", "no request at 14:02 on the usage page")
    run.budget.release(event["reservation"])
    assert run.agent("A05-KE", {"x": 1}, "A05-KE_R0001") == {"a": 1} and len(calls) == 2


def test_a_timeout_is_ambiguous_but_a_rejected_request_is_not(run, monkeypatch):
    class Rejected(Exception):
        status_code = 400

    class Timeout(Exception):
        pass
    _model(monkeypatch, [Rejected("bad request"), Timeout("read timed out")])
    with pytest.raises(agent_base.AgentError, match="API error: Rejected"):
        run.agent("A05-KE", {"x": 1}, "A05-KE_R0001")
    assert states(run, "A05-KE_R0001")[-1] == "API_ERROR" and run.budget.reservations() == {}   # nothing billed: hold released
    with pytest.raises(agent_base.AgentError, match="API error: Timeout"):
        run.agent("A05-KE", {"x": 2}, "A05-KE_R0002")
    assert states(run, "A05-KE_R0002")[-1] == "DISPATCHED" and len(run.budget.reservations()) == 1   # unknown: hold kept
    with pytest.raises(orch.Pause, match="not resent"):
        run.agent("A05-KE", {"x": 2}, "A05-KE_R0002")


def test_crash_after_validation_but_before_commit_reuses_the_saved_reply(run, monkeypatch):
    calls = _model(monkeypatch, [('{"a": 1}', "end_turn")])
    save = run._receipt_save
    monkeypatch.setattr(run, "_receipt_save", lambda *a, **k: (_ for _ in ()).throw(Crash()))   # dies before the receipt
    with pytest.raises(Crash):
        run.agent("A05-KE", {"x": 1}, "A05-KE_R0001")
    assert states(run, "A05-KE_R0001")[-1] == "COMMITTED" and len(run.budget.entries()) == 1
    assert run.load("receipts.json", {}) == {}
    monkeypatch.setattr(run, "_receipt_save", save)
    assert run.agent("A05-KE", {"x": 1}, "A05-KE_R0001") == {"a": 1}
    assert len(calls) == 1 and len(run.budget.entries()) == 1               # not sent again, not charged again
    assert "A05-KE_R0001" in run.load("receipts.json")
    # a different request under the same step is a new call: the saved reply is not reused for it
    _model(monkeypatch, [('{"a": 2}', "end_turn")])
    assert run.agent("A05-KE", {"x": 2}, "A05-KE_R0001") == {"a": 2}


def test_two_processes_cannot_work_on_one_run(tmp_path, monkeypatch):
    really_alive = job_ledger._alive
    with job_ledger.RunLock(tmp_path):
        holder = json.loads((tmp_path / "run.lock").read_text())
        (tmp_path / "run.lock").write_text(json.dumps({**holder, "pid": holder["pid"] + 1}))   # another process
        monkeypatch.setattr(job_ledger, "_alive", lambda pid: True)
        with pytest.raises(job_ledger.RunLocked, match="Two processes must never dispatch"):
            with job_ledger.RunLock(tmp_path):
                pass
        monkeypatch.setattr(job_ledger, "_alive", lambda pid: False)                         # that process is gone
        with job_ledger.RunLock(tmp_path) as lock:
            assert lock.took_over["pid"] == holder["pid"] + 1
    assert not (tmp_path / "run.lock").exists()
    assert really_alive(__import__("os").getpid()) and not really_alive(0)


def test_run_takes_and_releases_the_lock(run, monkeypatch):
    monkeypatch.setattr(run, "_run", lambda until=None: "LOCKED" if (run.dir / "run.lock").exists() else "UNLOCKED")
    assert run.run() == "LOCKED" and not (run.dir / "run.lock").exists()


# ---------------------------------------------------------------------------------- repair preservation
ORIGINAL = {"propositions": [{"id": "P1", "text": "DSF 50 mg/kg did not differ from vehicle (p = 0.0732)",
                              "finding_ids": ["R0001:F36", "R0001:F105"], "cites": "[@R0001]"}]}


def test_preservation_check_names_what_a_repair_lost():
    same = json.loads(json.dumps(ORIGINAL))
    same["mode"] = "GROUP"                                                     # structure added: fine
    assert agent_base.preservation_problems(ORIGINAL, same) == []
    fewer = {"propositions": [{"id": "P1", "text": "DSF did not differ from vehicle", "finding_ids": ["R0001:F36"], "cites": "[@R0001]"}]}
    problems = agent_base.preservation_problems(ORIGINAL, fewer)
    assert any("R0001:F105" in p for p in problems) and any("0.0732" in p and "50" in p for p in problems)
    invented = json.loads(json.dumps(ORIGINAL))
    invented["propositions"][0]["finding_ids"].append("R0009:F1")
    assert any("not in the original" in p and "R0009:F1" in p for p in agent_base.preservation_problems(ORIGINAL, invented))


def test_a_repair_that_drops_an_evidence_id_is_rejected_and_the_original_kept(run, monkeypatch):
    import jsonschema
    seen = []

    def validate(agent, out, schema=None):
        seen.append(out)
        if len(seen) == 1:
            raise jsonschema.ValidationError("too many finding_ids")
    monkeypatch.setattr(agent_base, "validate", validate)
    dropped = {"propositions": [{"id": "P1", "text": "DSF 50 mg/kg did not differ from vehicle (p = 0.0732)",
                                 "finding_ids": ["R0001:F36"], "cites": "[@R0001]"}]}
    _model(monkeypatch, [(json.dumps(ORIGINAL), "end_turn"), (json.dumps(dropped), "end_turn")])
    with pytest.raises(agent_base.AgentError, match="repair was rejected.*R0001:F105.*resize"):
        run.agent("A05-KE", {"x": 1}, "A05-KE_R0001")
    out = run.dir / "outputs"
    assert not (out / "A05-KE_R0001.json").exists()
    assert json.loads((out / "A05-KE_R0001.raw0.txt").read_text(encoding="utf-8")) == ORIGINAL        # the paid original survives
    assert json.loads((out / "A05-KE_R0001.repair.rejected.json").read_text())["problems"]
    assert states(run, "A05-KE_R0001")[-1] == "REPAIR_REJECTED"


def test_a_structural_repair_that_keeps_everything_is_accepted(run, monkeypatch):
    import jsonschema
    n = []

    def validate(agent, out, schema=None):
        n.append(1)
        if len(n) == 1:
            raise jsonschema.ValidationError("'mode' is a required property")
    monkeypatch.setattr(agent_base, "validate", validate)
    _model(monkeypatch, [(json.dumps(ORIGINAL), "end_turn"), (json.dumps({**ORIGINAL, "mode": "GROUP"}), "end_turn")])
    assert run.agent("A05-KE", {"x": 1}, "A05-KE_R0001")["mode"] == "GROUP"
    assert config.load("pipeline")["loops"]["max_json_repair_attempts"] == 1
