"""Acceptance tests for the A07 synthesis job (bounded calls, runtime coverage ledger)."""
import json

import pytest

from litreview import synthesis_input as si
from litreview.agents import AgentError
from litreview.synthesis_job import JobStopped, Ledger, SynthesisJob

FINDINGS = ["R1:F1", "R1:F2", "R2:F1", "R2:F2", "R3:F1"]
RECORD = {f: f.split(":")[0] for f in FINDINGS}
MANDATORY = {
    "PAPER:R1": {"item_id": "PAPER:R1", "kind": "SELECTED_PAPER", "record_id": "R1", "required_visibility": "CITED"},
    "PAPER:R2": {"item_id": "PAPER:R2", "kind": "SELECTED_PAPER", "record_id": "R2", "required_visibility": "CITED"},
    "CONFLICT:T2:1": {"item_id": "CONFLICT:T2:1", "kind": "CONFLICT", "required_visibility": "NARRATIVE"},
    "MISSING:HUMAN": {"item_id": "MISSING:HUMAN", "kind": "SYSTEM_GAP", "required_visibility": "NARRATIVE"},
}
CFG = {"max_tokens_per_turn": 1000, "context_ceiling_tokens": 100_000, "max_findings_per_group": 10}
PLAN = {"mode": "PLAN", "fivew1h": [], "findings_not_used": [{"finding_id": "R3:F1", "reason": "out of scope"}],
        "groups": [{"group_id": "G1", "kind": "EVIDENCE_GROUNDED_GROUP", "name": "A", "basis": "b",
                    "finding_ids": ["R1:F1", "R1:F2"], "manifest_item_ids": ["PAPER:R1"]},
                   {"group_id": "G2", "kind": "EVIDENCE_GROUNDED_GROUP", "name": "B", "basis": "b",
                    "finding_ids": ["R2:F1", "R2:F2"], "manifest_item_ids": ["PAPER:R2", "CONFLICT:T2:1"]}]}


def prop(pid, assertion, sup=(), con=(), satisfies=(), prominence="NARRATIVE_PRIMARY"):
    return {"proposition_id": pid, "type": "SOURCE_GROUNDED", "assertion": assertion, "prominence": prominence,
            "supporting_finding_ids": list(sup), "conflicting_finding_ids": list(con), "satisfies": list(satisfies)}


G1 = {"propositions": [prop("G1.P1", "Drug X lowers marker Y in vitro", sup=["R1:F1", "R1:F2"], satisfies=["PAPER:R1"])],
      "context_contrasts": [], "findings_context": [], "findings_not_used": []}
# cross-theme contradiction: G2's proposition cites R1:F1 (committed in G1's turn) as conflicting evidence
G2 = {"propositions": [prop("G2.P1", "Marker Y is unchanged in vivo", sup=["R2:F1"], con=["R1:F1"],
                            satisfies=["PAPER:R2", "CONFLICT:T2:1"])],
      "context_contrasts": [], "findings_context": ["R2:F2"], "findings_not_used": []}
FINAL = {"knowledge_gaps": [{"gap_id": "K1", "statement": "No human data", "established_by": [], "satisfies": ["MISSING:HUMAN"]}],
         "proposed_interpretations": [], "thesis_options": [], "beyond_prose_bindings": []}


class Model:
    """Scripted model: returns canned outputs per turn and records what each call was sent."""

    def __init__(self, outputs, fail=None):
        self.outputs, self.fail, self.calls = outputs, fail or {}, []

    def __call__(self, mode, turn, name):
        self.calls.append((name, json.loads(json.dumps(turn))))
        if name in self.fail:
            raise self.fail.pop(name)
        return json.loads(json.dumps(self.outputs[name]))


def job(tmp_path, model, count=lambda t: 1000, cfg=CFG):
    return SynthesisJob(tmp_path / "job", MANDATORY, FINDINGS, RECORD, model, count, cfg)


OUT = {"PLAN": PLAN, "GROUP_G1": G1, "GROUP_G2": G2, "FINAL": FINAL}


def test_complete_job_satisfies_each_item_once_and_accounts_for_every_finding(tmp_path):
    pkg = job(tmp_path, Model(OUT)).run()
    assert pkg["status"] == "COMPLETE" and not pkg["coverage_incomplete_item_ids"]
    by = {c["manifest_item_id"]: c for c in pkg["coverage_realization"]}
    assert by["CONFLICT:T2:1"] == {"manifest_item_id": "CONFLICT:T2:1", "status": "SATISFIED",
                                   "satisfied_by": "G2.P1", "required_visibility": "NARRATIVE"}
    assert by["MISSING:HUMAN"]["satisfied_by"] == "K1"
    assert pkg["finding_dispositions"]["R3:F1"] == ["UNUSED"] and pkg["finding_dispositions"]["R2:F2"] == ["CONTEXT"]
    assert "structural coverage only" in pkg["coverage_note"] and "never a warrant" in pkg["coverage_note"]


def test_cross_theme_contradiction_spanning_turns(tmp_path):
    pkg = job(tmp_path, Model(OUT)).run()
    assert pkg["finding_dispositions"]["R1:F1"] == ["SUPPORTING", "CONFLICTING"]   # used in G1, contradicted in G2
    assert [p["proposition_id"] for p in pkg["propositions"]] == ["G1.P1", "G2.P1"]


def test_later_turns_get_an_index_of_prior_output_not_its_bodies(tmp_path):
    m = Model(OUT)
    job(tmp_path, m).run()
    g2 = dict(m.calls)["GROUP_G2"]
    assert g2["prior_propositions"] == [{"id": "G1.P1", "assertion": "Drug X lowers marker Y in vitro",
                                         "findings": ["R1:F1", "R1:F2"], "group": "G1"}]
    assert "PAPER:R1" not in g2["assigned_item_ids"] + g2["other_pending_item_ids"]   # already satisfied
    assert dict(m.calls)["FINAL"]["pending_item_ids"] == ["MISSING:HUMAN"]


def test_duplicate_claims_ids_and_restatements_are_rejected(tmp_path):
    out = {**OUT, "GROUP_G2": {**G2, "propositions": [
        G2["propositions"][0],
        prop("G2.P2", "Also R1", sup=["R1:F2"], satisfies=["PAPER:R1"]),           # item already satisfied
        prop("G1.P1", "A new claim reusing an ID", sup=["R2:F2"]),                 # duplicate proposition ID
        prop("G2.P3", "Drug X lowers marker Y, in vitro.", sup=["R1:F1"]),        # restates G1.P1
        prop("G2.P4", "A second finding use is fine", sup=["R1:F1", "R2:F1"])]}}  # reusing findings is allowed
    pkg = job(tmp_path, Model(out)).run()
    stats = pkg["job_stats"]
    assert stats["duplicates_rejected"] == 3
    assert {r["proposition_id"]: r["reason"] for r in stats["propositions_rejected"]} == {
        "G1.P1": "duplicate proposition_id", "G2.P3": "restates a committed proposition"}
    assert [p["proposition_id"] for p in pkg["propositions"]] == ["G1.P1", "G2.P1", "G2.P2", "G2.P4"]
    assert {c["manifest_item_id"]: c["satisfied_by"] for c in pkg["coverage_realization"]}["PAPER:R1"] == "G1.P1"


def test_item_covered_nowhere_leaves_the_job_incomplete(tmp_path):
    out = {**OUT, "FINAL": {**FINAL, "knowledge_gaps": []}}
    pkg = job(tmp_path, Model(out)).run()
    assert pkg["status"] == "INCOMPLETE" and pkg["coverage_incomplete_item_ids"] == ["MISSING:HUMAN"]
    assert {c["manifest_item_id"]: c["status"] for c in pkg["coverage_realization"]}["MISSING:HUMAN"] == "PENDING"


def test_structural_check_failure_then_later_satisfaction(tmp_path):
    out = {**OUT,
           "GROUP_G2": {**G2, "propositions": [prop("G2.P1", "Marker Y is unchanged in vivo", sup=["R2:F1"],
                                                    con=["R1:F1"], satisfies=["PAPER:R2", "CONFLICT:T2:1"],
                                                    prominence="DISPLAY")]},          # narrative item, display prominence
           "FINAL": {**FINAL, "propositions": [prop("F.P1", "The in vitro and in vivo results conflict",
                                                    sup=["R2:F1"], con=["R1:F1"], satisfies=["CONFLICT:T2:1"])]}}
    m = Model(out)
    j = job(tmp_path, m)
    j.plan(); j.group(PLAN["groups"][0]); j.group(PLAN["groups"][1])
    assert j.ledger.state()["items"]["CONFLICT:T2:1"] == "FAILED_VALIDATION"
    assert j.ledger.state()["items"]["PAPER:R2"] == "SATISFIED"          # CITED needs no narrative prominence
    j.final()
    assert "CONFLICT:T2:1" in dict(m.calls)["FINAL"]["pending_item_ids"]   # a failed item is offered again
    pkg = j.assemble()
    assert {c["manifest_item_id"]: c["status"] for c in pkg["coverage_realization"]}["CONFLICT:T2:1"] == "SATISFIED"


def test_paper_item_requires_citing_the_paper(tmp_path):
    out = {**OUT, "GROUP_G1": {**G1, "propositions": [prop("G1.P1", "x", sup=["R2:F1"], satisfies=["PAPER:R1"])]}}
    j = job(tmp_path, Model(out))
    j.plan(); j.group(PLAN["groups"][0])
    assert j.ledger.state()["items"]["PAPER:R1"] == "FAILED_VALIDATION"


def test_truncated_turn_is_rejected_and_the_job_resumes_from_the_last_commit(tmp_path):
    m = Model(OUT, fail={"GROUP_G2": AgentError("A07-SYN (x): Output was truncated at max_tokens.")})
    with pytest.raises(JobStopped, match="truncated"):
        job(tmp_path, m).run()
    led = Ledger(tmp_path / "job" / "ledger.jsonl")
    assert led.state()["committed"] == ["PLAN", "GROUP_G1"] and led.state()["turns_rejected"][0]["turn"] == "GROUP_G2"
    assert led.state()["items"]["PAPER:R2"] == "PENDING"                # nothing from the truncated turn counts
    pkg = job(tmp_path, m).run()                                        # resume
    assert [c[0] for c in m.calls] == ["PLAN", "GROUP_G1", "GROUP_G2", "GROUP_G2", "FINAL"]
    assert pkg["status"] == "COMPLETE"


def test_context_ceiling_stops_cleanly_before_the_call(tmp_path):
    m = Model(OUT)
    with pytest.raises(JobStopped, match="exceeds the ceiling"):
        job(tmp_path, m, count=lambda t: 99_500).run()                  # 99,500 + 1,000 > 100,000
    assert m.calls == [] and Ledger(tmp_path / "job" / "ledger.jsonl").state()["turns_rejected"]


def test_peak_projected_context_is_reported(tmp_path):
    pkg = job(tmp_path, Model(OUT), count=lambda t: 5000 + 100 * len(t.get("prior_propositions", []))).run()
    # PLAN, G1 and FINAL carry no prior index; G2 carries one entry: 5,000 + 100 + 1,000 max output
    assert pkg["job_stats"]["peak_projected_tokens"] == 6100


def test_turn_without_commit_marker_is_redone_and_its_effects_never_applied(tmp_path):
    m = Model(OUT)
    j = job(tmp_path, m)
    j.plan()
    j._turn_file("GROUP_G1").write_text(json.dumps(G1), encoding="utf-8")       # crash after writing the turn file,
    j.ledger.append({"event": "TURN_STAGED", "turn": "GROUP_G1", "accepted": ["G1.P1"], "rejected": [],
                     "satisfied": {"PAPER:R1": "G1.P1"}, "failed": [], "duplicates": 0, "finding_uses": []})  # no marker
    assert j.ledger.state()["items"]["PAPER:R1"] == "PENDING"
    j.run()
    assert [c[0] for c in m.calls].count("GROUP_G1") == 1                         # redone once, from scratch


def test_oversized_group_is_split_mechanically(tmp_path):
    plan = {**PLAN, "groups": [{**PLAN["groups"][0], "finding_ids": FINDINGS[:4]}, PLAN["groups"][1]]}
    out = {**OUT, "PLAN": plan, "GROUP_G1.1": G1, "GROUP_G1.2": {**G1, "propositions": []}}
    p = job(tmp_path, Model(out), cfg={**CFG, "max_findings_per_group": 2}).plan()
    assert [(g["group_id"], g["finding_ids"], g["split_from"]) for g in p["groups"][:2]] == [
        ("G1.1", ["R1:F1", "R1:F2"], "G1"), ("G1.2", ["R2:F1", "R2:F2"], "G1")]
    assert p["groups"][1]["manifest_item_ids"] == []                              # items stay with the first part


# ------------------------------------------------------------------ input compaction
def _theme_records():
    return {"T1": {"conflicts": [{"finding_ids": ["R1:F1"]}], "limitations": ["Inspected only the supplied findings."],
                   "warnings": ["R1 and R2 may share a cohort."],
                   "evidence_reach": {"systems_missing": ["HUMAN", "EX_VIVO"], "summary": "s" * 50}},
            "T2": {"conflicts": [], "evidence_reach": {"systems_missing": ["HUMAN"]}}}


def test_manifest_references_theme_records_and_collapses_gaps_reconstructibly():
    corpus = [{"record_id": "R1", "tier": "CORE", "is_contrary_evidence": True}, {"record_id": "R2", "tier": "SUPPORTING"}]
    m = si.build_manifest(corpus, _theme_records(), [])
    by = {x["item_id"]: x for x in m}
    assert by["PAPER:R1"]["required_visibility"] == "NARRATIVE" and by["PAPER:R2"]["required_visibility"] == "CITED"
    assert by["REACH:T1"] == {"item_id": "REACH:T1", "kind": "EVIDENCE_REACH", "theme_record": "T1",
                              "required_visibility": "NARRATIVE"}                   # no copy of the summary
    assert "detail" not in by["CONFLICT:T1:1"] and by["CONFLICT:T1:1"]["theme_record"] == "T1"
    assert by["MISSING:HUMAN"]["occurrence_count"] == 2 and by["MISSING:HUMAN"]["affected_theme_ids"] == ["T1", "T2"]
    originals = sorted(o for x in m if x["kind"] == "SYSTEM_GAP" for o in x["source_occurrence_ids"])
    assert originals == ["MISSING:T1:EX_VIVO", "MISSING:T1:HUMAN", "MISSING:T2:HUMAN"]   # all reconstructible


def test_corpus_sends_each_context_once_without_spans_or_process_notes():
    findings = [{"finding_id": f"R1:F{i}", "record_id": "R1", "span": "quoted", "context_id": "R1:C1",
                 "context": {"species": "mouse"}} for i in (1, 2, 3)]
    c = si.build_corpus({}, [], findings, _theme_records(), [], None)
    assert c["contexts"] == {"R1:C1": {"species": "mouse"}}
    assert all("span" not in f and "context" not in f and f["context_id"] == "R1:C1" for f in c["validated_findings"])
    assert "limitations" not in c["theme_records"]["T1"] and c["theme_records"]["T1"]["warnings"]
    assert list(c) == ["review_spec", "theme_framework", "selected_corpus", "contexts", "validated_findings",
                       "theme_records", "coverage_manifest"]                       # fixed order: stable cached prefix


def test_stage_synthesize_sends_a_byte_identical_corpus_every_call(tmp_path, monkeypatch):
    from litreview import model_record
    from litreview import orchestrator as orch
    from litreview.agents.base import user_parts
    from litreview.llm import anthropic_client
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    r = orch.Run("t")
    r.save_state({"stage": "synthesize", "status": "READY", "counters": {}})
    r.save("spec_approved.json", {"x": 1})
    r.save("selected_corpus.json", [{"record_id": "R1", "tier": "CORE"}, {"record_id": "R2", "tier": "SUPPORTING"},
                                    {"record_id": "R3", "tier": "SUPPORTING"}])
    r.save("validated_findings.json", [{"finding_id": f, "record_id": f.split(":")[0], "themes": ["T2"],
                                        "context_id": f"{f.split(':')[0]}:C1", "context": {"s": 1}, "span": "q"}
                                       for f in FINDINGS])
    r.save("theme_records.json", {"T2": {"conflicts": [{"x": 1}], "evidence_reach": {"systems_missing": ["HUMAN"]}}})
    sent = []

    def fake_run_agent(agent_id, payload, run_dir, step, budget, prov, model=None, schema_file=None):
        sent.append((step, schema_file, model.cache_payload, user_parts(payload, model.cache_payload)[0]["text"]))
        name = step.split("_", 2)[2]
        out = {**OUT, "GROUP_G2": {**G2, "propositions": [prop("G2.P1", "Marker Y is unchanged in vivo", sup=["R2:F1"],
                                                              con=["R1:F1"], satisfies=["PAPER:R2", "CONFLICT:T2:1", "REACH:T2"])]},
               "GROUP_G3": {**G1, "propositions": [prop("G3.P1", "R3 alone", sup=["R3:F1"], satisfies=["PAPER:R3"])]},
               "PLAN": {**PLAN, "findings_not_used": [], "groups": PLAN["groups"] + [
                   {"group_id": "G3", "kind": "EVIDENCE_GROUNDED_GROUP", "name": "C", "basis": "b",
                    "finding_ids": ["R3:F1"], "manifest_item_ids": ["PAPER:R3"]}]}}[name]
        return json.loads(json.dumps(out))
    monkeypatch.setattr(orch, "run_agent", fake_run_agent)
    monkeypatch.setattr(anthropic_client, "count_tokens", lambda *a, **k: 1000)
    assert r.stage_synthesize(r.state()) == "cp3"
    assert len({s[3] for s in sent}) == 1                          # corpus block identical on every call
    assert [s[1] for s in sent] == ["A07-SYN.plan.schema.json", "A07-SYN.group.schema.json",
                                    "A07-SYN.group.schema.json", "A07-SYN.group.schema.json", "A07-SYN.final.schema.json"]
    assert all(s[2] == ("corpus",) for s in sent)
    pkg = r.load("synthesis_package.json")
    assert pkg["status"] == "COMPLETE", pkg["coverage_incomplete_item_ids"]
    tag = sent[0][0].split("_")[1][3:]
    rep = r.load(f"synthesis_job_{tag}/report.json")
    assert rep["status"] == "COMPLETE" and rep["propositions_valid"] == 3


def test_job_resumed_on_an_alternate_after_a_refusal_names_both_models(tmp_path):
    from litreview.agents import RefusalError
    from litreview.checkpoints import write_cp3
    served = {"model": "claude-opus-5"}
    m = Model(OUT, fail={"GROUP_G2": RefusalError("declined", "claude-opus-5", "bio")})
    with pytest.raises(RefusalError):        # a refusal is not a clean stop: the run fails and re-routes
        SynthesisJob(tmp_path / "job", MANDATORY, FINDINGS, RECORD, m, lambda t: 1000, CFG,
                     served_by=lambda: served["model"]).run()
    served["model"] = "claude-sonnet-5-5"   # the next run routes A07 to its alternate and resumes
    pkg = SynthesisJob(tmp_path / "job", MANDATORY, FINDINGS, RECORD, m, lambda t: 1000, CFG,
                       served_by=lambda: served["model"]).run()
    assert pkg["models_by_turn"] == {"PLAN": "claude-opus-5", "GROUP_G1": "claude-opus-5",
                                     "GROUP_G2": "claude-sonnet-5-5", "FINAL": "claude-sonnet-5-5"}
    assert pkg["models"] == ["claude-opus-5", "claude-sonnet-5-5"] and pkg["warnings"][0].startswith("MIXED_MODELS")
    write_cp3(tmp_path, pkg)
    cp3 = (tmp_path / "checkpoints" / "CP3_review.md").read_text(encoding="utf-8")
    assert "produced by more than one model" in cp3 and "- claude-sonnet-5-5: GROUP_G2, FINAL" in cp3
    single = job(tmp_path / "one", Model(OUT)).run()
    assert not any(w.startswith("MIXED_MODELS") for w in single["warnings"])
