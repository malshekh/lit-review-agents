"""Offline structural tests. Fixture outputs do not demonstrate scientific reasoning accuracy."""
import copy
import json
from pathlib import Path

import pytest

from litreview import config, checkpoints
from litreview.provenance import ProvenanceLog
from litreview.synthesis_bounded import RegistrySynthesisJob, AlignmentRequired
from litreview.synthesis_job import JobStopped
from litreview.synthesis_input import build_manifest, build_corpus
from litreview.synthesis_registry import EvidenceRegistry, offline_tokens, canonical, chunks
from litreview.evidence import status_of


def corpus(n=4, per_paper=3):
    records, findings = [], []
    fw = {"version": 1, "primary_themes": [{"theme_id": f"T{i}", "name": f"Mechanism {i}"} for i in range(1, 5)]}
    for i in range(1, n + 1):
        rid = f"R{i:04d}"
        records.append({"record_id": rid, "title": f"Evaluation source {i}", "tier": "CORE",
                        "study_id": "SAME_STUDY" if i <= 2 else None,
                        "cohort_id": "SHARED_COHORT" if i <= 2 else None})
        for j in range(1, per_paper + 1):
            findings.append({"finding_id": f"{rid}:F{j}", "record_id": rid, "primary_theme_id": f"T{(i-1)%4+1}",
                             "themes": [f"T{(i-1)%4+1}"], "subthemes": ["target engagement"],
                             "context_id": f"{rid}:C1", "context": {"evidence_system": "IN_VITRO_CELLULAR", "dose": "1 uM"},
                             "subject": "E1", "object": "E2", "predicate": "DECREASES", "predicate_detail": None,
                             "direction": "DECREASE" if i % 2 else "INCREASE", "polarity": "POSITIVE",
                             "modality": "HEDGED", "assertion_type": "REPORTED_RESULT", "attributed_to": None,
                             "disposition": "SUPPORTED_WITH_CONSTRAINTS", "eligibility": {"status": "SUPPORTING"},
                             "plain_language_limit": f"Evaluation finding {rid}:{j}, cellular only",
                             "constraints": ["No clinical inference", "One specified experimental context"],
                             "span": f"Source text {rid}:{j}"})
    themes = {t["theme_id"]: {"evidence_reach": {"systems_missing": ["HUMAN"]}, "conflicts": []}
              for t in fw["primary_themes"]}
    manifest = build_manifest(records, themes, [])
    c = build_corpus({"topic": "evaluation only"}, records, findings, themes, manifest, fw)
    c["selected_corpus"] = records
    return c


def header(mode):
    return {"agent_id": "A07-SYN", "prompt_version": "1.0", "mode": mode, "status": "COMPLETE",
            "warnings": [], "limitations": []}


class FixtureModel:
    """Mechanical coverage generator, deliberately NOT a scientific synthesizer."""
    def __init__(self, registry):
        self.r, self.calls = registry, []

    def __call__(self, mode, payload, turn):
        self.calls.append((mode, copy.deepcopy(payload), turn))
        out = header(mode)
        if mode == "PLAN":
            return {**out, "theme_change_proposals": [], "scope_drift": [], "fivew1h": []}
        if mode == "GROUP":
            ids = payload["group"]["finding_ids"]
            usable = [f for f in ids if status_of(self.r.findings[f]) == "SUPPORTING"]
            props = [{"type": "SOURCE_GROUNDED", "assertion": f"Evaluation-only assertion {turn}:{k}",
                      "evidence": [{"finding_id": f, "role": "SUPPORTING"} for f in part],
                      "source_item_ids": [], "satisfies": [], "prominence": "NARRATIVE_PRIMARY"}
                     for k, part in enumerate(chunks(usable, 6), 1)]
            appraised = [f for f in ids if status_of(self.r.findings[f]) == "NOT_ESTABLISHED"]
            for k, part in enumerate(chunks(appraised, 6), 1):
                props.append({"type":"CLAIM_APPRAISAL", "assertion":f"Evaluation-only appraisal {turn}:{k}",
                    "evidence":[{"finding_id":f,"role":"SUBJECT_OF_APPRAISAL", "appraisal":{
                        "statement":"Evaluation fixture appraisal", "claim_source_record_id":self.r.record_of[f],
                        "a06_rationale":self.r.findings[f]["plain_language_limit"]}} for f in part],
                    "source_item_ids":[],"satisfies":[],"prominence":"NARRATIVE_PRIMARY"})
            gaps = []
            for iid, source in payload["source_items"].items():
                item = source["item"]
                p = next((p for p in props if any(self.r.record_of[x["finding_id"]] == item.get("record_id")
                                                  for x in p["evidence"])), None)
                if item["kind"] == "SELECTED_PAPER" and p:
                    p["satisfies"].append(iid)
                else:
                    gaps.append({"type": "SYSTEM_GAP", "statement": f"Evaluation-only limitation {iid}",
                                 "source_item_ids": [iid], "established_by": [], "satisfies": [iid]})
            return {**out, "propositions": props, "knowledge_gaps": gaps,
                    "findings_not_used": [{"finding_id":f, "reason":"Evaluation fixture: explicitly unused; no scientific judgment"}
                                          for f in ids if f not in usable and f not in appraised], "retrieval_requests": []}
        if mode == "RECONCILE":
            return {**out, "reviews": [{"proposition_id": p["proposition_id"], "outcome": "NO_CONFLICT_IDENTIFIED",
                                         "rationale": "Mechanical structural fixture, not a scientific judgment"}
                                        for p in payload["focus"]], "issues": [], "retrieval_requests": []}
        return {**out, "thesis_options": [{"option_id": "T1", "type": "ORGANIZING_THESIS", "text": "Evaluation only",
                "title_draft": "Evaluation only", "contribution_statement_draft": "Structural fixture",
                "proposition_ids": [payload["proposition_index"][0]["proposition_id"]]}],
                "proposed_interpretations": [], "beyond_prose_bindings": []}


def job(tmp_path, data=None, model=None, approval=True, **settings):
    r = EvidenceRegistry(data or corpus())
    model = model or FixtureModel(r)
    cfg = {**config.load("pipeline")["synthesis"], **settings}
    return RegistrySynthesisJob(tmp_path / "job", r, model, offline_tokens, cfg,
                                {"prompt": "fixture", "schemas": "fixture"}, lambda *_: approval), model


def test_complete_global_coverage_no_context_disappearance(tmp_path):
    j, m = job(tmp_path)
    pkg = j.run()
    assert pkg["status"] == "COMPLETE"
    assert not pkg["findings_unaccounted"] and not pkg["coverage_incomplete_item_ids"]
    assert all(x["status"] == "SATISFIED" for x in pkg["coverage_realization"])
    assert any(mode == "RECONCILE" for mode, _, _ in m.calls)
    assert pkg["global_independence"]["independent_studies"] is None
    assert pkg["global_independence"]["known_study_ids"] == ["SAME_STUDY"]
    assert pkg["global_independence"]["distinct_explicit_studies"] == 1
    assert pkg["global_independence"]["distinct_explicit_datasets_or_cohorts"] == 1
    for p in pkg["propositions"]:
        assert p["independent_source_count"] is None
        assert all(q["modality"] == "HEDGED" for q in p["evidence_qualifiers"].values())


def test_human_approval_blocks_all_expensive_calls_and_resumes_plan(tmp_path):
    j, m = job(tmp_path, approval=False)
    with pytest.raises(AlignmentRequired):
        j.run()
    assert [x[0] for x in m.calls] == ["PLAN"]
    j.approve = lambda *_: True
    assert j.run()["status"] == "COMPLETE"
    assert sum(x[0] == "PLAN" for x in m.calls) == 1
    before = len(m.calls)
    assert j.run()["status"] == "COMPLETE" and len(m.calls) == before


def test_stale_input_and_tampered_turn_are_rejected(tmp_path):
    j, _ = job(tmp_path)
    j.plan()
    changed = corpus()
    changed["validated_findings"][0]["modality"] = "SPECULATIVE"
    with pytest.raises(JobStopped, match="stale"):
        job(tmp_path, changed)
    path = j._turn_file("PLAN")
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(JobStopped, match="hash"):
        j.plan()


@pytest.mark.parametrize("defect", ["blocked", "unknown", "type", "incomplete", "missing", "source"])
def test_bad_turn_is_never_partially_accepted(tmp_path, defect):
    r = EvidenceRegistry(corpus())
    base = FixtureModel(r)
    def model(mode, payload, turn):
        out = base(mode, payload, turn)
        if mode == "GROUP":
            if defect == "blocked":
                fid = out["propositions"][0]["evidence"][0]["finding_id"]
                r.findings[fid]["disposition"] = "BLOCKED_ALIGNMENT"
            elif defect == "unknown":out["propositions"][0]["evidence"][0]["finding_id"] = "R9999:F1"
            elif defect == "type":out["propositions"][0]["type"] = "NEW_INFERENCE_AS_ESTABLISHED"
            elif defect == "incomplete":out["status"] = "FAILED"
            elif defect == "missing":out.pop("findings_not_used")
            else:out["propositions"][0]["satisfies"] = ["CONFLICT:NONEXISTENT"]
        return out
    j = RegistrySynthesisJob(tmp_path, r, model, offline_tokens, config.load("pipeline")["synthesis"], {}, lambda *_: True)
    with pytest.raises(JobStopped):j.run()
    assert not j.ledger.state()["propositions"]


def test_targeted_retrieval_reaches_another_primary_theme(tmp_path):
    r = EvidenceRegistry(corpus())
    base = FixtureModel(r)
    external = "R0004:F1"
    def model(mode, payload, turn):
        if mode == "GROUP" and payload["group"]["primary_theme_id"] == "T1":
            if not payload["retrieved_evidence"]["findings"]:
                return {**header(mode), "status": "NEEDS_EVIDENCE", "propositions": [], "knowledge_gaps": [],
                        "findings_not_used": [], "retrieval_requests": [{"finding_ids": [external]}]}
            assert payload["retrieved_evidence"]["findings"][0]["finding_id"] == external
            out = base(mode, payload, turn)
            out["propositions"][0]["evidence"].append({"finding_id": external, "role": "CONFLICTING"})
            return out
        return base(mode, payload, turn)
    j = RegistrySynthesisJob(tmp_path, r, model, offline_tokens, config.load("pipeline")["synthesis"], {}, lambda *_: True)
    pkg = j.run()
    assert any(external in p["conflicting_finding_ids"] for p in pkg["propositions"])
    assert r.retrieve([{"query": "R0004:F1"}]) == [external]


def test_global_reconciliation_preserves_both_sides_and_overlap(tmp_path):
    r = EvidenceRegistry(corpus())
    base = FixtureModel(r)
    def model(mode, payload, turn):
        out = base(mode, payload, turn)
        if mode != "RECONCILE":return out
        if not payload["retrieved_evidence"]["findings"]:
            return {**header(mode), "status": "NEEDS_EVIDENCE", "reviews": [], "issues": [],
                    "retrieval_requests": [{"finding_ids": ["R0001:F1", "R0002:F1"]}]}
        ids = [p["proposition_id"] for p in payload["global_proposition_index"][:2]]
        out["issues"] = [{"kind": kind, "proposition_ids": ids, "finding_ids": ["R0001:F1", "R0002:F1"],
                          "limitation": "Opposing directions in shared evidence; unresolved"}
                         for kind in ["UNRESOLVED_CONTRADICTION", "SHARED_EVIDENCE"]]
        for review in out["reviews"]:
            if review["proposition_id"] in ids:review["outcome"] = "ISSUES_IDENTIFIED"
        return out
    j = RegistrySynthesisJob(tmp_path, r, model, offline_tokens, config.load("pipeline")["synthesis"], {}, lambda *_: True)
    pkg = j.run()
    assert len(pkg["reconciliation"]) == 2
    assert all(p["scientific_limitations"] for p in pkg["propositions"][:2])
    assert len(pkg["propositions"]) == 4


def test_admission_stops_before_model_call(tmp_path):
    r = EvidenceRegistry(corpus())
    called = []
    with pytest.raises(JobStopped, match="context"):
        RegistrySynthesisJob(tmp_path, r, lambda *x: called.append(x), lambda x: 9999999,
                             config.load("pipeline")["synthesis"], {}, lambda *_: True)
    assert not called


def test_checkpoint_checks_exact_fingerprint(tmp_path):
    j, _ = job(tmp_path)
    a = {**j.registry.alignment(j.packets), "planning": j.plan(), "fingerprint": j.identity}
    checkpoints.write_synthesis_alignment(tmp_path, j.identity, a)
    path = tmp_path / "checkpoints/CP_SYN_decision.json"
    decision = json.loads(path.read_text())
    decision.update(approve_alignment=True, keep_approved_framework=True)
    path.write_text(json.dumps(decision))
    assert checkpoints.approve(tmp_path, "CP_SYN", ProvenanceLog(tmp_path))["fingerprint"] == j.identity
    decision["fingerprint"] = "stale"
    path.write_text(json.dumps(decision))
    with pytest.raises(checkpoints.DecisionIncomplete):checkpoints.approve(tmp_path, "CP_SYN", ProvenanceLog(tmp_path))


def test_missing_mandatory_coverage_stops_final_and_cp3(tmp_path):
    r = EvidenceRegistry(corpus())
    base = FixtureModel(r)
    def model(mode, payload, turn):
        out = base(mode, payload, turn)
        if mode == "GROUP":
            for p in out["propositions"]:p["satisfies"] = []
            for g in out["knowledge_gaps"]:g["satisfies"] = []
        return out
    j = RegistrySynthesisJob(tmp_path, r, model, offline_tokens, config.load("pipeline")["synthesis"], {}, lambda *_: True)
    with pytest.raises(JobStopped, match="coverage incomplete"):j.run()
    assert j._committed("FINAL") is None and j.assemble()["status"] == "INCOMPLETE"


def test_appraisal_roles_attribution_and_limits_survive(tmp_path):
    data = corpus()
    f = data["validated_findings"][0]
    f.update(disposition="DOES_NOT_ESTABLISH", eligibility={"status":"NOT_ESTABLISHED"},
             modality="REPORTED_BY_OTHERS", attributed_to="Original source, ref 15", assertion_type="AUTHORS_INTERPRETATION")
    j, _ = job(tmp_path, data)
    pkg = j.run()
    p = next(p for p in pkg["propositions"] if p["type"] == "CLAIM_APPRAISAL")
    assert p["evidence"][0]["role"] == "SUBJECT_OF_APPRAISAL"
    q = p["evidence_qualifiers"][f["finding_id"]]
    assert q["modality"] == "REPORTED_BY_OTHERS" and q["attributed_to"] == "Original source, ref 15"


@pytest.mark.parametrize("cause", ["omit_review", "unsupported", "unknown_premise"])
def test_global_reconciliation_and_final_cannot_be_bypassed(tmp_path, cause):
    r = EvidenceRegistry(corpus())
    base = FixtureModel(r)
    def model(mode, payload, turn):
        out = base(mode, payload, turn)
        if mode == "RECONCILE" and cause == "omit_review":out["reviews"] = []
        if mode == "RECONCILE" and cause == "unsupported":
            if not payload["retrieved_evidence"]["findings"]:
                return {**header(mode),"status":"NEEDS_EVIDENCE","reviews":[],"issues":[],
                        "retrieval_requests":[{"finding_ids":["R0001:F1"]}]}
            out["issues"] = [{"kind":"UNSUPPORTED_INTERPRETATION","proposition_ids":[payload["focus"][0]["proposition_id"]],
                              "finding_ids":["R0001:F1"],"limitation":"unsupported hypothesis"}]
        if mode == "FINAL" and cause == "unknown_premise":out["thesis_options"][0]["proposition_ids"] = ["invented"]
        return out
    j = RegistrySynthesisJob(tmp_path, r, model, offline_tokens, config.load("pipeline")["synthesis"], {}, lambda *_: True)
    with pytest.raises(JobStopped):j.run()
    assert j._committed("FINAL") is None


def test_reserved_interactive_call_cannot_cross_absolute_cap(tmp_path):
    from litreview.budget import BudgetTracker, BudgetExceeded
    b = BudgetTracker(tmp_path)
    b.cap = 1
    assert b.reserve("call", 1, "A07-SYN")[0]
    b.ensure_headroom("call")  # the already-admitted call may use its own reservation
    assert not b.reserve("another", .01, "A07-SYN")[0]
    with pytest.raises(BudgetExceeded):b.ensure_headroom()
    b.release("call")
    with pytest.raises(BudgetExceeded):b.ensure_headroom("missing")


@pytest.mark.parametrize("part", ["prompt", "schema", "settings"])
def test_resume_identity_includes_execution_dependencies(tmp_path, part):
    j, _ = job(tmp_path)
    identity = {"prompt":"fixture", "schemas":"fixture"}
    cfg = {**j.cfg}
    if part == "settings":cfg["retrieval_limit"] += 1
    else:identity["schemas" if part == "schema" else part] = "changed"
    with pytest.raises(JobStopped, match="stale"):
        RegistrySynthesisJob(j.dir,j.registry,j.call,j.count,cfg,identity,lambda *_:True)


def test_capacity_report_uses_real_builders_and_admits_all_workloads():
    report = json.loads((Path(__file__).resolve().parents[1]/"docs/a07_capacity_redesign.json").read_text(encoding="utf-8"))
    assert [r["papers"] for r in report["rows"]] == [40,80,120]
    for row in report["rows"]:
        assert row["status"] == "COMPLETE" and row["pending"] == row["unaccounted"] == 0
        assert row["all_requests_admitted"]
        assert row["legacy_same_workload_final_input_upper"] > row["by_mode"]["FINAL"]["input_upper_tokens"]
        for mode, usage in row["by_mode"].items():
            assert usage["output_upper_tokens"] <= usage["output_cap_tokens"]
