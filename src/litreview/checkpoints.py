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
              *_framework_lines(spec.get("theme_framework"), "Theme framework (proposed by A02)"),
              "To change the framework, put the edited version in `edited_theme_framework` "
              "(same shape: `primary_themes`, `count_justification`).", "",
              "## Assumptions", *[f"- {a}" for a in spec.get("assumptions", [])], "",
              "## Questions for you", *[f"- {q}" for q in spec.get("questions_for_researcher", [])], "",
              "Fill in `CP1_decision.json`, then run `litreview approve <run_id> CP1`."]
    (d / "CP1_review.md").write_text("\n".join(lines), encoding="utf-8")
    template = {"selected_option_id": None, "edited_angle": None,
                "approve_selection_criteria": None, "edited_selection_criteria": None,
                "edited_theme_framework": None, "answers_to_questions": {}, "notes": ""}
    (d / "CP1_decision.json").write_text(json.dumps(template, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- CP2: papers
CP2_COLUMNS = ["select", "tier_override", "record_id", "disposition", "proposed_tier", "tier_signal",
               "contrary", "themes", "year", "title", "venue", "flags", "reason", "doi", "pmid", "screened_by"]
SCREENING_SPLIT_CAVEAT = (
    "The models screened different records, so comparing their exclusion rates is an observational "
    "screening-bias indicator, not a measure of agreement between models: equal rates do not establish "
    "agreement, and different rates may reflect different record populations rather than different judgment.")


def _framework_lines(fw: dict | None, title: str) -> list[str]:
    if not fw:
        return []
    out = [f"## {title}" + (f" — version {fw['version']}" if fw.get("version") else ""), ""]
    for t in fw.get("primary_themes", []):
        out.append(f"- **{t.get('theme_id')} {t.get('name')}** — {t.get('scope')} "
                   f"(includes: {t.get('includes')}; excludes: {t.get('excludes')})")
    if fw.get("count_justification"):
        out += ["", f"Why this number: {fw['count_justification']}"]
    return out + [""]


def _emerging_lines(emerging: list[dict] | None, what: str) -> list[str]:
    if not emerging:
        return []
    return ([f"## Emerging evidence: {len(emerging)} {what} fit no primary theme", "",
             "Each is attached to its closest primary theme for now. Decide whether the framework should change: "
             "to change it, put the new `primary_themes` list (and a `note`) in `theme_framework_update` in the "
             "decision file. The change becomes a new framework version, recorded as your decision.", ""]
            + [f"- {e['id']} (now under {e.get('primary_theme_id')}; subthemes: {', '.join(e.get('subthemes') or []) or '—'}): "
               f"{e.get('note') or ''}" for e in emerging] + [""])


def write_cp2(run_dir: Path, records: list[dict], quals: list[dict], bias_report: dict,
              emerging: list[dict] | None = None, framework: dict | None = None) -> None:
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
                "in the bias checks below before approving. " + SCREENING_SPLIT_CAVEAT]
               if len(screeners) > 1 else []), "",
             "## Bias checks", "```json", json.dumps(bias_report, indent=2), "```", "",
             *_emerging_lines(emerging, "records"), *_framework_lines(framework, "Current theme framework"),
             "Then run `litreview approve <run_id> CP2`."]
    (d / "CP2_review.md").write_text("\n".join(lines), encoding="utf-8")
    (d / "CP2_decision.json").write_text(json.dumps({"theme_framework_update": None, "notes": ""}, indent=2),
                                         encoding="utf-8")


def read_cp2_selection(run_dir: Path) -> dict:
    rows = list(csv.DictReader(open(cp_dir(run_dir) / "CP2_records.csv", encoding="utf-8")))
    selected = [r["record_id"] for r in rows if r["select"].strip().upper() in {"Y", "YES", "X", "1"}]
    overrides = {r["record_id"]: r["tier_override"].strip().upper() for r in rows if r["tier_override"].strip()}
    return {"selected_record_ids": selected, "tier_overrides": overrides}


# ---------------------------------------------------------------- CP3: argument
def write_cp3(run_dir: Path, pkg: dict, emerging: list[dict] | None = None, framework: dict | None = None) -> None:
    from .synthesis_registry import fingerprint
    d = cp_dir(run_dir)
    lines = ["# Checkpoint 3 — Approve the argument", ""]
    if len(pkg.get("models") or []) > 1:
        by_model: dict[str, list[str]] = {}
        for turn, model in (pkg.get("models_by_turn") or {}).items():
            by_model.setdefault(model or "not recorded", []).append(turn)
        lines += ["## This synthesis was produced by more than one model", "",
                  "A model refused partway through, and the job resumed on its alternate. Propositions from "
                  "different models sit side by side; the AI-use disclosure must name both "
                  "(`provenance_summary.json`).", "",
                  *[f"- {m}: {', '.join(t)}" for m, t in sorted(by_model.items())], ""]
    lines += ["## Thesis options", ""]
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
                                          for g in pkg.get("knowledge_gaps", [])], ""]
    if pkg.get("coverage_incomplete_item_ids") or pkg.get("findings_unaccounted"):
        lines += ["## Synthesis coverage is INCOMPLETE", "",
                  f"- Mandatory items not satisfied: {len(pkg.get('coverage_incomplete_item_ids') or [])} "
                  f"({', '.join((pkg.get('coverage_incomplete_item_ids') or [])[:20])})",
                  f"- Findings accounted for nowhere: {len(pkg.get('findings_unaccounted') or [])}", ""]
    lines += ["## What coverage means", "",
              "Coverage is structural only: SATISFIED means a mandatory item is linked to a proposition that "
              "cites its findings. It is not a check that the proposition is correct or states the evidence at "
              "the right strength; that judgment is yours here, and A10-RV's after drafting.", ""]
    lines += [*_emerging_lines(emerging, "findings"), *_framework_lines(framework, "Current theme framework"),
              "Fill in `CP3_decision.json`, then run `litreview approve <run_id> CP3`."]
    (d / "CP3_review.md").write_text("\n".join(lines), encoding="utf-8")
    template = {"synthesis_fingerprint":fingerprint(pkg), "selected_thesis": None, "adopted_interpretations": [], "rejected_interpretations": [],
                "edits": None, "theme_framework_update": None, "notes": ""}
    (d / "CP3_decision.json").write_text(json.dumps(template, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- approval
def write_synthesis_alignment(run_dir: Path, digest: str, alignment: dict) -> None:
    """Compact human review; full evidence-linked planning stays machine-readable internally."""
    d = cp_dir(run_dir)
    (d / "CP_SYN_alignment.json").write_text(json.dumps(alignment, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# A07 thematic alignment approval", "", f"Input fingerprint: `{digest}`", "",
             "Structural counts are not scientific validation. Unknown independence stays unknown.", "",
             "| Approved primary theme | Findings | Explicit study IDs | Unknown identity findings | Subthemes |",
             "|---|---:|---:|---:|---|"]
    for t in alignment["themes"]:
        ind = t["independence"]
        lines.append(f"| {t['theme_id']}: {t.get('name', '')} | {t['findings']} | {len(ind['known_study_ids'])} | "
                     f"{len(ind['identity_unknown_findings'])} | {', '.join(t['subthemes'])} |")
    lines += ["", f"Unmapped: {len(alignment['unmapped'])}; emerging: {len(alignment['emerging'])}; "
              f"mandatory items: {alignment['mandatory_items']}; bounded packets: {alignment['packets']}.",
              "Full IDs, source-linked conflicts and planning are in CP_SYN_alignment.json.", "", "## Proposed changes"]
    planning = alignment["planning"]
    for n, p in enumerate(planning["theme_change_proposals"], 1):
        lines += [f"{n}. {p['proposal']} — {p['rationale']} ({', '.join(p['finding_ids'])})"]
    lines += ["", "## Potential scope drift", *planning["scope_drift"], "", "## Important conflict source IDs",
              *alignment["conflicts"], "", "Approve the existing framework only after reviewing every proposal.",
              "To adopt a change, revise the upstream framework and regenerate affected evidence before replanning.",
              "Set approve_alignment and keep_approved_framework true, then run `litreview approve RUN CP_SYN`."]
    (d / "CP_SYN_review.md").write_text("\n".join(lines), encoding="utf-8")
    decision = d / "CP_SYN_decision.json"
    if not decision.exists() or json.loads(decision.read_text(encoding="utf-8")).get("fingerprint") != digest:
        decision.write_text(json.dumps({"fingerprint": digest, "approve_alignment": False,
                                        "keep_approved_framework": False, "proposal_review_notes": "", "notes": ""}, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- CP_LEDGER: allocation before writing
def write_ledger_review(run_dir: Path, digest: str, ledger: list[dict], report: dict, elements: dict) -> None:
    """The allocation ledger for approval before A09 writes: what is discussed individually, grouped, shown only
    in the table, or not individually discussed (with A08's reason). Evidence selection is the authors' decision
    under the journal's AI policy; nothing is written until it is approved for these exact plan and ledger."""
    d = cp_dir(run_dir)
    (d / "CP_LEDGER_ledger.json").write_text(json.dumps({"fingerprint": digest, "ledger": ledger, "report": report},
                                                        indent=2, ensure_ascii=False), encoding="utf-8")
    counts = report.get("counts", {})
    lines = ["# Allocation ledger: what the review discusses", "",
             "A08 has allocated every approved element (proposition, gap, adopted interpretation). Approve only if "
             "this is the evidence selection you want: everything below NOT_INDIVIDUALLY_DISCUSSED will not be "
             "written individually.", "",
             *[f"- {k}: {v}" for k, v in counts.items()], "",
             f"Mandatory elements (conflicts, contrary CORE evidence, researcher-verified inconsistencies, system gaps, "
             f"NARRATIVE coverage): {len(report.get('mandatory', {}))}, all written (the bridge rejects any other plan).",
             "", "## Theme to sections", *[f"- {t}: {', '.join(s)}" for t, s in report.get("theme_to_sections", {}).items()],
             "", "## Not individually discussed", ""]
    for e in ledger:
        if e.get("outcome") == "NOT_INDIVIDUALLY_DISCUSSED":
            text = (elements.get(e["item_id"]) or {}).get("text") or ""
            lines.append(f"- **{e['item_id']}** {text} — reason: {e.get('reason')}")
    lines += ["", "## Table only", ""]
    lines += [f"- **{e['item_id']}** {(elements.get(e['item_id']) or {}).get('text') or ''}"
              for e in ledger if e.get("outcome") == "TABLE_ONLY"]
    lines += ["", "## Grouped passages", ""]
    lines += [f"- {g}: {', '.join(m)}" for g, m in report.get("groups", {}).items()]
    lines += ["", "Set approve_ledger to true in `CP_LEDGER_decision.json`, then run "
                  "`litreview approve <run_id> CP_LEDGER`. To change the allocation, record what to change in notes "
                  "and rerun the outline stage instead."]
    (d / "CP_LEDGER_review.md").write_text("\n".join(lines), encoding="utf-8")
    decision = d / "CP_LEDGER_decision.json"
    if not decision.exists() or json.loads(decision.read_text(encoding="utf-8")).get("fingerprint") != digest:
        decision.write_text(json.dumps({"fingerprint": digest, "approve_ledger": False, "notes": ""}, indent=2),
                            encoding="utf-8")


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
    elif cp == "CP_SYN":
        alignment = json.loads((d / "CP_SYN_alignment.json").read_text(encoding="utf-8"))
        if decision.get("fingerprint") != alignment["fingerprint"]:
            raise DecisionIncomplete("CP_SYN: stale planning fingerprint")
        if decision.get("approve_alignment") is not True or decision.get("keep_approved_framework") is not True:
            raise DecisionIncomplete("CP_SYN: approve alignment and explicitly retain the approved framework")
        if alignment["planning"]["theme_change_proposals"] and not decision.get("proposal_review_notes", "").strip():
            raise DecisionIncomplete("CP_SYN: record the decision on proposed changes")
    elif cp == "CP_LEDGER":
        ledger = json.loads((d / "CP_LEDGER_ledger.json").read_text(encoding="utf-8"))
        if decision.get("fingerprint") != ledger["fingerprint"]:
            raise DecisionIncomplete("CP_LEDGER: stale ledger fingerprint (the plan or ledger changed)")
        if decision.get("approve_ledger") is not True:
            raise DecisionIncomplete("CP_LEDGER: set approve_ledger to true")
    elif cp == "CP3":
        from .synthesis_registry import fingerprint
        from .scientific_validation import require_package
        pkg_path = Path(run_dir) / "data" / "synthesis_package.json"
        if not pkg_path.exists():raise DecisionIncomplete('CP3: synthesis package missing')
        pkg = json.loads(pkg_path.read_text(encoding='utf-8'))
        findings_path = Path(run_dir)/'data/validated_findings.json'
        findings = json.loads(findings_path.read_text(encoding='utf-8')) if findings_path.exists() else []
        try:require_package(pkg, findings)
        except ValueError as exc:raise DecisionIncomplete('CP3: '+str(exc)) from exc
        if decision.get('synthesis_fingerprint') != fingerprint(pkg):
            raise DecisionIncomplete('CP3: stale synthesis fingerprint; review current package')
        if not decision.get("selected_thesis"):
            raise DecisionIncomplete("CP3: set selected_thesis.")
    provenance.human_decision(cp, decision, decision.get("notes", ""))
    (d / f"{cp}_approved.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
    return decision


def approved(run_dir: Path, cp: str) -> dict | None:
    p = cp_dir(run_dir) / f"{cp}_approved.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
