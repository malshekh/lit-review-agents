"""Human checkpoints. The pipeline stops, writes files for the researcher, and resumes after approval.

For each checkpoint, runs/<run_id>/checkpoints/ gets:
  CPn_review.md       human-readable summary of what to decide
  CPn_decision.json   template the researcher fills in (CP2 also gets CP2_records.csv)
`litreview approve <run_id> CPn` reads the decision, checks it, and logs it to provenance.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .provenance import ProvenanceLog


class DecisionIncomplete(ValueError):
    pass


def cp_dir(run_dir: Path) -> Path:
    d = Path(run_dir) / "checkpoints"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- CP1: scope
def write_cp1(run_dir: Path, spec: dict) -> None:
    d = cp_dir(run_dir)
    lines = ["# Checkpoint 1 — Scope & perspective", "",
             f"**Topic (verbatim):** {spec.get('original_topic')}", "",
             f"**Normalized topic:** {spec.get('normalized_topic')}", "",
             f"**Specification state:** {spec.get('spec_state')}", "", "## Perspective options", ""]
    for o in spec.get("perspective_options", []):
        lines += [f"### {o.get('option_id')}: {o.get('angle')}",
                  f"- Organizing principle: {o.get('organizing_principle')}",
                  f"- Why timely: {o.get('why_timely')}",
                  f"- Contribution: {o.get('contribution')}",
                  f"- Competing positions: {'; '.join(o.get('competing_positions', []))}",
                  f"- Risks: {'; '.join(o.get('risks', []))}",
                  f"- Title candidates: {' | '.join(o.get('title_candidates', []))}", ""]
    lines += ["## Selection criteria (frozen once approved)", "```json",
              json.dumps(spec.get("selection_criteria"), indent=2), "```", "",
              "## Assumptions", *[f"- {a}" for a in spec.get("assumptions", [])], "",
              "## Questions for you", *[f"- {q}" for q in spec.get("questions_for_researcher", [])], "",
              "Fill in `CP1_decision.json`, then run `litreview approve <run_id> CP1`."]
    (d / "CP1_review.md").write_text("\n".join(lines), encoding="utf-8")
    template = {"selected_option_id": None, "edited_angle": None,
                "approve_selection_criteria": None, "edited_selection_criteria": None,
                "answers_to_questions": {}, "notes": ""}
    (d / "CP1_decision.json").write_text(json.dumps(template, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- CP2: papers
CP2_COLUMNS = ["select", "tier_override", "record_id", "disposition", "proposed_tier", "tier_signal",
               "contrary", "themes", "year", "title", "venue", "flags", "reason", "doi", "pmid", "screened_by"]


def write_cp2(run_dir: Path, records: list[dict], quals: list[dict], bias_report: dict) -> None:
    """Every record is listed — qualified (all tiers), unresolved and excluded. Nothing is hidden."""
    d = cp_dir(run_dir)
    by_id = {r["record_id"]: r for r in records}
    order = {"CORE": 0, "SUPPORTING": 1, "CONTEXT": 2, "PERIPHERAL": 3, None: 4}
    quals = sorted(quals, key=lambda q: (q["disposition"] != "QUALIFIED", order.get(q.get("proposed_tier"), 4)))
    with open(d / "CP2_records.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CP2_COLUMNS)
        w.writeheader()
        for q in quals:
            r = by_id.get(q["record_id"], {})
            w.writerow({"select": "", "tier_override": "", "record_id": q["record_id"],
                        "disposition": q["disposition"], "proposed_tier": q.get("proposed_tier") or "",
                        "tier_signal": q.get("tier_signal") or "", "contrary": q.get("is_contrary_evidence"),
                        "themes": "; ".join(q.get("themes", [])), "year": r.get("year"),
                        "title": r.get("title"), "venue": r.get("venue"),
                        "flags": "; ".join(q.get("flags", [])), "reason": q.get("reason", ""),
                        "doi": r.get("doi"), "pmid": r.get("pmid"),
                        "screened_by": f"{q.get('screened_by') or 'not recorded'}"
                                       + (f" ({q['screening_prompt']})" if q.get("screening_prompt") else "")})
    counts: dict[str, int] = {}
    screeners: dict[str, int] = {}
    for q in quals:
        screeners[q.get("screened_by") or "not recorded"] = screeners.get(q.get("screened_by") or "not recorded", 0) + 1
        key = q["disposition"] if q["disposition"] != "QUALIFIED" else f"QUALIFIED/{q.get('proposed_tier')}"
        counts[key] = counts.get(key, 0) + 1
    lines = ["# Checkpoint 2 — Select papers", "",
             "Every retrieved record is in `CP2_records.csv` — all tiers, unresolved and excluded. "
             "Tiers are sorting aids only. Put `Y` in the `select` column for every paper the review should use. "
             "You may select excluded or unresolved records too, and set `tier_override`.", "",
             "## Counts", *[f"- {k}: {v}" for k, v in sorted(counts.items())], "",
             "## Screened by", *[f"- {k}: {v} records" for k, v in sorted(screeners.items())],
             *(["", "Screening was split between models: compare `exclusion_rate_by_screening_model` "
                "in the bias checks below before approving."] if len(screeners) > 1 else []), "",
             "## Bias checks", "```json", json.dumps(bias_report, indent=2), "```", "",
             "Then run `litreview approve <run_id> CP2`."]
    (d / "CP2_review.md").write_text("\n".join(lines), encoding="utf-8")
    (d / "CP2_decision.json").write_text(json.dumps({"notes": ""}, indent=2), encoding="utf-8")


def read_cp2_selection(run_dir: Path) -> dict:
    rows = list(csv.DictReader(open(cp_dir(run_dir) / "CP2_records.csv", encoding="utf-8")))
    selected = [r["record_id"] for r in rows if r["select"].strip().upper() in {"Y", "YES", "X", "1"}]
    overrides = {r["record_id"]: r["tier_override"].strip().upper() for r in rows if r["tier_override"].strip()}
    return {"selected_record_ids": selected, "tier_overrides": overrides}


# ---------------------------------------------------------------- CP3: argument
def write_cp3(run_dir: Path, pkg: dict) -> None:
    d = cp_dir(run_dir)
    lines = ["# Checkpoint 3 — Approve the argument", "", "## Thesis options", ""]
    for t in pkg.get("thesis_options", []):
        lines += [f"### {t.get('option_id')} ({t.get('type')})", t.get("text", ""), "",
                  f"- Title draft: {t.get('title_draft')}",
                  f"- Contribution statement: {t.get('contribution_statement_draft')}", ""]
    lines += ["## Proposed interpretations (enter the review only if you adopt them)", ""]
    for p in pkg.get("proposed_interpretations", []):
        lines += [f"- **{p.get('pi_id')}** [{p.get('kind')}] {p.get('statement')}",
                  f"  - Goes beyond the evidence by: {p.get('what_it_goes_beyond')}",
                  f"  - Premises: {', '.join(p.get('premise_proposition_ids', []))}"]
    lines += ["", "## Knowledge gaps", *[f"- [{g.get('type')}] {g.get('statement')}"
                                          for g in pkg.get("knowledge_gaps", [])],
              "", "Fill in `CP3_decision.json`, then run `litreview approve <run_id> CP3`."]
    (d / "CP3_review.md").write_text("\n".join(lines), encoding="utf-8")
    template = {"selected_thesis": None, "adopted_interpretations": [], "rejected_interpretations": [],
                "edits": None, "notes": ""}
    (d / "CP3_decision.json").write_text(json.dumps(template, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- approval
def approve(run_dir: Path, cp: str, provenance: ProvenanceLog) -> dict:
    d = cp_dir(run_dir)
    decision = json.loads((d / f"{cp}_decision.json").read_text(encoding="utf-8"))
    if cp == "CP1":
        if not decision.get("selected_option_id"):
            raise DecisionIncomplete("CP1: set selected_option_id.")
        if decision.get("approve_selection_criteria") is not True and not decision.get("edited_selection_criteria"):
            raise DecisionIncomplete("CP1: set approve_selection_criteria to true, or supply edited_selection_criteria.")
    elif cp == "CP2":
        decision.update(read_cp2_selection(run_dir))
        if not decision["selected_record_ids"]:
            raise DecisionIncomplete("CP2: mark at least one paper with Y in CP2_records.csv.")
    elif cp == "CP3":
        if not decision.get("selected_thesis"):
            raise DecisionIncomplete("CP3: set selected_thesis.")
    provenance.human_decision(cp, decision, decision.get("notes", ""))
    (d / f"{cp}_approved.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
    return decision


def approved(run_dir: Path, cp: str) -> dict | None:
    p = cp_dir(run_dir) / f"{cp}_approved.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
