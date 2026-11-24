"""Scripted model replies completed to the strict output contracts (every field present, nothing extra).
A test states only the fields it is about; these fill the rest with the contract's neutral values."""

A06_ROW = {"structure": "ATOMIC", "components": [], "gate2": "ALIGNED", "profiles": [], "dimensions": None,
           "constraints": [], "plain_language_limit": None}
A06_PAPER = {"validations": [], "defect_reports": [], "defect_count": 0, "normalization_conflicts": [],
             "source_inconsistencies": []}
A06_THEME = {"conflicts": [], "independence": [], "evidence_reach": None, "cross_packet_candidates": [],
             "packet_conflicts_not_retained": [], "retrieval_requests": []}
HEAD = {"agent_id": "A06-SV", "prompt_version": "0.9", "status": "COMPLETE", "warnings": [], "limitations": []}


def a06_row(row: dict) -> dict:
    return {**A06_ROW, **row}


def a06_paper(**fields) -> dict:
    """A PER_PAPER reply: the paper's lists, the PER_THEME half empty."""
    out = {**HEAD, **A06_PAPER, **A06_THEME, "mode": "PER_PAPER", "theme": None, **fields}
    out["validations"] = [a06_row(v) for v in out["validations"]]
    if "defect_count" not in fields:
        out["defect_count"] = len(out["defect_reports"])
    return out


def a06_theme(**fields) -> dict:
    """A PER_THEME reply: the theme's lists, the PER_PAPER half empty."""
    reach = {"systems_covered": [], "systems_missing": [], "main_constraints": [], "summary": "scripted"}
    out = {**HEAD, **A06_PAPER, **A06_THEME, "mode": "PER_THEME", "record_id": None, "evidence_reach": reach, **fields}
    if isinstance(out.get("evidence_reach"), dict):
        out["evidence_reach"] = {**reach, **out["evidence_reach"]}
    return out
