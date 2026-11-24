"""The merged pipeline end to end on 30 replicated papers: real A07 job, CP3, bridge, real A10 job, final release.
Scripted model outputs only (tests/integrated_pipeline.py); structural, not scientific, evidence."""
import pytest

import integrated_pipeline as ip


@pytest.fixture(scope="module")
def sim(tmp_path_factory):
    return ip.simulate(30, tmp_path_factory.mktemp("sim"), fail={"A09-WRI_draft1_S3": 1, "A10-RV_draft1": 1})


def test_no_evidence_is_lost_or_promoted(sim):
    assert sim["a07"]["status"] == "COMPLETE" and not sim["a07"]["findings_unaccounted"]
    assert not sim["a07"]["coverage_incomplete"]
    held = sim["held_finding"]
    assert held["status"] == "HELD_FOR_CORRECTION"
    assert not (held["used_by_any_proposition"] or held["in_any_packet"] or held["in_table"])
    assert sim["ineligible_findings_in_packets"] == [] and sim["manuscript_tags_with_ineligible_roles"] == []


def test_every_element_is_accounted_for_and_every_written_one_is_rendered(sim):
    assert sum(v for k, v in sim["ledger"].items() if k != "elements") == sim["ledger"]["elements"]
    assert sim["written_elements_rendered"] == sim["written_elements"] and sim["mandatory_not_written"] == []


def test_cross_theme_contradiction_reaches_both_sections(sim):
    issue = sim["cross_theme_issue"]
    assert len(issue["sections"]) == 2 and issue["in_each_sections_packet"]


def test_final_release_rests_on_current_complete_verification(sim):
    a10 = sim["a10_final"]
    assert a10["execution"] == "COMPLETE" and a10["release"] == "APPROVED"
    assert a10["coverage"]["occurrences_total"] == a10["coverage"]["occurrences_reviewed"]
    assert a10["current_for_final_manuscript"] and a10["stamp_matches"] and a10["table_occurrences"] > 0
    assert sim["final_state"] == "finalize" and sim["exported_tables"] == 1


def test_interrupted_calls_resume_without_repeating_paid_work(sim):
    assert sim["interruptions"]["draft"] == 2
    assert set(sim["successful_section_calls"].values()) == {1}          # no section written twice
    assert sim["front_matter_calls"] == 1 and sim["integration_calls"] == 1


def test_every_request_fit_its_window(sim):
    assert all(x["all_fit"] for x in sim["admissions_by_agent"].values())


def test_the_table_says_it_is_a_selection(sim):
    assert sim["table"]["rows"] <= 25 and "not a summary of every study" in sim["table"]["notes"][0]
