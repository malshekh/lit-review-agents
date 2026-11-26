import pytest

from litreview.reconciliation_links import explained_links, SVM
from litreview.synthesis_job import JobStopped


def example_page():
    props = {"GROUP_G0004.P3": {"evidence": [{"finding_id": "R0078:F13"}]},
             "GROUP_G0003.P1": {"evidence": [{"finding_id": "R0058:F3"}]}}
    reviews = [{"proposition_id": "GROUP_G0004.P3", "rationale": SVM},
               {"proposition_id": "GROUP_G0003.P1", "rationale": "The bacterial benchmark examined model choice."}]
    issue = {"proposition_ids": list(props), "finding_ids": ["R0078:F13", "R0058:F3"],
             "limitation": f"G0004.P3 R0078:F13 {SVM}\nG0003.P1 R0058:F3 The benchmark examined spectrum partitioning."}
    return {"reviews": reviews, "issues": [issue], "limitations": [], "warnings": []}, props


def test_other_studies_can_report_model_choice():
    out, props = example_page()
    assert len(explained_links(out, set(out["issues"][0]["finding_ids"]), props)[0]) == 2


@pytest.mark.parametrize("error", ["cause_in_review", "cause_in_issue", "unseen", "wrong_proposition"])
def test_scientific_and_link_controls(error):
    out, props = example_page()
    visible = set(out["issues"][0]["finding_ids"])
    if error == "unseen":
        visible.remove("R0078:F13")
    elif error == "cause_in_review":
        out["reviews"][0]["rationale"] += " Model choice explains the decline."
    elif error == "cause_in_issue":
        out["issues"][0]["limitation"] = out["issues"][0]["limitation"].replace(SVM, "Model choice explains the decline.")
    else:
        out["issues"][0]["limitation"] = out["issues"][0]["limitation"].replace("G0003.P1 R0058:F3", "G0003.P1 R0078:F13")
    with pytest.raises(JobStopped):
        explained_links(out, visible, props)
