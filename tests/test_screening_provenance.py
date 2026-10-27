"""Screening invariants when A04 is rerouted mid-stage (Haiku refuses, Luna takes over on resume)."""
import json

import pytest

from litreview import config, model_record
from litreview import orchestrator as orch
from litreview.agents import RefusalError
from litreview.checkpoints import write_cp2

HAIKU = config.AgentModel("A04-CQ", "anthropic", "claude-haiku-5-5", 1000, 0.0)
LUNA = config.AgentModel("A04-CQ", "openai", "gpt-6-luna", 1000, 0.0)


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    monkeypatch.setattr(config, "agent_candidates", lambda a: [HAIKU, LUNA])
    r = orch.Run("t")
    r.cfg = {**r.cfg, "loops": {**r.cfg["loops"], "cq_batch_size": 2}}
    r.save_state({"stage": "qualify", "status": "READY", "counters": {}})
    (r.dir / "input").mkdir(parents=True, exist_ok=True)
    (r.dir / "input" / "topic_family.txt").write_text("onc", encoding="utf-8")
    r.save("spec_approved.json", {"selection_criteria": {"inclusion": ["glioblastoma"]}})
    r.save("records.json", [{"record_id": f"R{i}", "title": f"T{i}", "abstract": "a", "query_family_ids": ["QF01"]}
                            for i in range(1, 6)])
    return r


def _fake(calls, refuse_batch=None):
    def run_agent(agent_id, payload, run_dir, step, budget, prov, model=None, schema_file=None):
        calls.append({"step": step, "model": model.model, "spec": json.dumps(payload["review_spec"]),
                      "ids": [x["record_id"] for x in payload["records"]]})
        if step == refuse_batch:
            raise RefusalError("refused", model.model, "bio")
        return {"qualifications": [{"record_id": x["record_id"], "disposition": "EXCLUDED" if x["record_id"] == "R5"
                                    else "QUALIFIED", "themes": [], "flags": []} for x in payload["records"]]}
    return run_agent


def test_refused_batch_stays_unscreened_and_resume_neither_duplicates_nor_skips(run, monkeypatch):
    calls = []
    monkeypatch.setattr(orch, "run_agent", _fake(calls, refuse_batch="A04-CQ_B002"))
    with pytest.raises(RefusalError):
        run._qualify_pending()
    quals = {q["record_id"]: q for q in run.load("qualifications.json")}
    assert set(quals) == {"R1", "R2"}                           # the refused batch (R3, R4) stays unscreened
    run2 = orch.Run("t")                                        # resume
    run2.cfg = run.cfg
    monkeypatch.setattr(orch, "run_agent", _fake(calls))
    run2._qualify_pending()
    quals = {q["record_id"]: q for q in run2.load("qualifications.json")}
    screened = [i for c in calls if c["step"] != "A04-CQ_B002" for i in c["ids"]]
    assert sorted(screened) == ["R1", "R2", "R3", "R4", "R5"]   # every record exactly once, none skipped
    assert [c["step"] for c in calls] == ["A04-CQ_B001", "A04-CQ_B002", "A04-CQ_B003", "A04-CQ_B004"]  # no overwrite
    assert [c["model"] for c in calls] == ["claude-haiku-5-5", "claude-haiku-5-5", "gpt-6-luna", "gpt-6-luna"]
    assert len({c["spec"] for c in calls}) == 1                 # identical eligibility criteria to both models
    assert {q["record_id"]: q["screened_by"] for q in quals.values()} == {
        "R1": "claude-haiku-5-5", "R2": "claude-haiku-5-5", "R3": "gpt-6-luna", "R4": "gpt-6-luna", "R5": "gpt-6-luna"}
    assert all(q["screening_prompt"].startswith("A04-CQ v") for q in quals.values())


def test_cp2_shows_screener_per_record_and_split_bias_check(run, monkeypatch):
    calls = []
    monkeypatch.setattr(orch, "run_agent", _fake(calls, refuse_batch="A04-CQ_B002"))
    with pytest.raises(RefusalError):
        run._qualify_pending()
    run2 = orch.Run("t")
    run2.cfg = run.cfg
    monkeypatch.setattr(orch, "run_agent", _fake(calls))
    run2._qualify_pending()
    bias = run2.load("bias_report.json")
    by_model = bias["exclusion_rate_by_screening_model"]
    assert by_model["gpt-6-luna"] == {"received": 3, "excluded": 1, "exclusion_rate": 0.333}
    assert by_model["claude-haiku-5-5"]["exclusion_rate"] == 0.0
    write_cp2(run2.dir, run2.load("records.json"), run2.load("qualifications.json"), bias)
    csv_text = (run2.dir / "checkpoints" / "CP2_records.csv").read_text(encoding="utf-8")
    assert "screened_by" in csv_text.splitlines()[0] and "gpt-6-luna (A04-CQ v" in csv_text
    review = (run2.dir / "checkpoints" / "CP2_review.md").read_text(encoding="utf-8")
    assert "- claude-haiku-5-5: 2 records" in review and "- gpt-6-luna: 3 records" in review
    assert "Screening was split between models" in review


def test_single_screener_has_no_split_section(run, monkeypatch):
    monkeypatch.setattr(orch, "run_agent", _fake([]))
    run._qualify_pending()
    assert "exclusion_rate_by_screening_model" not in run.load("bias_report.json")
