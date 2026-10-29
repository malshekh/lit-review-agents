"""Evidence eligibility: only findings with a supported A06 disposition may be cited, enforced by code at
every point findings are consumed as evidence (A07 job, display tables, A10), independently of entity
normalization."""
import json
from pathlib import Path

import pytest

from litreview import evidence as ev
from litreview import model_record
from litreview import orchestrator as orch
from litreview.synthesis_job import SynthesisJob
from litreview.tools import display_items as di

RUN = Path(__file__).resolve().parents[1] / "runs" / "20261025-100039" / "data"


# ------------------------------------------------------------------ classification
DSF_WRONG = {"entity_id": "E1", "mention": "DSF", "normalization_state": "RESOLVED", "normalized_id": "CHEBI:81585",
             "approved_name": "cis-11-Methyl-2-dodecenoic acid"}
DSF_CU = {"entity_id": "E3", "mention": "DSF–Cu", "normalization_state": "NOT_APPLICABLE", "normalized_id": None}
GROWTH = {"entity_id": "E2", "mention": "growth", "normalization_state": "UNRESOLVED", "normalized_id": None}


def paper(validations, defects, entities=(DSF_WRONG, DSF_CU, GROWTH)):
    findings = [{"finding_id": v["finding_id"], "subject_entity_id": v.pop("_s", "E1"), "object_entity_id": "E2"}
                for v in validations]
    return ({"entities": list(entities), "findings": findings},
            {"validations": validations, "defect_reports": defects})


def test_a_normalization_error_holds_the_finding_and_an_extraction_error_rejects_it():
    ext, val = paper(
        [{"finding_id": "F1", "gate2": "ENTITY_MISMATCH", "disposition": "BLOCKED_ALIGNMENT"},
         {"finding_id": "F2", "gate2": "ENTITY_MISMATCH", "disposition": "BLOCKED_ALIGNMENT", "_s": "E3"},
         {"finding_id": "F3", "gate2": "ENTITY_MISMATCH", "disposition": "BLOCKED_ALIGNMENT"},
         {"finding_id": "F4", "gate2": "STRENGTHENED; ENTITY_MISMATCH", "disposition": "BLOCKED_ALIGNMENT"}],
        [{"finding_id": "F1", "defect_type": "ENTITY_MISMATCH",
          "recorded": "Subject E1 is DSF but resolves to cis-11-Methyl-2-dodecenoic acid"},
         {"finding_id": "F2", "defect_type": "ENTITY_MISMATCH", "recorded": "E3 is DSF co-added with CuSO4"},
         {"finding_id": "F3", "defect_type": "ENTITY_MISMATCH; ATTRIBUTION_MISMATCH", "recorded": "x"}])
    e = ev.annotate_paper(ext, val)
    assert e["F1"]["status"] == "HELD_FOR_CORRECTION" and e["F1"]["basis"] == "inferred"
    assert e["F2"]["status"] == "REJECTED"           # wrong entity chosen by the extraction (R0061 F12)
    assert e["F3"]["status"] == "REJECTED"           # a second mismatch is independent of normalization (R0044 F21)
    assert e["F4"]["status"] == "REJECTED"           # strengthening is an extraction error whatever else is wrong


def test_a06_cause_decides_when_given():
    ext, val = paper([{"finding_id": "F1", "gate2": "ENTITY_MISMATCH", "disposition": "BLOCKED_ALIGNMENT"},
                      {"finding_id": "F2", "gate2": "ENTITY_MISMATCH", "disposition": "BLOCKED_ALIGNMENT"}],
                     [{"finding_id": "F1", "defect_type": "ENTITY_MISMATCH", "cause": "NORMALIZATION"},
                      {"finding_id": "F2", "defect_type": "ENTITY_MISMATCH", "cause": "EXTRACTION",
                       "recorded": "resolves to cis-11-Methyl-2-dodecenoic acid"}])
    e = ev.annotate_paper(ext, val)
    assert e["F1"] == {"status": "HELD_FOR_CORRECTION", "disposition": "BLOCKED_ALIGNMENT",
                       "basis": "A06 defect cause",
                       "reason": "entity identity attached by normalization contradicts the source"}
    assert e["F2"]["status"] == "REJECTED"


def test_normalization_state_never_decides_eligibility():
    """A wrong or ambiguous identifier does not unblock or block a finding: only the disposition does."""
    for state in ("RESOLVED", "AMBIGUOUS", "UNRESOLVED", "CONFLICT"):
        ent = {**DSF_WRONG, "normalization_state": state}
        ext, val = paper([{"finding_id": "F1", "gate2": "ALIGNED", "disposition": "SUPPORTED_WITH_CONSTRAINTS"},
                          {"finding_id": "F2", "gate2": "ALIGNED", "disposition": "DOES_NOT_ESTABLISH"},
                          {"finding_id": "F3", "gate1": "FAILED", "disposition": "BLOCKED_PROVENANCE"},
                          {"finding_id": "F4", "disposition": "HUMAN_REVIEW_REQUIRED"}], [], (ent, DSF_CU, GROWTH))
        e = ev.annotate_paper(ext, val)
        assert [e[f]["status"] for f in ("F1", "F2", "F3", "F4")] == \
            ["SUPPORTING", "NOT_ESTABLISHED", "REJECTED", "UNRESOLVED"]
    assert not ev.can_cite("HELD_FOR_CORRECTION") and not ev.can_cite(None)


@pytest.mark.skipif(not RUN.exists(), reason="run 20261025-100039 not present")
def test_run_20261025_known_errors_stay_rejected_and_normalization_blocks_are_held():
    status = {}
    # the run as validated, before the normalization correction (archived by `litreview renormalize`)
    before = RUN / "renormalization"
    ext_dir, val_dir = ((before / "extractions_before", before / "validations_before") if before.exists()
                        else (RUN / "extractions", RUN / "validations"))
    for p in sorted(ext_dir.glob("*.json")):
        ext = json.loads(p.read_text(encoding="utf-8"))
        val = json.loads((val_dir / p.name).read_text(encoding="utf-8"))
        status.update({f"{ext['record_id']}:{k}": v["status"] for k, v in ev.annotate_paper(ext, val).items()})
    assert status["R0061:F12"] == "REJECTED" and status["R0044:F21"] == "REJECTED"
    held = sorted(k for k, s in status.items() if s == "HELD_FOR_CORRECTION")
    assert len(held) == 27 and {k.split(":")[0] for k in held} == {"R0045", "R0190", "R0238"}
    assert status["R0045:F34"] == "REJECTED"           # entity plus interpretation-as-result: not only normalization


# ------------------------------------------------------------------ A07 job: evidence roles on links
FIDS = ["R0001:F1", "R0001:F2", "R0002:F1", "R0002:F2", "R0003:F1", "R0003:F2", "R0003:F3"]
DISP = {"R0001:F1": "SUPPORTED", "R0001:F2": "BLOCKED_ALIGNMENT", "R0002:F1": "SUPPORTED",
        "R0002:F2": "DOES_NOT_ESTABLISH", "R0003:F1": "HUMAN_REVIEW_REQUIRED", "R0003:F2": "BLOCKED_ALIGNMENT",
        "R0003:F3": "SUPPORTED"}
STORED = {"R0003:F2": {"status": "HELD_FOR_CORRECTION"}, "R0003:F3": {"status": "REVALIDATION_REQUIRED"}}
RATIONALE = "The single-arm data do not establish in vivo efficacy."
RECORDS = {f: {"finding_id": f, "record_id": f[:5], "disposition": d, "plain_language_limit": RATIONALE
               if f == "R0002:F2" else f"limit {f}", "constraints": [], **({"eligibility": STORED[f]} if f in STORED else {})}
           for f, d in DISP.items()}
MANDATORY = {"PAPER:R0001": {"item_id": "PAPER:R0001", "kind": "SELECTED_PAPER", "record_id": "R0001",
                             "required_visibility": "CITED"}}
CFG = {"max_tokens_per_turn": 1000, "context_ceiling_tokens": 100_000, "max_findings_per_group": 10}


def link(fid, role, **appraisal):
    x = {"finding_id": fid, "role": role}
    if appraisal:
        x["appraisal"] = appraisal
    return x


def appraisal_link(fid="R0002:F2", record="R0002", rationale=RATIONALE, statement="R0002 claimed efficacy in vivo"):
    return link(fid, "SUBJECT_OF_APPRAISAL", statement=statement, claim_source_record_id=record, a06_rationale=rationale)


def prop(pid, *links, type_="SOURCE_GROUNDED", satisfies=()):
    return {"proposition_id": pid, "type": type_, "assertion": f"assertion {pid}", "prominence": "NARRATIVE_PRIMARY",
            "evidence": list(links), "satisfies": list(satisfies)}


def run_job(tmp_path, props, gaps=()):
    out = {"PLAN": {"groups": [{"group_id": "G1", "kind": "EVIDENCE_GROUNDED_GROUP", "finding_ids": FIDS,
                                "manifest_item_ids": ["PAPER:R0001"]}], "findings_not_used": []},
           "GROUP_G1": {"propositions": props}, "FINAL": {"knowledge_gaps": list(gaps)}}
    job = SynthesisJob(tmp_path / "job", MANDATORY, FIDS, {f: f[:5] for f in FIDS},
                       lambda mode, turn, name: json.loads(json.dumps(out[name])), lambda t: 1000, CFG,
                       findings=RECORDS)
    pkg = job.run()
    return pkg, {r["proposition_id"]: r["reason"] for r in pkg["job_stats"]["propositions_rejected"]}


def test_blocked_and_not_established_findings_cannot_support_or_conflict(tmp_path):
    pkg, why = run_job(tmp_path, [
        prop("P1", link("R0001:F2", "SUPPORTING"), satisfies=["PAPER:R0001"]),          # blocked as support
        prop("P2", link("R0002:F1", "SUPPORTING"), link("R0002:F2", "CONFLICTING")),     # DNE as conflict
        prop("P3", link("R0001:F1", "SUPPORTING"), satisfies=["PAPER:R0001"])],
        gaps=[{"gap_id": "K1", "established_by": ["R0001:F2"]}, {"gap_id": "K2", "established_by": ["P3"]}])
    assert [p["proposition_id"] for p in pkg["propositions"]] == ["P3"]
    assert "R0001:F2 (REJECTED, BLOCKED_ALIGNMENT) may not serve as SUPPORTING" in why["P1"]
    assert "R0002:F2 (NOT_ESTABLISHED, DOES_NOT_ESTABLISH) may not serve as CONFLICTING" in why["P2"]
    assert "K1" in why and [g["gap_id"] for g in pkg["knowledge_gaps"]] == ["K2"]
    assert pkg["coverage_realization"][0]["satisfied_by"] == "P3"         # P1's claim on the item never counted
    assert pkg["finding_dispositions"]["R0001:F2"] == ["NOT_CITABLE"]     # accounted for, not UNACCOUNTED
    assert pkg["finding_dispositions"]["R0001:F1"] == ["SUPPORTING"]


def test_rejected_unresolved_held_and_revalidation_findings_serve_in_no_role(tmp_path):
    bad = {"R0001:F2": "REJECTED", "R0003:F1": "UNRESOLVED", "R0003:F2": "HELD_FOR_CORRECTION",
           "R0003:F3": "REVALIDATION_REQUIRED"}
    props = []
    for n, (fid, status) in enumerate(bad.items()):
        props += [prop(f"S{n}", link("R0001:F1", "SUPPORTING"), link(fid, "SUPPORTING")),
                  prop(f"C{n}", link("R0001:F1", "SUPPORTING"), link(fid, "CONFLICTING")),
                  prop(f"A{n}", link("R0001:F1", "SUPPORTING"), appraisal_link(fid, fid[:5]))]
    pkg, why = run_job(tmp_path, props)
    assert pkg["propositions"] == []
    for n, (fid, status) in enumerate(bad.items()):
        for role, pid in (("SUPPORTING", f"S{n}"), ("CONFLICTING", f"C{n}"), ("SUBJECT_OF_APPRAISAL", f"A{n}")):
            assert f"{fid} ({status}" in why[pid] and f"may not serve as {role}" in why[pid]


def test_an_appraisal_subject_cannot_support_a_biological_proposition(tmp_path):
    pkg, why = run_job(tmp_path, [prop("P1", appraisal_link()),                                   # appraisal only
                                  prop("P2", link("R0002:F2", "SUPPORTING"))])                    # DNE as support
    assert pkg["propositions"] == []
    assert "appraised claims never support a proposition" in why["P1"]
    assert "may not serve as SUPPORTING" in why["P2"]


def test_one_proposition_holds_support_and_a_separately_attributed_appraisal(tmp_path):
    pkg, why = run_job(tmp_path, [
        prop("P1", link("R0001:F1", "SUPPORTING"), link("R0002:F1", "CONFLICTING"), appraisal_link()),
        prop("P2", appraisal_link(), type_="CLAIM_APPRAISAL")])
    assert why == {}
    p1 = next(p for p in pkg["propositions"] if p["proposition_id"] == "P1")
    assert (p1["supporting_finding_ids"], p1["conflicting_finding_ids"], p1["appraised_finding_ids"]) == \
        (["R0001:F1"], ["R0002:F1"], ["R0002:F2"])                       # appraisal never enters the support lists
    assert pkg["finding_dispositions"]["R0002:F2"] == ["APPRAISED"]


def test_an_appraisal_must_be_attributed_and_quote_a06(tmp_path):
    pkg, why = run_job(tmp_path, [
        prop("P1", appraisal_link(record="R0001"), type_="CLAIM_APPRAISAL"),            # wrong source record
        prop("P2", appraisal_link(rationale="The data are weak."), type_="CLAIM_APPRAISAL"),   # not A06's words
        prop("P3", appraisal_link(statement=""), type_="CLAIM_APPRAISAL"),             # no appraisal statement
        prop("P4", link("R0001:F1", "SUPPORTING"), type_="CLAIM_APPRAISAL"),           # appraisal type, no subject
        prop("P5", link("R0001:F1", "SUPPORTING"), link("R0001:F1", "CONFLICTING"))])  # one finding, two roles
    assert pkg["propositions"] == []
    assert "must name the record that made the claim (R0002)" in why["P1"]
    assert "quote A06's plain_language_limit" in why["P2"]
    assert "without an appraisal statement" in why["P3"]
    assert "needs a SUBJECT_OF_APPRAISAL link" in why["P4"]
    assert "linked twice" in why["P5"]


def test_older_parallel_lists_are_read_as_roles_and_must_agree_with_links(tmp_path):
    old = {"proposition_id": "P1", "type": "SOURCE_GROUNDED", "assertion": "a", "supporting_finding_ids": ["R0001:F1"],
           "conflicting_finding_ids": ["R0002:F1"], "satisfies": []}
    clash = {**prop("P2", link("R0001:F1", "SUPPORTING")), "supporting_finding_ids": ["R0002:F1"]}
    pkg, why = run_job(tmp_path, [old, clash])
    assert [p["proposition_id"] for p in pkg["propositions"]] == ["P1"]
    assert [x["role"] for x in pkg["propositions"][0]["evidence"]] == ["SUPPORTING", "CONFLICTING"]
    assert "disagree" in why["P2"]


# ------------------------------------------------------------------ display tables
def test_display_tables_never_render_a_finding_that_may_not_be_cited():
    synth = {"propositions": [{"proposition_id": "P1", "supporting_finding_ids": ["R0001:F1", "R0001:F2", "R0003:F3"]}]}
    findings = [RECORDS[f] for f in ("R0001:F1", "R0001:F2", "R0003:F3")]
    rows, left_out = di.evidence_rows({"source_proposition_ids": ["P1"]}, synth, findings, [{"record_id": "R0001"}])
    assert [r["finding_id"] for r in rows] == ["R0001:F1"]
    assert left_out == ["R0001:F2 (not citable: REJECTED, BLOCKED_ALIGNMENT)",
                        "R0003:F3 (not citable: REVALIDATION_REQUIRED, SUPPORTED)"]


# ------------------------------------------------------------------ A10
PKG = {"propositions": [{"proposition_id": "P1", "supporting_finding_ids": ["R0001:F2"]},
                        {"proposition_id": "P2", "supporting_finding_ids": ["R0001:F1", "R0002:F2"]},
                        {"proposition_id": "P3", "supporting_finding_ids": ["R0001:F1"]},
                        {"proposition_id": "P4", "type": "SOURCE_GROUNDED",
                         "evidence": [link("R0001:F1", "SUPPORTING"), appraisal_link()]}],
       "knowledge_gaps": [{"gap_id": "K1", "established_by": ["P1"]}]}
FINDINGS = [{**r, "span": "s"} for r in RECORDS.values()]


def manuscript(text):
    return {"sections": [{"section_id": "S1", "text_markdown": text}]}


def test_code_flags_claims_resting_on_blocked_evidence():
    flags = ev.claims_on_ineligible_evidence(
        manuscript("Only blocked ⟦P1⟧. Mixed ⟦P2⟧. Clean ⟦P3⟧. A gap on P1 ⟦K1⟧. Organizing ⟦ORG⟧."), PKG, FINDINGS)
    by = {tuple(f["item_ids"]): f for f in flags}
    assert set(by) == {("P1",), ("P2",), ("K1",)}
    assert by[("P1",)]["code"] == "SUPPORTED_ONLY_BY_INELIGIBLE_EVIDENCE" and by[("P1",)]["severity"] == "BLOCKING"
    assert by[("K1",)]["severity"] == "BLOCKING"               # a gap resting on P1 rests on blocked evidence
    assert by[("P2",)]["code"] == "INELIGIBLE_EVIDENCE_CITED" and by[("P2",)]["citable_supporting"] == ["R0001:F1"]


def test_a_final_approval_cannot_survive_a_claim_on_blocked_evidence():
    flags = ev.claims_on_ineligible_evidence(manuscript("Only blocked ⟦P1⟧."), PKG, FINDINGS)
    rv = ev.apply_to_verification({"findings": [], "finding_severity": "NONE", "release_disposition": "APPROVED"},
                                  flags, "FINAL")
    assert rv["release_disposition"] == "HOLD_FOR_UPSTREAM_REVIEW" and rv["finding_severity"] == "BLOCKING"
    assert rv["findings"][0]["code"] == "SUPPORTED_ONLY_BY_INELIGIBLE_EVIDENCE"
    assert rv["findings"][0]["source"] == "CODE" and rv["findings"][0]["responsible_stage"] == "A7-SYN"
    clean = {"findings": [], "release_disposition": "APPROVED"}
    assert ev.apply_to_verification(clean, [], "FINAL") is clean


SENTENCE = "DSF/Cu reduced viability [@R0001], and R0002 reported in vivo efficacy that its data do not establish ⟦P4⟧."


def test_each_appraisal_binding_is_listed_for_a10():
    flags, bindings = ev.verification_bindings(manuscript(SENTENCE), PKG, FINDINGS)
    assert flags == []
    assert [(b["binding_id"], b["finding_id"], b["claim_source_record_id"], b["a06_rationale"]) for b in bindings] == \
        [("AB1", "R0002:F2", "R0002", RATIONALE)]


def test_a10_rejects_a_sentence_promoting_an_appraised_claim():
    _, bindings = ev.verification_bindings(manuscript(SENTENCE), PKG, FINDINGS)
    approved = {"findings": [], "finding_severity": "NONE", "release_disposition": "APPROVED"}
    promoted = ev.apply_to_verification({**approved, "appraisal_checks": [
        {"binding_id": "AB1", "preserved": False, "rationale": "stated as established in vivo efficacy"}]},
        [], "FINAL", bindings)
    assert [f["code"] for f in promoted["findings"]] == ["APPRAISED_CLAIM_PROMOTED"]
    assert promoted["finding_severity"] == "BLOCKING" and promoted["release_disposition"] == "HOLD_FOR_REVISION"
    # A10 raising it itself at a lower severity: the floor holds, and it is not duplicated
    own = ev.apply_to_verification({**approved, "appraisal_checks": [{"binding_id": "AB1", "preserved": False}],
                                    "findings": [{"code": "APPRAISED_CLAIM_PROMOTED", "severity": "MINOR",
                                                  "location": {"sentence_excerpt": bindings[0]["sentence_excerpt"]}}]},
                                   [], "FINAL", bindings)
    assert [(f["code"], f["severity"]) for f in own["findings"]] == [("APPRAISED_CLAIM_PROMOTED", "BLOCKING")]
    # no verdict at all: not verified, so not approved
    silent = ev.apply_to_verification(approved, [], "FINAL", bindings)
    assert silent["release_disposition"] == "INCOMPLETE_VERIFICATION" and silent["appraisal_bindings_unchecked"] == ["AB1"]
    kept = {**approved, "appraisal_checks": [{"binding_id": "AB1", "preserved": True}]}
    assert ev.apply_to_verification(kept, [], "FINAL", bindings) is kept


def test_verify_merges_the_code_flags_whatever_a10_concludes(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    run = orch.Run("t")
    run.save_state({"stage": "draft", "status": "READY", "counters": {}})
    run.save("manuscript_plan.json", {"sections": []})
    run.save("synthesis_approved.json", PKG)
    run.save("validated_findings.json", [{k: v for k, v in f.items() if k != "eligibility"} for f in FINDINGS])
    monkeypatch.setattr(run, "_deterministic_report", lambda m: {})
    run.budget.record("A09-WRI", "anthropic", "m", 10, 10, step="A09-WRI_draft1")
    (run.dir / "outputs").mkdir(parents=True, exist_ok=True)
    (run.dir / "outputs" / "A09-WRI_draft1.json").write_text("{}")
    sent = []
    from test_verification_job import ScriptedVerifier
    base=ScriptedVerifier()

    def agent(agent_id, payload, step, **kw):
        sent.append(payload)
        out=base(payload['mode'],payload,step)
        for verdict in out['verdicts']:
            for appraisal in verdict['appraisal_checks']:appraisal['preserved']=False
        return out
    monkeypatch.setattr(run, "agent", agent)
    rv = run._verify(manuscript("Only blocked ⟦P1⟧. " + SENTENCE), "FINAL", "A10-RV_final")
    status = {f["finding_id"]: f["eligibility"]["status"] for f in sent[0]["findings"]}
    assert status == {"R0001:F2": "REJECTED", "R0001:F1": "SUPPORTING", "R0002:F2": "NOT_ESTABLISHED"}
    assert rv["release_disposition"] == "HOLD_FOR_REVISION"
    assert {"INELIGIBLE_EVIDENCE_CITED", "APPRAISED_CLAIM_PROMOTED"} <= {f["code"] for f in rv["findings"]}
    saved = json.loads((run.dir / "data" / "validated_findings.json").read_text(encoding="utf-8"))
    assert all("eligibility" in f for f in saved)
