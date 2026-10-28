"""A10 input scope: bound findings in full, every other finding as a contradiction-index line, and one
detail round for the records A10 asks to see."""
import json

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
    monkeypatch.setattr(run, "_deterministic_report", lambda m: {})
    sent = []

    def agent(agent_id, payload, step, **kw):
        sent.append((step, payload))
        if len(sent) == 1:
            return {"findings": [], "detail_requests": [{"finding_id": "R0004:F1", "reason": "null result"}]}
        return {"findings": [{"code": "UNCITED_CONFLICT"}], "detail_requests": []}
    monkeypatch.setattr(run, "agent", agent)
    rv = run._verify(manuscript("Claim ⟦P1⟧."), "DRAFT", "A10-RV_draft1")
    assert [s for s, _ in sent] == ["A10-RV_draft1", "A10-RV_draft1_detail"]
    first, second = sent[0][1], sent[1][1]
    assert "R0004:F1" in {i["finding_id"] for i in first["contradiction_index"]}
    assert "R0004:F1" in {f["finding_id"] for f in second["validated_findings"]}
    assert "R0004:F1" not in {i["finding_id"] for i in second["contradiction_index"]}
    assert rv["findings"] == [{"code": "UNCITED_CONFLICT"}]                  # the detail round replaces the first
    prov = [json.loads(line) for line in (run.dir / "provenance.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(p.get("tool") == "verification_scope" or "verification_scope" in json.dumps(p) for p in prov)
