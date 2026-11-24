"""Offline regressions for the interrupted post-pilot hardening handoff."""
import json
import pytest
from test_discovery_pilot import run, _records, _at_cp2
from litreview import orchestrator as orch, checkpoints, structured
from litreview.budget import BudgetTracker


def approve_selection(run, ids=None):
    d = checkpoints.cp_dir(run.dir)
    if ids is not None:
        import csv
        p = d / "CP2_records.csv"
        rows = list(csv.DictReader(p.open(encoding="utf-8")))
        for row in rows:
            row["select"] = "Y" if row["record_id"] in ids else ""
        with p.open("w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    p = d / "CP2_decision.json"
    decision = json.loads(p.read_text())
    decision.update(review_issues_acknowledged=True, notes="Offline fixture: selection and budget reviewed.")
    decision["review_fingerprint"] = json.loads((d / "CP2_review_state.json").read_text())["fingerprint"]
    p.write_text(json.dumps(decision))
    checkpoints.approve(run.dir,"CP2",run.prov)


def test_over_budget_cp2_can_change_selection_without_discovery_replay(run,monkeypatch):
    _at_cp2(run,_records())
    monkeypatch.setattr(run,"_cp2_costs",lambda q: None)
    with pytest.raises(orch.Pause): run.stage_cp2(run.state())
    run.budget.cap = 0.01
    approve_selection(run)
    with pytest.raises(orch.Pause,match="not frozen"): run.stage_cp2(run.state())
    assert not run.data("corpus_manifest.json").exists()
    assert not run.data("selected_corpus.json").exists()
    records, quals = run.load("records.json"), run.load("qualifications.json")
    run.budget.cap = 10000
    approve_selection(run,["R0001"])
    with pytest.raises(orch.Pause,match="approve CP2 again"): run.stage_cp2(run.state())
    approve_selection(run,["R0001"])
    assert run.stage_cp2(run.state()) == "extract"
    assert len(run.load("corpus_manifest.json")["papers"]) == 1
    assert run.load("records.json") == records and run.load("qualifications.json") == quals


@pytest.mark.parametrize("levels", [["ABSTRACT"]*7,["FULL_TEXT"]*7,["FULL_TEXT","ABSTRACT"]*3+["FULL_TEXT"]])
def test_level_agnostic_tranche_uses_three_papers(run,levels):
    manifest={"papers":[{"paper_id":f"P{i}"} for i in range(7)]}
    run.save("corpus_manifest.json",manifest)
    run.save("selected_corpus.json",[{"record_id":f"R{i}","manifest_paper_id":f"P{i}","intended_reading_level":lv} for i,lv in enumerate(levels)])
    run.cfg["run_spec"]["first_tranche"]={"papers":3}
    first=run._first_tranche()
    assert len(first)==3 and len(set(first))==3
    if len(set(levels))==2: assert {levels[int(r[1:])] for r in first}==set(levels)


def test_smoke_receipts_charge_run_once_and_block_uncertain_retry(tmp_path,monkeypatch):
    from litreview.llm.base import LLMResponse
    budget=BudgetTracker(tmp_path)
    target={"agent":"A05-KE","provider":"openai","model":"gpt-6.1-sol","effort":None,"schema_file":"fixture","schema":{},"schema_sha256":"abc","already_verified":False}
    monkeypatch.setattr(structured,"targets",lambda:[target] if not structured.verified().get("openai|gpt-6.1-sol|abc",{}).get("accepted") else [])
    monkeypatch.setattr(structured,"RECORD",tmp_path/"verified.json")
    monkeypatch.setattr("litreview.llm.complete",lambda *a,**k: LLMResponse("{}","openai","gpt-6.1-sol",500,20,"end_turn"))
    result=structured.smoke_test(budget,1,"Fixture",tmp_path/"smoke.jsonl")
    assert result["spent_usd"] == pytest.approx(budget.spent(),abs=0.0001)
    assert len(budget.entries())==1 and not budget.reservations()
    structured.smoke_test(budget,1,"Fixture",tmp_path/"smoke.jsonl")
    assert len(budget.entries())==1
    budget.reserve("smoke-uncertain",0.1,"smoke-test")
    with pytest.raises(ValueError,match="unsettled smoke receipt"):
        structured.smoke_test(budget,1,"Fixture",tmp_path/"smoke.jsonl")


def test_smoke_cannot_exceed_combined_run_cap(tmp_path,monkeypatch):
    budget=BudgetTracker(tmp_path); budget.cap=0
    monkeypatch.setattr(structured,"RECORD",tmp_path/"verified.json")
    monkeypatch.setattr("litreview.llm.complete",lambda *a,**k: pytest.fail("paid dispatch"))
    with pytest.raises(ValueError,match="combined run allowance"):
        structured.smoke_test(budget,100,"Fixture",tmp_path/"smoke.jsonl")



def test_independent_initial_validation_resumes_without_repeating_completed_calls(run,monkeypatch):
    calls=[]
    monkeypatch.setattr(run,"_prepare_validation",lambda rid: ({"findings":[]},{"Abstract":"fixture"}))
    monkeypatch.setattr(run,"_save_a06_input",lambda *a: None)
    monkeypatch.setattr(run,"_extraction_vendor",lambda *a: "openai")
    monkeypatch.setattr(run,"_save_validation",lambda rid,out: run.save(f"validations/{rid}.json",out))
    def agent(agent,payload,step,**kwargs):
        assert agent=="A06-SV" and kwargs["exclude_providers"]==frozenset({"openai"})
        calls.append(step)
        if len(calls)==2: raise RuntimeError("interrupted validation")
        out={"validations":[]}
        (run.dir/"outputs").mkdir(exist_ok=True)
        (run.dir/"outputs"/(step+".json")).write_text(json.dumps(out))
        return out
    monkeypatch.setattr(run,"agent",agent)
    with pytest.raises(RuntimeError,match="interrupted"):
        run._validate_papers(["R0001","R0002","R0003"])
    assert run.data("validations/R0001.json").exists()
    run._validate_papers(["R0001","R0002","R0003"])
    assert calls.count("A06-SV_R0001_v1")==1
    assert calls.count("A06-SV_R0002_v1")==2
    assert all(run.data(f"validations/{rid}.json").exists() for rid in ["R0001","R0002","R0003"])


def test_received_smoke_receipt_recovers_once_after_interruption(tmp_path,monkeypatch):
    budget=BudgetTracker(tmp_path)
    monkeypatch.setattr(structured,"RECORD",tmp_path/"verified.json")
    monkeypatch.setattr("litreview.llm.complete",lambda *a,**k: pytest.fail("receipt must not be dispatched again"))
    budget.reserve("smoke-received",0.1,"smoke-test")
    receipts=tmp_path/"smoke_receipts"; receipts.mkdir()
    (receipts/"smoke-received.json").write_text(json.dumps({"state":"RECEIVED","reservation":"smoke-received",
        "provider":"openai","model":"gpt-6.1-sol","schema_sha256":"fixture","input_tokens":500,"output_tokens":20,"text":"{}"}))
    structured.recover_smoke_receipts(budget)
    structured.recover_smoke_receipts(BudgetTracker(tmp_path))
    assert len(budget.entries())==1 and not budget.reservations()
    assert structured.verified()["openai|gpt-6.1-sol|fixture"]["accepted"]
