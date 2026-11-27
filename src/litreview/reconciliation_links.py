"""Local contract for page 1001's evidence-link explanations inside the existing issue schema."""
import re

from .synthesis_job import JobStopped

SVM = "SVM three-fold CV 98 +/- 4%; intermediate-concentration test 50%; cause of decline unresolved."
RULE = ("Each issue limitation must consist of one line per referenced proposition, in the form "
        "G0002.P6 R0078:F28 explanation of what this visible finding supports in this comparison. "
        "Choose a relevant finding for each line. finding_ids must equal the set of line anchors. "
        "Split or narrow issues to stay within 480 characters. Withdraw relationships without evidence. "
        "Request missing records through NEEDS_EVIDENCE before judgment. "
        "For every R0078:F13 line and the G0004.P3 review rationale use exactly: " + SVM +
        " Keep all commentary on the SVM decline in those fields. A causal explanation is unestablished.")

def matched_test_comparison(review, props, visible, records):
    """Recognize the bounded DT/SVM comparison from the two visible, co-reported findings."""
    match = re.fullmatch(
        r"The (decision tree|SVM) reached (\d+)% on the same intermediate-concentration test set "
        r"on which (decision tree|SVM) reached (\d+)% in (G\d{4}\.P\d+)"
        r"(?:; different models on one dataset, not a contradiction)?\.",
        review["rationale"], re.IGNORECASE)
    if not match or not records:
        return False
    first, score, second, other_score, reference = match.groups()
    models = {"decision tree": "R0078:F14", "svm": "R0078:F13"}
    left, right = models[first.lower()], models[second.lower()]
    if left == right or not {left, right} <= visible:
        return False
    for pid, fid in ((review["proposition_id"], left), ("GROUP_" + reference.upper(), right)):
        if fid not in {e["finding_id"] for e in props.get(pid, {}).get("evidence", [])}:
            return False
    a, b = records.get(left, {}), records.get(right, {})
    span = a.get("span", "")
    if not span or span != b.get("span") or a.get("record_id") != "R0078" or b.get("record_id") != "R0078":
        return False
    scores = re.search(
        r"test set with intermediate concentrations.*?3-fold cross-validation.*?"
        r"\(DT\),.*?\(SVM\), and .*?\(XGBoost\)\. Test set performance .*?"
        r"accuracies of (\d+)%, (\d+)%, and \d+%, respectively", span, re.DOTALL)
    if not scores:
        return False
    measured = dict(zip(("decision tree", "svm"), scores.groups()))
    return measured[first.lower()] == score and measured[second.lower()] == other_score


def explained_links(out, visible, props, records=None):
    links = []
    if "G0004.P3" not in {r["proposition_id"].removeprefix("GROUP_") for r in out["reviews"]}:
        raise JobStopped("missing focal Israel review")
    for r in out["reviews"]:
        if r["proposition_id"] == "GROUP_G0004.P3" and r["rationale"] != SVM:
            raise JobStopped("Israel focal review must preserve both evaluations and unresolved cause")
    other_text = [(text, False) for text in [*out["warnings"], *out["limitations"]]]
    classifiers = {"R0078:F12", "R0078:F13", "R0078:F14"}
    for review in out["reviews"]:
        pid = review["proposition_id"]
        if pid != "GROUP_G0004.P3" and not matched_test_comparison(review, props, visible, records):
            local = {e["finding_id"] for e in props.get(pid, {}).get("evidence", [])}
            other_text.append((review["rationale"], bool(local & classifiers)))
    for issue in out["issues"]:
        entries = {}
        for line in issue["limitation"].splitlines():
            match = re.fullmatch(r"(G[0-9]{4}\.P[0-9]+) (R[0-9]{4}:F[0-9]+) (\S.*)", line)
            if not match:
                raise JobStopped("each issue needs a proposition, visible finding and explanation on each line")
            short, fid, reason = match.groups()
            pid = "GROUP_" + short
            prior = {e["finding_id"] for e in props.get(pid,{}).get("evidence",[])}
            if pid in entries or fid not in visible or fid not in prior or len(reason.split()) < 3:
                raise JobStopped("invalid or unexplained proposition-specific finding link")
            if fid == "R0078:F13":
                if reason != SVM:
                    raise JobStopped("Israel issue conflicts with frozen evaluation and unresolved cause")
            else:
                other_text.append((reason, fid in classifiers))
            entries[pid] = {"finding":fid,"supports":reason}
        if set(entries) != set(issue["proposition_ids"]) or {v["finding"] for v in entries.values()} != set(issue["finding_ids"]):
            raise JobStopped("explained links must cover the entire issue")
        links.append(entries)
    for text, classifier_context in other_text:
        names_svm = re.search(r"\b(?:svm|support.vector)\b", text, re.I)
        attribution = re.search(r"\b(?:model choice|decline|drop|fell|decreased)\b", text, re.I)
        if names_svm or (classifier_context and attribution):
            raise JobStopped("unexpected Israel interpretation outside the checked evidence statement")
    return links
