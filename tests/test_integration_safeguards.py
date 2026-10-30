"""Task 1 safeguards hold through Task 2's bridge, and the interface conflicts found by integrating them stay fixed.
Offline; evaluation-only fixtures."""
import copy
import json
from pathlib import Path

import pytest

from bridge_fixtures import compact_package, fixture_plan
from litreview import bridge, config
from litreview import orchestrator as orch
from litreview.evidence import status_of
from litreview.scientific_validation import require_package

JOURNAL = config.load("journal_scirev")
BCFG = config.load("pipeline")["bridge"]


@pytest.fixture(scope="module")
def fx():
    data = compact_package(40)
    data["table"] = bridge.comparative_table(data["pkg"], data["findings"], data["corpus"])
    data["plan"], data["ledger"] = fixture_plan(data["pkg"], data["corpus"], data["table"])
    return data


def written_finding(fx):
    els = bridge.elements(fx["pkg"])
    e = next(x["item_id"] for x in fx["ledger"] if x["outcome"] in bridge.WRITTEN and els[x["item_id"]]["kind"] == "PROPOSITION"
             and els[x["item_id"]]["record"]["supporting_finding_ids"])
    return e, els[e]["record"]["supporting_finding_ids"][0]


# ------------------------------------------------------------------ evidence states through the bridge
@pytest.mark.parametrize("change,status", [
    ({"provenance_gate1": {"passed": False}}, "HELD_FOR_CORRECTION"),                   # failed Gate 1 beats A06
    ({"eligibility": {"status": "QUARANTINED", "reason": "pending human review"}}, "QUARANTINED"),
    ({"eligibility": {"status": "REVALIDATION_REQUIRED"}}, "REVALIDATION_REQUIRED"),
    ({"disposition": "BLOCKED_PROVENANCE", "eligibility": None}, "HELD_FOR_CORRECTION")])
def test_ineligible_or_pending_evidence_never_reaches_a_packet_or_the_table(fx, change, status):
    element, fid = written_finding(fx)
    findings = copy.deepcopy(fx["findings"])
    f = next(x for x in findings if x["finding_id"] == fid)
    f.update(change)
    assert status_of(f) == status
    with pytest.raises(ValueError, match="may not serve"):
        require_package(fx["pkg"], findings)                        # CP3's contract refuses it first
    with pytest.raises(bridge.BridgeError, match="no longer eligible"):
        bridge.section_packets(fx["plan"], fx["ledger"], fx["pkg"], findings, fx["corpus"])
    assert fid not in bridge.comparative_table(fx["pkg"], findings, fx["corpus"])["row_finding_ids"]
    with pytest.raises(bridge.BridgeError, match="ineligible"):
        bridge.fulfil_retrieval([{"finding_ids": [fid], "reason": "x"}], fx["pkg"], findings)


def test_the_bridge_stage_refuses_a_package_that_no_longer_meets_its_contract(tmp_path, monkeypatch, fx):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    run = orch.Run("contract")
    _, fid = written_finding(fx)
    findings = copy.deepcopy(fx["findings"])
    next(x for x in findings if x["finding_id"] == fid)["provenance_gate1"] = {"passed": False}
    run.save("synthesis_approved.json", fx["pkg"])
    monkeypatch.setattr(run, "_publishable", lambda n: run.load(n))
    monkeypatch.setattr(run, "_findings", lambda: findings)
    monkeypatch.setattr(run, "agent", lambda *a, **k: pytest.fail("A08 called on a package that fails its contract"))
    run.save_state({"stage": "outline", "status": "READY", "counters": {}})
    with pytest.raises(orch.Pause, match="evidence contract"):
        run.stage_outline(run.state())


def test_fingerprints_constraints_attribution_and_review_status_survive_the_bridge(fx):
    findings = copy.deepcopy(fx["findings"])
    for f in findings:
        f["provenance_gate1"] = {"passed": True, "checks": {"span_found": True}, "source_fingerprint": "src-" + f["finding_id"],
                                 "finding_fingerprint": "fnd-" + f["finding_id"]}
        f["span_corrections"] = [{"original": "a ... b", "replacement": "a x b"}]
    packets = bridge.section_packets(fx["plan"], fx["ledger"], fx["pkg"], findings, fx["corpus"])
    fby = {f["finding_id"]: f for f in findings}
    seen = 0
    for p in packets.values():
        for fid, f in p["findings"].items():
            assert f["provenance_gate1"] == {"passed": True, "source_fingerprint": "src-" + fid, "finding_fingerprint": "fnd-" + fid}
            assert f["span_corrections"] == fby[fid]["span_corrections"]
            for k in ("constraints", "attributed_to", "modality", "eligibility", "plain_language_limit", "context"):
                assert f.get(k) == fby[fid].get(k)
            assert "span" not in f and f["eligibility_status"] == status_of(fby[fid])
            seen += 1
    assert seen
    # the original quotation is supplied when a writer asks for the finding itself
    some = next(fid for p in packets.values() for fid in p["findings"])
    got, _ = bridge.fulfil_retrieval([{"finding_ids": [some], "reason": "quote"}], fx["pkg"], findings)
    assert got[some]["findings"][some]["span"] == fby[some]["span"]


def test_argument_map_lists_the_approved_themes_and_their_subthemes(fx):
    findings = copy.deepcopy(fx["findings"])
    for f in findings:
        f["subthemes"] = [f"sub-{f['record_id']}"]
    amap = bridge.argument_map(fx["pkg"], fx["corpus"], findings)
    approved = [t["theme_id"] for t in fx["pkg"]["theme_framework"]["primary_themes"]]
    assert [t["theme"]["theme_id"] for t in amap["themes"] if t["theme"]["theme_id"] != "UNMAPPED"] == approved
    for t in amap["themes"]:
        expected = {f"sub-{fid.split(':')[0]}" for p in fx["pkg"]["propositions"] if p["primary_theme_id"] == t["theme"]["theme_id"]
                    for fid in bridge._finding_ids(p)}
        assert set(t.get("subthemes", [])) == expected
    assert amap["study_independence"]["papers"] == fx["pkg"]["global_independence"]["papers"]


def test_each_record_keeps_its_study_independence(fx):
    packets = bridge.section_packets(fx["plan"], fx["ledger"], fx["pkg"], fx["findings"], fx["corpus"])
    els = bridge.elements(fx["pkg"])
    for p in packets.values():
        for i, r in bridge.packet_records(p).items():
            if els[i]["kind"] == "PROPOSITION":
                assert r["record"]["independence"] == els[i]["record"]["independence"]


# ------------------------------------------------------------------ A07 gaps established by findings
def test_a_gap_established_by_eligible_findings_meets_the_package_contract(fx):
    pkg = copy.deepcopy(fx["pkg"])
    eligible = next(f["finding_id"] for f in fx["findings"] if status_of(f) == "SUPPORTING")
    rejected = next(f["finding_id"] for f in fx["findings"] if status_of(f) == "REJECTED")
    pkg["knowledge_gaps"][0]["established_by"] = [eligible]          # bounded A07's contract: finding IDs
    require_package(pkg, fx["findings"])
    pkg["knowledge_gaps"][0]["established_by"] = [rejected]
    with pytest.raises(ValueError, match="ineligible finding"):
        require_package(pkg, fx["findings"])
    pkg["knowledge_gaps"][0]["established_by"] = ["R9999:F1"]
    with pytest.raises(ValueError, match="unknown"):
        require_package(pkg, fx["findings"])


# ------------------------------------------------------------------ CP_LEDGER binds the exact plan and ledger
def test_a_ledger_edited_after_approval_cannot_authorize_writing(tmp_path, monkeypatch, fx):
    from litreview import checkpoints
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    run = orch.Run("ledger")
    for n, v in (("synthesis_approved.json", fx["pkg"]), ("selected_corpus.json", fx["corpus"]),
                 ("manuscript_plan.json", fx["plan"]), ("allocation_ledger.json", fx["ledger"])):
        run.save(n, v)
    monkeypatch.setattr(run, "_publishable", lambda n: run.load(n))
    monkeypatch.setattr(run, "_findings", lambda: fx["findings"])
    pv = bridge.plan_version(fx["plan"], fx["ledger"])
    run.save("bridge/plan_check.json", {"plan_version": pv, "problems": []})
    checkpoints.write_ledger_review(run.dir, pv, fx["ledger"], {"counts": {}}, {})
    d = checkpoints.cp_dir(run.dir) / "CP_LEDGER_decision.json"
    d.write_text(json.dumps({"fingerprint": pv, "approve_ledger": True}), encoding="utf-8")
    checkpoints.approve(run.dir, "CP_LEDGER", run.prov)
    assert run._plan_state()["pv"] == pv
    edited = copy.deepcopy(fx["ledger"])
    edited[-1]["reason"] = "changed after approval"
    run.save("allocation_ledger.json", edited)
    with pytest.raises(orch.Pause, match="changed after the bridge checked it"):
        run._plan_state()


# ------------------------------------------------------------------ A10 and the journal's citation rules
def _verify_one(tmp_path, manuscript, verdict_fids):
    from litreview.synthesis_registry import EvidenceRegistry, offline_tokens
    from litreview.verification_job import VerificationJob
    from test_synthesis_bounded import corpus
    from test_verification_job import ScriptedVerifier
    r = EvidenceRegistry(corpus())
    pkg = {"propositions": [{"proposition_id": "P1", "type": "SOURCE_GROUNDED", "assertion": "x",
                             "evidence": [{"finding_id": "R0001:F1", "role": "SUPPORTING"}]}]}
    base = ScriptedVerifier()

    def model(mode, payload, name):
        out = base(mode, payload, name)
        if mode == "LOCAL" and verdict_fids is not None:
            for v in out["verdicts"]:
                v.update(verdict="VERIFIED", evidence_finding_ids=verdict_fids, checks=__import__("litreview.verification_job",
                         fromlist=["CHECKS"]).CHECKS)
        return out
    plan = {"title": {"proposition_ids": ["P1"]}, "abstract_plan": {"ordered_proposition_ids": ["P1"]}}
    return VerificationJob(tmp_path, manuscript, plan, pkg, r, [], config.load("pipeline")["scientific_verification"],
                           model, offline_tokens, {"prompt": "t"}).run()


def test_title_and_abstract_need_no_citation_but_still_need_evidence(tmp_path):
    m = {"title": "A bound title", "abstract": "A bound abstract sentence. ⟦P1⟧", "sections": []}
    rv = _verify_one(tmp_path / "a", m, None)
    assert not [f for f in rv["findings"] if f["code"] == "UNCITED_SCIENTIFIC_ASSERTION"]
    body = {"title": "t", "abstract": "", "sections": [{"section_id": "S1", "heading": "h",
                                                        "text_markdown": "An uncited claim in the body. ⟦P1⟧"}]}
    rv = _verify_one(tmp_path / "b", body, None)
    assert [f for f in rv["findings"] if f["code"] == "UNCITED_SCIENTIFIC_ASSERTION"]   # the body still needs one
    rv = _verify_one(tmp_path / "c", {"title": "Unbound claim", "abstract": "", "sections": []}, [])
    assert [f for f in rv["findings"] if f["code"] in ("UNCITED_SCIENTIFIC_ASSERTION", "UNBACKED_VERIFICATION")]


def test_a_sentence_cannot_bind_more_findings_than_a10_can_verify(fx):
    limit = bridge.max_findings_per_sentence()
    schema = json.loads((Path(bridge.__file__).parents[2] / "schemas" / "A10-RV.bounded.schema.json").read_text())
    assert limit == schema["properties"]["verdicts"]["items"]["properties"]["evidence_finding_ids"]["maxItems"]
    packets = bridge.section_packets(fx["plan"], fx["ledger"], fx["pkg"], fx["findings"], fx["corpus"])
    p = max(packets.values(), key=lambda q: len(q["findings"]))
    records = bridge.packet_records(p)
    ids, n = [], 0
    for i in p["allowed_tags"]:
        ids.append(i)
        if len(bridge.sentence_findings(ids, records)) > limit:
            break
    assert len(bridge.sentence_findings(ids, records)) > limit
    problems = bridge.check_text(f"One sentence for too much evidence. ⟦{','.join(ids)}⟧", p, p["section_id"])
    assert any(x.startswith("TOO_MANY_FINDINGS") for x in problems)


# ------------------------------------------------------------------ the table as A10 and the reader see it
def test_the_reader_table_carries_rows_and_notes_but_no_selection_bookkeeping(fx):
    from litreview.verification_job import inventory
    reader = bridge.reader_table(fx["table"], fx["corpus"])
    assert set(reader) <= {"display_id", "kind", "type", "columns", "rows", "row_finding_ids", "inconsistency_notes", "notes"}
    assert "not a summary of every study" in reader["notes"][0]
    texts = [o["text"] for o in inventory({"sections": []}, [reader])]
    assert not any(t in ("BUILT", "25") or t.startswith("Rows are eligible findings") for t in texts)
    assert sum(1 for t in texts if "⟦" in t) == len(reader["rows"])


# ------------------------------------------------------------------ model windows against the providers
def test_configured_windows_do_not_exceed_what_the_providers_report():
    record = json.loads((Path(__file__).parents[1] / "docs" / "integration_validation" / "model_windows.json").read_text())
    windows = config.load("pipeline")["admission"]["context_windows"]
    for model, m in record["models"].items():
        reported = m.get("max_input_tokens") or m.get("context_length")
        if model in windows and reported:
            assert windows[model] <= reported, model
    assert windows["kimi-k3.1-pro"] == record["models"]["kimi-k3.1-pro"]["context_length"]
