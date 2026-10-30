"""A10 input scope: bound findings in full, every other finding as a contradiction-index line, and one
detail round for the records A10 asks to see."""
import json

import pytest

from litreview import model_record
from litreview import orchestrator as orch
from litreview.tools import verification_scope as vs

PACKAGE = {
    "propositions": [
        {"proposition_id": "P1", "group_id": "G1", "supporting_finding_ids": ["R0001:F1"],
         "conflicting_finding_ids": ["R0002:F1"]},
        {"proposition_id": "P2", "group_id": "G1", "supporting_finding_ids": ["R0003:F1"]},
        {"proposition_id": "P3", "group_id": "G2", "supporting_finding_ids": ["R0005:F2"]},
    ],
    "groups": [{"group_id": "G1", "proposition_ids": ["P1", "P2"]}],
    "knowledge_gaps": [{"gap_id": "K1", "statement": "x", "established_by": ["P3"]}],
}
PLAN = {"title": {"text": "t", "proposition_ids": []},
        "sections": [{"section_id": "S1", "heading_proposition_ids": [],
                      "ordered_items": [{"item_id": "P1"}, {"item_id": "P2"}]}]}


def finding(fid, **kw):
    return {"finding_id": fid, "record_id": fid[:5], "span": "verbatim source passage " + fid,
            "context": {"evidence_system": "CELL_LINE"}, "disposition": "SUPPORTED",
            "plain_language_limit": "limit of " + fid, "constraints": ["c"], **kw}


FINDINGS = [finding(f) for f in ("R0001:F1", "R0002:F1", "R0003:F1", "R0004:F1", "R0005:F2")]


def manuscript(text):
    return {"sections": [{"section_id": "S1", "text_markdown": text}]}


def test_tagged_findings_in_full_everything_else_as_index_lines():
    full, index, stats = vs.scope(manuscript("DSF/Cu kills GBM cells ⟦P1⟧. Organizing text ⟦ORG⟧."), PLAN, PACKAGE,
                                  FINDINGS)
    assert [f["finding_id"] for f in full] == ["R0001:F1", "R0002:F1"]       # supporting and conflicting of P1
    assert full[0]["span"] and full[0]["context"]                            # contexts and source passages kept
    assert [i["finding_id"] for i in index] == ["R0003:F1", "R0004:F1", "R0005:F2"]  # P2 shares G1: not pulled in
    assert all(set(i) == {"finding_id", "assertion", "disposition"} for i in index)
    assert index[0]["assertion"] == "limit of R0003:F1"
    assert stats["bound_in_full"] == 2 and stats["contradiction_index"] == 3


def test_gap_references_and_plan_claim_lists_are_followed():
    plan = {**PLAN, "abstract_plan": {"ordered_proposition_ids": ["P2"]}}
    full, _, _ = vs.scope(manuscript("No study tested this ⟦K1⟧."), plan, PACKAGE, FINDINGS)
    assert {f["finding_id"] for f in full} == {"R0003:F1", "R0005:F2"}       # abstract P2; K1 -> P3


def test_requested_ids_must_be_in_the_index_and_are_capped():
    index = [{"finding_id": f"R0001:F{i}"} for i in range(60)]
    rv = {"detail_requests": [{"finding_id": f"R0001:F{i}"} for i in range(50)] + [{"finding_id": "R9999:F1"}]}
    ok, ignored = vs.requested(rv, index)
    assert len(ok) == vs.MAX_DETAIL and "R9999:F1" in ignored and len(ignored) == 11


def test_verify_sends_the_scope_and_runs_one_detail_round(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    run = orch.Run("t")
    run.save_state({"stage": "draft", "status": "READY", "counters": {}})
    run.save("manuscript_plan.json", PLAN)
    run.save("synthesis_approved.json", PACKAGE)
    run.save("validated_findings.json", FINDINGS)
    from evidence_fixtures import seed_sources
    seed_sources(run, FINDINGS)
    monkeypatch.setattr(run, "_deterministic_report", lambda m: {})
    _wrote(run, "A09-WRI", "A09-WRI_draft1", "anthropic")
    sent = []
    from test_verification_job import ScriptedVerifier, response
    base = ScriptedVerifier()

    def agent(agent_id, payload, step, **kw):
        sent.append((step, payload))
        assert kw["exclude_providers"] == frozenset({"anthropic"})
        if len(sent) == 1:
            return {**response('LOCAL'),'status':'NEEDS_EVIDENCE','retrieval_requests':[{'finding_ids':['R0004:F1']}]}
        out = base(payload['mode'],payload,step)
        if payload['mode']=='LOCAL':
            out['issues']=[{'occurrence_ids':[payload['occurrences'][0]['occurrence_id']],
                'finding_ids':['R0004:F1'],'code':'UNCITED_CONFLICT','severity':'MAJOR',
                'rationale':'Supplied contradiction','correction':'Qualify statement'}]
        return out
    monkeypatch.setattr(run, "agent", agent)
    rv = run._verify(manuscript("Claim ⟦P1⟧."), "DRAFT", "A10-RV_draft1")
    assert len(sent)==3 and sent[-1][1]['mode']=='GLOBAL'
    first, second = sent[0][1], sent[1][1]
    assert 'synthesis_package' not in first
    assert "R0004:F1" in {f["finding_id"] for f in second['retrieved_evidence']['findings']}
    assert 'UNCITED_CONFLICT' in {f['code'] for f in rv['findings']}
    prov = [json.loads(line) for line in (run.dir / "provenance.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(p.get('tool')=='bounded_verification' for p in prov)



def _wrote(run, agent, step, provider):
    run.budget.record(agent, provider, "m", 10, 10, step=step)
    (run.dir / "outputs").mkdir(parents=True, exist_ok=True)
    (run.dir / "outputs" / f"{step}.json").write_text("{}")


def _run(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    run = orch.Run("t")
    run.save_state({"stage": "draft", "status": "READY", "counters": {}})
    (run.dir / "input").mkdir(parents=True, exist_ok=True)
    (run.dir / "input" / "topic_family.txt").write_text("onc", encoding="utf-8")
    from evidence_fixtures import seed_sources
    seed_sources(run, FINDINGS)
    return run


def test_a10_stays_off_every_vendor_that_produced_the_manuscript(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    _wrote(run, "A09-WRI", "A09-WRI_draft1", "anthropic")
    run.budget.record("A12-EDI", "anthropic", "claude-sonnet-5-5", 10, 10, step="A12-EDI_rev1")  # refused...
    _wrote(run, "A12-EDI", "A12-EDI_rev1", "openai")                       # ...and an OpenAI fallback edited it
    run.budget.record("A12-EDI", "openai", "x", 10, 10, step="A12-EDI_rev2")   # no output: not in the lineage
    assert run._prose_vendors("A10-RV") == frozenset({"anthropic", "openai"})
    assert run.route("A10-RV").provider == "openai"                        # configuration alone: GPT-6.1
    m = run.route("A10-RV", run._prose_vendors("A10-RV"))                          # what produced the prose: not GPT-6.1
    assert m.provider == "kimi"                                            # same price, so the cost gate passes


def test_a10_with_no_known_producer_does_not_run(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    with pytest.raises(orch.AgentError, match="cannot tell which vendor produced the manuscript"):
        run._prose_vendors("A10-RV")


def test_detail_report_flags_routine_requests_at_the_cap():
    ev = [{"type": "tool_run", "tool": "verification_scope", "step": f"A10-RV_{i}",
           "summary": {"detail_requested": n, "detail_sent": min(n, vs.MAX_DETAIL), "bound_in_full": 200,
                       "contradiction_index": 271}} for i, n in enumerate([45, 40, 3])]
    entries = [{"agent": "A10-RV", "step": "A10-RV_0", "input_tokens": 150000, "cost_usd": 0.4},
               {"agent": "A10-RV", "step": "A10-RV_0_detail", "input_tokens": 170000, "cost_usd": 0.45}]
    r = vs.detail_report(ev, entries)
    assert (r["passes"], r["passes_with_requests"], r["passes_at_cap"], r["verdict"]) == (3, 3, 2, "ROUTINELY_AT_CAP")
    assert r["detail_calls"]["calls"] == 1 and r["first_calls"]["input_tokens_avg"] == 150000
    assert "scoping may not pay" in vs.detail_report_text(r)
    ev2 = [{**e, "summary": {"detail_requested": 0, "detail_sent": 0}} for e in ev[:2]] + [ev[2]]
    assert vs.detail_report(ev2, [])["verdict"] == "RARE"


def test_a11_stays_off_every_vendor_that_produced_the_manuscript(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    _wrote(run, "A09-WRI", "A09-WRI_draft1", "anthropic")
    _wrote(run, "A12-EDI", "A12-EDI_rev1", "kimi")                         # A12 fell back to Kimi mid-run
    assert run.route("A11-RC").provider == "kimi"                          # configuration alone: Kimi
    assert run.route("A11-RC", run._prose_vendors("A11-RC")).provider == "openai"   # would critique its own prose


def test_detail_report_breaks_requests_down_by_reason_and_check():
    def ev(items):
        return {"type": "tool_run", "tool": "verification_scope", "step": "s",
                "summary": {"detail_requested": len(items), "detail_sent": len(items), "detail_items": items}}
    conflict = {"finding_id": "R0001:F1", "kind": "UNCITED_CONFLICT", "check": "COUNTER_EVIDENCE", "paper_cited": False}
    missing = {"finding_id": "R0002:F1", "kind": "MISSING_FROM_SCOPE", "check": "CITATION", "paper_cited": True}
    r = vs.detail_report([ev([conflict, conflict, missing]), ev([])], [])
    assert r["by_kind"] == {"UNCITED_CONFLICT": 2, "MISSING_FROM_SCOPE": 1} and r["verdict"] == "FREQUENT"
    assert r["by_check"] == {"COUNTER_EVIDENCE": {"UNCITED_CONFLICT": 2}, "CITATION": {"MISSING_FROM_SCOPE": 1}}
    assert r["from_cited_papers"] == 1
    text = vs.detail_report_text(r)
    assert "CITATION (MISSING_FROM_SCOPE 1)" in text and "1 from papers the manuscript cites" in text
    r = vs.detail_report([ev([missing, missing, conflict])], [])
    assert r["verdict"] == "SCOPE_LINE_MISPLACED" and "wrong place" in vs.detail_report_text(r)


def test_classify_reads_a10_labels_and_checks_citations_itself():
    rv = {"detail_requests": [{"finding_id": "R0003:F1", "kind": "MISSING_FROM_SCOPE", "check": "CITATION"},
                              {"finding_id": "R0004:F1"}]}
    out = vs.classify(rv, ["R0003:F1", "R0004:F1"], manuscript("Claim [@R0003] ⟦P1⟧."), FINDINGS)
    assert out == [{"finding_id": "R0003:F1", "kind": "MISSING_FROM_SCOPE", "check": "CITATION", "paper_cited": True},
                   {"finding_id": "R0004:F1", "kind": "UNSPECIFIED", "check": "UNSPECIFIED", "paper_cited": False}]
