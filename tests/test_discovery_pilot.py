"""The discovery pilot: an outline without a corpus; the pipeline finds, screens, proposes and freezes 7 papers."""
import csv
import json

import pytest

from litreview import config, model_record, run_spec
from litreview import orchestrator as orch
from litreview.paths import REPO_ROOT

OUTLINE = json.loads((REPO_ROOT / "docs" / "pilot7" / "outline.json").read_text(encoding="utf-8"))


def test_the_pilot_outline_is_valid_and_its_subsections_become_the_themes():
    summary = run_spec.check_outline(OUTLINE, {"max_papers": 7})
    assert summary["word_budget"] == 1600 and summary["mode"] == "DISCOVERY"
    fw = run_spec.framework_from_outline(OUTLINE)
    assert [t["outline_section_id"] for t in fw["primary_themes"]] == ["S1.1", "S1.2", "S1.3", "S1.4", "S2.1", "S2.2", "S2.3", "S2.4"]
    t5 = fw["primary_themes"][4]
    assert "What drug-related information" in t5["scope"] and "synthetic-fluid performance" in t5["excludes"]
    assert [c["word_budget"] for c in run_spec.chapters(OUTLINE)] == [800, 800]
    bad = json.loads(json.dumps(OUTLINE))
    bad["sections"][1]["word_budget"] = 700
    with pytest.raises(run_spec.SpecError, match="a chapter budget includes its subsections"):
        run_spec.check_outline(bad, {})


def test_the_profile_overrides_reach_only_its_own_run():
    eff = config.effective("pilot7")
    assert eff["run_spec"]["max_papers"] == 7 and eff["loops"]["max_critique_cycles"] == 2
    assert eff["extraction"]["full_text_tiers"] is None and eff["retrieval"]["max_records_total"] == 150
    assert eff["retrieval"]["citation_expansion"]["directions"] == ["references", "citations"]   # merged, not replaced
    base = config.load("pipeline")
    assert base["run_spec"]["max_papers"] == 15 and base["loops"]["max_critique_cycles"] == 1           # untouched


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    monkeypatch.setattr(orch.notify, "send", lambda *a, **k: False)
    run_id = orch.new_run("AI-enabled nanobiosensing", outline=OUTLINE, corpus_mode="OPEN_CORPUS", profile="pilot7")
    return orch.Run(run_id)


def test_a_discovery_run_has_the_outline_no_corpus_and_its_profile(run):
    assert run.cfg["run_spec"]["max_papers"] == 7 and run.budget.cap == 65.0
    spec = json.loads((run.dir / "input" / "run_spec.json").read_text())
    assert spec["mode"] == "DISCOVERY" and spec["max_papers"] == 7
    assert run_spec.load(run.dir) == (OUTLINE, None)
    policy = json.loads((run.dir / "input" / "corpus_policy.json").read_text())
    assert policy["mode"] == "OPEN_CORPUS" and policy["broad_discovery"] is True
    assert (run.dir / "input" / "seeds.txt").read_text() == ""            # nothing researcher-selected
    assert run._outline_input()["researcher_outline"]["sections"][1]["questions"][0].startswith("How are computational")


def test_scope_uses_the_outline_framework_and_keeps_a02s_proposal_for_the_record(run, monkeypatch):
    seen = {}

    def agent(agent_id, payload, step, **k):
        seen.update(payload)
        return {"status": "COMPLETE", "theme_framework": {"primary_themes": [{"theme_id": "T1", "name": "A02 idea"}]}}
    monkeypatch.setattr(run, "agent", agent)
    run.save_state({**run.state(), "stage": "scope"})
    assert run.stage_scope(run.state()) == "cp1"
    spec = run.load("spec.json")
    assert seen["researcher_outline"]["review_question"].startswith("How does AI contribute")
    assert spec["theme_framework_proposed_by_A02"]["primary_themes"][0]["name"] == "A02 idea"
    assert len(spec["theme_framework"]["primary_themes"]) == 8


def _records(n=12):
    recs = []
    for i in range(1, n + 1):
        recs.append({"record_id": f"R{i:04d}", "pmid": str(40000000 + i), "doi": f"10.1000/p{i}", "title": f"Study {i} of sensing",
                     "abstract": f"Abstract {i}.", "year": 2020 + i % 5, "pmcid": f"PMC{i}" if i % 2 else None})
    recs.append({**recs[0], "record_id": "R0099", "doi": "10.1101/preprint1", "pmid": None})   # a preprint version of R0001
    return recs


def _quals(records):
    themes = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]
    out = []
    for i, r in enumerate(records):
        out.append({"record_id": r["record_id"], "disposition": "QUALIFIED" if i < 10 else "EXCLUDED",
                    "proposed_tier": "CORE" if i < 4 else "SUPPORTING", "themes": [themes[i % 8]],
                    "reason": f"addresses {themes[i % 8]}", "is_contrary_evidence": i == 6, "flags": []})
    return out


def test_the_proposal_covers_the_subsections_includes_contrary_evidence_and_ignores_access():
    records = _records()
    proposal = run_spec.propose_selection(_quals(records), records, run_spec.framework_from_outline(OUTLINE), 7)
    ids = [p["record_id"] for p in proposal]
    assert len(ids) == 7 and ids[0] == "R0007" and "contrary evidence" in proposal[0]["reason"]
    assert "R0099" not in ids                                                   # one version of a publication
    assert {r["record_id"] for r in records if not r.get("pmcid")} & set(ids)   # abstract-only papers are proposed too
    assert all("covers T" in p["reason"] for p in proposal)


def _at_cp2(run, records):
    run.save("records.json", records)
    run.save("qualifications.json", _quals(records))
    run.save("theme_framework.json", orch.theme_framework.create(run_spec.framework_from_outline(OUTLINE)["primary_themes"], "outline", "CP1"))
    run.save("bias_report.json", {})
    run.save_state({**run.state(), "stage": "cp2"})


def test_cp2_prefills_the_proposal_and_refuses_more_than_seven_or_two_versions(run, monkeypatch):
    records = _records()
    _at_cp2(run, records)
    monkeypatch.setattr(run, "_cp2_costs", lambda q: None)
    with pytest.raises(orch.Pause, match="waiting for CP2"):
        run.stage_cp2(run.state())
    cp = orch.checkpoints.cp_dir(run.dir)
    rows = list(csv.DictReader(open(cp / "CP2_records.csv", encoding="utf-8")))
    marked = [r["record_id"] for r in rows if r["select"] == "Y"]
    assert len(marked) == 7 and all(r["proposed_reason"] for r in rows if r["select"] == "Y")
    assert "Proposed selection" in (cp / "CP2_review.md").read_text(encoding="utf-8")
    decision = {"selected_record_ids": marked + ["R0010"], "tier_overrides": {}}
    with pytest.raises(orch.Pause, match="selects 8 papers; this run allows at most 7"):
        run._freeze_discovered_corpus(decision, {r["record_id"]: r for r in records}, {q["record_id"]: q for q in _quals(records)})
    with pytest.raises(orch.Pause, match="versions of one publication"):
        run._freeze_discovered_corpus({"selected_record_ids": ["R0001", "R0099"]}, {r["record_id"]: r for r in records},
                                      {q["record_id"]: q for q in _quals(records)})


def test_the_approved_selection_is_frozen_as_the_corpus_manifest(run):
    records = _records()
    _at_cp2(run, records)
    by_id = {r["record_id"]: r for r in records}
    quals = {q["record_id"]: q for q in _quals(records)}
    chosen = ["R0001", "R0002", "R0003", "R0007"]
    m = run._freeze_discovered_corpus({"selected_record_ids": chosen, "review_fingerprint": "fp"}, by_id, quals)
    assert m["generated_from"] == "DISCOVERY_AND_SCREENING" and [p["record_id"] for p in m["papers"]] == chosen
    p1, p2 = m["papers"][0], m["papers"][1]
    assert (p1["intended_reading_level"], p2["intended_reading_level"]) == ("FULL_TEXT", "ABSTRACT")   # expected, from the PMCID
    assert p1["informs_sections"] == ["S1.1"] and p1["actual_access"] is None and p1["selection_reason"]
    decision = [e for e in run.prov.events() if e.get("checkpoint") == "CORPUS_FROZEN"]
    assert decision and decision[0]["decision"]["papers"] == chosen
    with pytest.raises(orch.Pause, match="frozen at an earlier CP2"):
        run._freeze_discovered_corpus({"selected_record_ids": ["R0001", "R0004"]}, by_id, quals)
    assert run._freeze_discovered_corpus({"selected_record_ids": chosen}, by_id, quals)["papers"] == m["papers"]


def test_retrieval_is_logged_and_a_failure_is_a_limitation_not_an_exclusion(run, monkeypatch):
    from litreview.tools import fulltext
    monkeypatch.setattr(fulltext, "find_pmcid", lambda pmid, doi: (None, "no PMC copy listed for this identifier"))

    def fetch(rec):
        if rec["pmcid"] == "PMC1":
            return {"Abstract": "a", "Results": "b", "Figure legend Figure 1": "c"}, {"verified": True}
        raise orch.FullTextUnavailable("Full-text body missing")
    monkeypatch.setattr(orch, "fetch_verified_sections", fetch)
    ok = {"record_id": "R0001", "pmid": "1", "pmcid": "PMC1", "abstract": "a", "manifest_paper_id": "P01", "tier": "CORE"}
    sections, access = run._retrieve_discovered(ok)
    assert access["level"] == "FULL_TEXT" and access["figures_inspected"] and not access["supplements_inspected"]
    failed = {**ok, "record_id": "R0003", "pmcid": "PMC3", "abstract": "only the abstract"}
    sections, access = run._retrieve_discovered(failed)
    assert sections == {"Abstract": "only the abstract"} and access["level"] == "ABSTRACT"
    none = {**ok, "record_id": "R0002", "pmcid": None}
    run._retrieve_discovered(none)
    log = run.load("retrieval_log.json")
    assert log["R0001"]["category"] == "FULL_TEXT_RETRIEVED"
    assert log["R0003"]["category"] == "RETRIEVAL_LIMITATION_ABSTRACT_ONLY"
    assert log["R0003"]["attempts"][-1] == {"source": "PMC open-access XML", "outcome": "FAILED", "detail": "Full-text body missing"}
    assert log["R0002"]["attempts"][0]["outcome"] == "NOT_FOUND"
    with pytest.raises(orch.Pause, match="no full text and no abstract"):
        run._retrieve_discovered({**none, "record_id": "R0005", "abstract": ""})
    assert run.load("retrieval_log.json")["R0005"]["category"] == "NO_SOURCE_TEXT"


def test_chapter_lengths_are_measured_against_the_outline():
    from litreview.tools import compliance
    sections = [{"section_id": "S1.1", "text_markdown": "word " * 200}, {"section_id": "S1.2", "text_markdown": "word " * 600},
                {"section_id": "S2.1", "text_markdown": "word " * 300}]
    rep = run_spec.chapter_word_report(OUTLINE, sections, compliance.word_count)
    assert rep[0]["written"] == 800 and rep[0]["within_tolerance"]
    assert rep[1]["written"] == 300 and not rep[1]["within_tolerance"] and rep[1]["by_subsection"]["S2.1"] == 300


def test_cp2_projection_prices_verification_for_the_outline_and_caps_every_stage(run, monkeypatch):
    """Found by the rehearsal: A10 was priced for a 5,000-word manuscript, and the per-paper lines (named by work, not
    by agent) left extraction and validation without a sub-cap."""
    from litreview.tools import cost_projection
    sel = [{"record_id": f"R{i:04d}", "pmcid": f"PMC{i}" if i < 7 else None} for i in range(1, 8)]
    proj = cost_projection.for_selection(cost_projection.load_rates(), sel, run.dir, run.budget, run.route, run.cfg)
    a10 = next(x for x in proj["lines"] if x["stage"] == "A10-RV")
    assert "scaled to the outline's 1,600 words" in a10["detail"] and a10["usd"] < 20
    run._derive_stage_caps(proj)
    caps = run.load("stage_caps.json")["caps_usd"]
    assert "A05-A06" in caps and caps["A05-A06"] > 0
