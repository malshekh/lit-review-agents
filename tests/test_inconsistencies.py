"""Inconsistencies inside a paper reach A07 through the coverage manifest; researcher verification marks them."""
import pytest

from litreview import orchestrator as orch


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    r = orch.Run("t")
    r.save_state({"stage": "synthesize", "status": "READY", "counters": {}})
    r.save("selected_corpus.json", [{"record_id": "R1", "tier": "SUPPORTING"},
                                    {"record_id": "R2", "tier": "SUPPORTING", "is_contrary_evidence": True},
                                    {"record_id": "R3", "tier": "SUPPORTING"}])
    r.save("extractions/R1.json", {"in_paper_conflicts": [
        {"finding_ids": ["F21"], "description": "Text says no body-weight effect; ANOVA reports one."},
        {"finding_ids": ["F2"], "description": "Survival described two ways."}]})
    r.save("validations/R1.json", {"validations": [{"finding_id": "F2", "disposition": "SUPPORTED"},
                                                   {"finding_id": "F21", "disposition": "BLOCKED_ALIGNMENT"}],
                                   "warnings": [   # written before A06-SV v0.2: free text only
        "Gate 1 blocks F18 because code did not find its span.",
        "Table 1 labels the DSF dose as 150 μM, whereas Results and Figure 6 specify 150 nM."]})
    r.save("extractions/R2.json", {})
    r.save("validations/R2.json", {"validations": [{"finding_id": "F1", "disposition": "SUPPORTED_WITH_CONSTRAINTS"}],
                                   "warnings": ["Gate 1 blocks F2."], "source_inconsistencies": [
        {"description": "n = 8 in Methods, n = 6 in the Figure 2 legend", "locations": ["Methods", "Fig. 2"],
         "finding_ids": ["F1"], "affects_interpretation": "Statistical power"}]})
    r.save("extractions/R3.json", {})
    r.save("validations/R3.json", {"validations": [{"finding_id": "F1", "disposition": "DOES_NOT_ESTABLISH"}],
                                   "source_inconsistencies": [{"description": "dose differs", "finding_ids": []}]})
    return r


def _by_id(run):
    return {i["item_id"]: i for i in run._inconsistency_items(run.load("selected_corpus.json"))}


def test_items_and_visibility_rule(run):
    items = _by_id(run)
    vis = {k: v["required_visibility"] for k, v in items.items()}
    assert vis == {
        "INCONSISTENCY:R1:1": "SUPPLEMENTARY",   # affects F21, which A06 blocked: not used by the review
        "INCONSISTENCY:R1:2": "DISPLAY",         # usable finding, SUPPORTING paper: cited, not built on
        "INCONSISTENCY:R1:3": "DISPLAY",         # free-text warning: no finding IDs, paper has usable findings
        "INCONSISTENCY:R2:1": "NARRATIVE",       # usable finding of a contrary-evidence paper
        "INCONSISTENCY:R3:1": "SUPPLEMENTARY"}   # paper has no usable findings
    assert items["INCONSISTENCY:R1:3"]["source"] == "A06-SV warning (free text)"   # pipeline warnings skipped
    assert items["INCONSISTENCY:R2:1"]["source"] == "A06-SV source_inconsistencies"
    assert all(i["visibility_reason"] for i in items.values())
    assert len(run.load("inconsistencies.json")) == 5   # the full list is kept whatever the visibility


def test_core_paper_makes_named_items_narrative_but_not_paper_level_ones(run):
    run.save("selected_corpus.json", [{"record_id": "R1", "tier": "CORE"}])
    items = _by_id(run)
    assert items["INCONSISTENCY:R1:2"]["required_visibility"] == "NARRATIVE"   # names usable F2
    assert items["INCONSISTENCY:R1:3"]["required_visibility"] == "DISPLAY"     # free text, no finding IDs


def test_researcher_verification_is_always_narrative_and_logged(run):
    run.verify_source_inconsistency("R3", "Checked: the dose differs between Methods and Table 2.",
                                    matches="dose differs")
    item = _by_id(run)["INCONSISTENCY:R3:1"]   # would be SUPPLEMENTARY on tier and usability alone
    assert item["researcher_verified"] and item["required_visibility"] == "NARRATIVE"
    assert item["researcher_statement"].startswith("Checked:")
    ev = [e for e in run.prov.events() if e["type"] == "human_decision"]
    assert ev[-1]["actor"] == "HUMAN" and ev[-1]["checkpoint"] == "SOURCE_VERIFICATION"


def test_display_items_become_notes_under_the_table_showing_that_paper(run):
    from litreview.tools.display_items import inconsistency_notes
    items = list(_by_id(run).values())
    table = {"row_finding_ids": ["R1:F2", "R2:F1"]}
    notes = inconsistency_notes(table, items, run.load("selected_corpus.json"))
    assert [n["item_id"] for n in notes] == ["INCONSISTENCY:R1:2", "INCONSISTENCY:R1:3"]
    assert notes[0]["text"].startswith("R1 [@R1]: inconsistency reported within the paper")
    assert inconsistency_notes({"row_finding_ids": ["R2:F1"]}, items, run.load("selected_corpus.json")) == []


def test_verification_with_no_agent_match_adds_its_own_item(run):
    run.verify_source_inconsistency("R2", "Supplementary Table S1 gives a different dose.")
    items = [i for i in run._inconsistency_items(run.load("selected_corpus.json")) if i["record_id"] == "R2"]
    assert items[-1]["source"] == "RESEARCHER" and items[-1]["researcher_verified"]


def test_verify_rejects_unknown_record(run):
    with pytest.raises(ValueError):
        run.verify_source_inconsistency("R9", "x")


def test_run_until_stops_before_the_stage(run):
    assert run.run(until="synthesize") == "PAUSED: stopped before synthesize (--until)"


def test_changed_manuscripts_are_reverified_even_under_draft_and_final(run, monkeypatch):
    calls = []
    monkeypatch.setattr(run, "_verify", lambda *a, **k: calls.append(a) or {"findings": ["new"]})
    monkeypatch.setattr(run, '_verification_current', lambda *a:False)
    run.cfg = {**run.cfg, "loops": {**run.cfg["loops"], "verification": "draft_and_final"}}
    out = run._maybe_verify({}, "REVISION", "A10-RV_revision1", {"findings": ["old"]})
    assert calls and out['findings']==['new']
    monkeypatch.setattr(run,'_verification_current',lambda *a:True)
    assert run._maybe_verify({},'REVISION','same',{'findings':['old']})['findings']==['old']
    monkeypatch.setattr(run,'_verification_current',lambda *a:False)
    run.cfg["loops"]["verification"] = "all"
    assert run._maybe_verify({}, "REVISION", "A10-RV_revision1", {})["findings"] == ["new"]


def test_theme_merge_is_string_level_only():
    from litreview.tools import themes
    counts = {"Pharmacokinetics": 5, "pharmacokinetic": 2, "mechanistic: ROS generation": 3, "ROS generation": 4,
              "drug_exposure_and_brain_penetration": 7, "Blood-brain barrier / P-gp inhibition and exposure": 10}
    mapping, s = themes.consolidate(counts, max_after_merge=40)
    assert s["applied"] and mapping["pharmacokinetic"] == "Pharmacokinetics"
    assert mapping["mechanistic: ROS generation"] == "ROS generation"
    assert mapping["drug_exposure_and_brain_penetration"] == "drug_exposure_and_brain_penetration"   # meaning, not merged
    _, s = themes.consolidate(counts, max_after_merge=3)
    assert not s["applied"] and "sent unmerged" in s["note"]


def test_consolidation_keeps_original_labels(run):
    findings = [{"finding_id": "R1:F1", "themes": ["Pharmacokinetics"]}, {"finding_id": "R1:F3", "themes": ["Pharmacokinetics"]},
                {"finding_id": "R1:F2", "themes": ["pharmacokinetics "]}]   # most used label becomes the merged name
    out, recs = run._consolidate_themes(findings, {"Pharmacokinetics": {"conflicts": []}, "pharmacokinetics ": {}})
    assert out[2]["themes"] == ["Pharmacokinetics"] and out[2]["themes_original"] == ["pharmacokinetics "]
    assert recs["Pharmacokinetics"]["merged_from"] == ["Pharmacokinetics", "pharmacokinetics "]
    assert run.prov.events()[-1]["tool"] == "theme_consolidation"
