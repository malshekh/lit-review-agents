"""Live-CP2 failure shapes reproduced with synthetic metadata; no benchmark or provider calls."""
import csv
import json
from types import SimpleNamespace as NS

import pytest
from litreview import orchestrator as orch, checkpoints, pilot_authorization as pa
from litreview.tools import fulltext
from litreview.tools.literature.base import Record, SearchResult


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(orch.notify, "send", lambda *a, **k: None)
    r = orch.Run("synthetic-cp2")
    r.save_state({"stage": "cp2", "status": "READY", "counters": {}, "execution_mode": "STAGED_PILOT"})
    from corpus_fixture import install
    install(r)
    r.save("spec_approved.json", {"researcher_decision": {"selected_option_id": "P1"}})
    r.save("theme_framework.json", {"primary_themes": [{"theme_id": f"T{i}"} for i in range(1, 6)]})
    r.save("records.json", [
        {"record_id": "R0001", "pmid": "34638842", "pmcid": "PMC8508702", "title": "Synthetic Liu", "abstract": "abstract"},
        {"record_id": "R0002", "pmid": "30771200", "title": "Synthetic Huang", "abstract": "abstract"},
        {"record_id": "R0003", "pmid": "27006494", "title": "Synthetic Lun", "abstract": "abstract"}])
    r.save("qualifications.json", [{"record_id": rec["record_id"], "disposition": "QUALIFIED", "role": "PRIMARY",
        "is_contrary_evidence": rec["record_id"] == "R0002", "themes": [], "flags": []} for rec in r.load("records.json")])
    r.save("search_plan.json", {"citation_expansion_seed_families": []})
    return r


def plan(query="(34638842[PMID] OR 27006494[PMID] OR 30771200[PMID])"):
    return {"query_families": [{"family_id": "QF01", "purpose": "KNOWN_ITEM", "sources": ["pubmed"],
                                "compiled": {"pubmed": query}}]}


def test_fixed_corpus_contrary_seed_cannot_expand(run, monkeypatch):
    calls = []
    monkeypatch.setattr(orch, "expand", lambda *a, **k: calls.append("expansion") or ([], []))
    monkeypatch.setattr(run, "_qualify_pending", lambda: calls.append("screen"))
    assert run.stage_expand(run.state()) == "cp2"
    assert calls == []
    assert len(run.load("records.json")) == 3


@pytest.mark.parametrize("query", ["disulfiram AND glioblastoma", "99999999[PMID]", "34638842[PMID] OR glioblastoma"])
def test_fixed_query_stops_before_retrieval(run, monkeypatch, query):
    calls = []
    monkeypatch.setattr(orch, "search", lambda *a: calls.append(a) or SearchResult("pubmed", "QF01", query, 0, []))
    with pytest.raises(orch.Pause, match="Fixed corpus"):
        run._execute_plan(plan(query), {"pubmed": object()})
    assert calls == []


def test_provider_returned_outsider_never_reaches_screening(run, monkeypatch):
    monkeypatch.setattr(orch, "search", lambda *a: SearchResult("pubmed", "QF01", "q", 1,
                        [Record("pubmed", "Synthetic outsider", pmid="99999999")]))
    with pytest.raises(orch.Pause, match="Fixed corpus"):
        run._execute_plan(plan(), {"pubmed": object()})
    assert run.load("retrieval_boundary_error.json")["unexpected_pmids"] == ["99999999"]
    assert len(run.load("records.json")) == 3


def test_existing_outsider_is_not_screened(run, monkeypatch):
    run.save("records.json", run.load("records.json") + [{"record_id": "R0004", "pmid": "99999999"}])
    calls = []
    monkeypatch.setattr(run, "agent", lambda *a, **k: calls.append(a) or {"qualifications": []})
    with pytest.raises(orch.Pause, match="Fixed corpus"):
        run._qualify_pending()
    assert calls == []


def test_three_existing_qualified_records_survive(run, monkeypatch):
    before = run.load("qualifications.json")
    monkeypatch.setattr(run, "agent", lambda *a, **k: pytest.fail("unnecessary screening call"))
    run._qualify_pending()
    assert run.load("qualifications.json") == before


def test_needs_human_input_blocks_retrieval_and_is_bound(run, monkeypatch):
    proposal = {**plan(), "status": "NEEDS_HUMAN_INPUT", "warnings": ["Synthetic protocol conflict"]}
    monkeypatch.setattr(run, "agent", lambda *a, **k: proposal)
    calls = []
    monkeypatch.setattr(run, "_execute_plan", lambda *a: calls.append(a) or [])
    with pytest.raises(orch.Pause, match="CP_AGENT_REVIEW"):
        run.stage_search(run.state())
    assert not calls
    state = json.loads((run.dir / "checkpoints/CP_AGENT_REVIEW_state.json").read_text())
    decision_path = run.dir / "checkpoints/CP_AGENT_REVIEW_decision.json"
    decision = json.loads(decision_path.read_text())
    decision.update(approve_continue=True, notes="Human resolves synthetic exception; fixed identifiers remain mandatory.")
    decision_path.write_text(json.dumps(decision))
    checkpoints.approve(run.dir, "CP_AGENT_REVIEW", run.prov)
    run._agent_human_review("A03-LM", "PLAN", proposal)
    with pytest.raises(orch.Pause, match="CP_AGENT_REVIEW"):
        run._agent_human_review("A03-LM", "PLAN", {**proposal, "warnings": ["changed"]})
    assert state["fingerprint"] != json.loads((run.dir / "checkpoints/CP_AGENT_REVIEW_state.json").read_text())["fingerprint"]


@pytest.mark.parametrize("returned_id", ["30771200", "R9999"])
def test_record_id_is_not_a_pmid(run, monkeypatch, returned_id):
    run.save("qualifications.json", [])
    monkeypatch.setattr(run, "agent", lambda *a, **k: {"qualifications": [{"record_id": returned_id}]})
    with pytest.raises(orch.Pause, match="identifier integrity"):
        run._qualify_pending()


def test_r0002_canonical_identity_and_all_six_questions_visible(run, monkeypatch):
    run.save("qualifications.json", [])
    seen = []
    questions = [{"record_id": "R0002", "question": f"Synthetic review question {i}"} for i in range(6)]
    def agent(a, payload, **kwargs):
        seen.append(payload)
        return {"status": "COMPLETE_WITH_WARNINGS", "human_review_queue": questions,
                "criteria_defects": [{"defect": "Synthetic scope conflict"}],
                "qualifications": [{"record_id": x["record_id"], "disposition": "QUALIFIED", "themes": [], "flags": []}
                                   for x in payload["records"]]}
    monkeypatch.setattr(run, "agent", agent)
    run._qualify_pending()
    identity = next(x for x in seen[0]["identifier_registry"] if x["record_id"] == "R0002")
    assert identity["pmid"] == "30771200" and identity["in_fixed_corpus"] is True
    with pytest.raises(orch.Pause, match="CP2"):
        run.stage_cp2(run.state())
    review = (run.dir / "checkpoints/CP2_review.md").read_text(encoding="utf8")
    assert all(q["question"] in review for q in questions)
    assert "Synthetic scope conflict" in review and "30771200" in review
    assert "Stage 1-only" in review and "A08-OL" not in review and "OVER_CAP" not in review


def test_cp2_review_requires_disposition_and_preserves_edits(run):
    checkpoints.write_cp2(run.dir, run.load("records.json"), run.load("qualifications.json"), {},
                          review_issues={"human_review_queue": ["synthetic question"]})
    d = run.dir / "checkpoints"
    path = d / "CP2_records.csv"
    rows = list(csv.DictReader(path.open(encoding="utf8")))
    for row in rows: row["select"] = "Y"
    with path.open("w", encoding="utf8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
    with pytest.raises(checkpoints.DecisionIncomplete, match="acknowledge"):
        checkpoints.approve(run.dir, "CP2", run.prov)
    checkpoints.write_cp2(run.dir, run.load("records.json"), run.load("qualifications.json"), {},
                          review_issues={"human_review_queue": ["synthetic question"]})
    assert all(row["select"] == "Y" for row in csv.DictReader(path.open(encoding="utf8")))
    assert list((d / "history/CP2").glob("*/CP2_records.csv"))
    decision = json.loads((d / "CP2_decision.json").read_text())
    decision.update(review_issues_acknowledged=True, notes="Human reviewed all synthetic unresolved questions and source requirements.")
    (d / "CP2_decision.json").write_text(json.dumps(decision))
    checkpoints.approve(run.dir, "CP2", run.prov)


def test_lun_and_huang_never_fetch_fulltext_even_with_pmcid(run, monkeypatch):
    rows = run.load("records.json")[1:]
    for rec in rows:rec["pmcid"] = "PMC-SYNTHETIC"
    run.save("selected_corpus.json", rows)
    monkeypatch.setattr(orch, "fetch_sections", lambda *a: pytest.fail("abstract-only full-text request"))
    calls = []
    monkeypatch.setattr(run, "run_many", lambda a, items, *args: calls.extend(items))
    run.stage_extract(run.state())
    assert len(calls) == 2 and all(payload["content_level"] == "ABSTRACT" for _, payload in calls)


def test_liu_unverified_cache_stops_before_any_extraction(run, monkeypatch):
    run.save("selected_corpus.json", run.load("records.json"))
    run.save("fulltext/R0001.json", {"Abstract": "Synthetic abstract", "Results": "Synthetic body"})
    calls = []
    monkeypatch.setattr(run, "run_many", lambda *a, **k: calls.append(a))
    with pytest.raises(orch.Pause, match="verified full text"):
        run.stage_extract(run.state())
    assert calls == [] and not run.budget.reservations()


def xml(pmid="34638842", body=True):
    figures = ''.join(f'<fig id="ijms-22-10496-f{i:03d}"><label>Figure {i}</label><caption><p>Synthetic legend</p></caption><graphic href="fake{i}.png"/></fig>' for i in range(1,11))
    table = '<table-wrap id="ijms-22-10496-t001"><label>Table 1</label><table><thead><tr><th>Group</th><th>Value</th></tr></thead><tbody><tr><td>Synthetic row</td><td>12.3</td></tr></tbody></table></table-wrap>'
    sections = '<body><sec><title>Methods</title><p>Synthetic methods.</p></sec><sec><title>Results</title><p>Synthetic results.</p>'+table+figures+'</sec><sec><title>Discussion</title><p>Synthetic discussion.</p></sec></body>' if body else ''
    return (f'<article><front><article-meta><article-id pub-id-type="pmid">{pmid}</article-id><article-id pub-id-type="pmc">8508702</article-id><abstract>Synthetic abstract</abstract></article-meta></front>'+sections+'</article>').encode()


@pytest.mark.parametrize("kind", ["http", "xml", "identity", "body"])
def test_liu_missing_or_mismatched_source_fails_before_paid_call(run, monkeypatch, kind):
    run.save("selected_corpus.json", run.load("records.json"))
    response = NS(status_code=404 if kind == "http" else 200,
                  content=b"bad XML" if kind == "xml" else xml("wrong" if kind == "identity" else "34638842", kind != "body"))
    monkeypatch.setattr(fulltext.requests, "get", lambda *a, **k: response)
    calls = []
    monkeypatch.setattr(run, "run_many", lambda *a, **k: calls.append(a))
    with pytest.raises(orch.Pause, match="verified full text"):
        run.stage_extract(run.state())
    assert calls == [] and not run.budget.reservations()


def test_verified_liu_source_cache_resume_and_tampering(run, monkeypatch):
    run.save("selected_corpus.json", run.load("records.json"))
    gets = []
    monkeypatch.setattr(fulltext.requests, "get", lambda *a, **k: gets.append(a) or NS(status_code=200, content=xml()))
    calls = []
    monkeypatch.setattr(run, "run_many", lambda a, items, *args: calls.append(items))
    run.stage_extract(run.state());run.stage_extract(run.state())
    assert len(gets) == 1
    assert calls[0][0][1]["content_level"] == "FULL_TEXT"
    assert all(x[1]["content_level"] == "ABSTRACT" for x in calls[0][1:])
    source = run.load("fulltext_provenance/R0001.json")
    assert source["verified"] and source["pmid"] == "34638842" and source["xml_base64"]
    run.save("fulltext/R0001.json", {"Abstract": "changed", "Results": "changed"})
    with pytest.raises(orch.Pause, match="verified full text"):
        run.stage_extract(run.state())
    assert len(calls) == 2


def test_stage1_cost_display_excludes_manuscript_agents(run):
    checkpoints.write_cp2(run.dir, run.load("records.json"), run.load("qualifications.json"), {})
    run._cp2_costs(run.load("qualifications.json"))
    text = (run.dir / "checkpoints/CP2_review.md").read_text(encoding="utf8")
    assert "A08-OL" not in text and "A10-RV" not in text and "A11-RC" not in text
    assert "Stage 1-only" in text and "WITHIN_CAP" in text


def test_raw_questions_are_not_dropped_from_cp2(run):
    questions = [{"record_id": "R0002", "question": f"Actual-shape synthetic question {i}"} for i in range(6)]
    run.save("screening_review.json", {"B002": {"human_review_queue": questions,
        "criteria_defects": [{"defect": "Synthetic expansion deviation"}]}})
    with pytest.raises(orch.Pause, match="CP2"):
        run.stage_cp2(run.state())
    text = (run.dir / "checkpoints/CP2_review.md").read_text(encoding="utf8")
    assert all(q["question"] in text for q in questions)
    assert "Synthetic expansion deviation" in text


def test_cp2_approval_rejects_changed_source_after_review(run):
    checkpoints.write_cp2(run.dir, run.load("records.json"), run.load("qualifications.json"), {})
    run.save("records.json", run.load("records.json") + [{"record_id": "other", "pmid": "other"}])
    with pytest.raises(checkpoints.DecisionIncomplete, match="inputs changed"):
        checkpoints.approve(run.dir, "CP2", run.prov)


def test_a04_human_pause_resume_preserves_accepted_qualifications(run, monkeypatch):
    run.save("qualifications.json", [])
    calls = []
    def agent(a, payload, **kwargs):
        calls.append(a)
        return {"status": "NEEDS_HUMAN_INPUT", "human_review_queue": [{"record_id": "R0002", "question": "Synthetic concern"}],
                "qualifications": [{"record_id": x["record_id"], "disposition": "QUALIFIED", "themes": [], "flags": []}
                                   for x in payload["records"]]}
    monkeypatch.setattr(run, "agent", agent)
    with pytest.raises(orch.Pause, match="CP_AGENT_REVIEW"):
        run._qualify_pending()
    assert len(run.load("qualifications.json")) == 3
    path = run.dir / "checkpoints/CP_AGENT_REVIEW_decision.json"
    decision = json.loads(path.read_text());decision.update(approve_continue=True, notes="Human resolves all synthetic review concerns within fixed scope.")
    path.write_text(json.dumps(decision))
    checkpoints.approve(run.dir, "CP_AGENT_REVIEW", run.prov)
    run._qualify_pending()
    assert len(calls) == 1 and len(run.load("qualifications.json")) == 3


@pytest.mark.parametrize("tamper", ["identity", "body", "encoding"])
def test_cached_xml_is_revalidated_not_only_trusted_metadata(run, monkeypatch, tamper):
    import base64, hashlib
    record = run.load("records.json")[0]
    monkeypatch.setattr(fulltext.requests, "get", lambda *a, **k: NS(status_code=200, content=xml()))
    sections, source = fulltext.fetch_verified_sections(record)
    raw = xml("wrong") if tamper == "identity" else xml(body=False)
    source["xml_base64"] = "not base64" if tamper == "encoding" else base64.b64encode(raw).decode()
    source["xml_sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(fulltext.FullTextUnavailable):
        fulltext.verify_cached_source(record, sections, source)


def test_liu_fulltext_screening_also_requires_verified_source(run, monkeypatch):
    run.save("qualifications.json", [{"record_id": rec["record_id"],
        "disposition": "UNRESOLVED_FULL_TEXT_REQUIRED" if rec["record_id"] == "R0001" else "QUALIFIED",
        "themes": [], "flags": []} for rec in run.load("records.json")])
    monkeypatch.setattr(fulltext.requests, "get", lambda *a, **k: NS(status_code=200, content=xml("wrong")))
    calls = []
    monkeypatch.setattr(run, "agent", lambda *a, **k: calls.append(a))
    with pytest.raises(orch.Pause, match="verified full text"):
        run._qualify_pending()
    assert calls == []


def test_canonical_huang_cannot_be_classified_outside_fixed_corpus(run, monkeypatch):
    run.save("qualifications.json", [])
    monkeypatch.setattr(run, "agent", lambda *a, **k: {"qualifications": [{"record_id": "R0002",
        "disposition": "EXCLUDED", "exclusion_code": "OUTSIDE_FIXED_CORPUS"}]})
    with pytest.raises(orch.Pause, match="canonical corpus membership"):
        run._qualify_pending()
    assert run.load("screening_review.json")["B001"]["identifier_conflict"]


def test_abstract_access_metadata_does_not_inflate_pilot_projection(run):
    before = pa.project(run, pa.STAGE_1, records=run.load("records.json"))
    rows = run.load("records.json")
    for rec in rows[1:]:rec["pmcid"] = "PMC-SYNTHETIC"
    after = pa.project(run, pa.STAGE_1, records=rows)
    assert before == after


def test_regenerated_cp2_cannot_reuse_old_approval(run):
    checkpoints.write_cp2(run.dir, run.load("records.json"), run.load("qualifications.json"), {})
    d = run.dir / "checkpoints"
    decision = json.loads((d / "CP2_decision.json").read_text())
    (d / "CP2_approved.json").write_text(json.dumps(decision))
    assert checkpoints.approved(run.dir, "CP2")
    checkpoints.write_cp2(run.dir, run.load("records.json"), run.load("qualifications.json"), {},
                          review_issues={"human_review_queue": ["changed substantive question"]})
    assert checkpoints.approved(run.dir, "CP2") is None
    assert list((d / "history/CP2").glob("*/CP2_approved.json"))
