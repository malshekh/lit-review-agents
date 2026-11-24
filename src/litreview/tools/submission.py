"""Submission integrity: what must hold before an exported manuscript may be called submission-ready.

The export itself fails (nothing is written) on an unknown citation ID or a retracted cited paper. Everything
else is written out and listed as a blocker in final/submission_status.json, which is recomputed by
`litreview submission-check RUN` after the researcher has dealt with it:

  declarations    AI-use disclosure, author contributions and competing interests are drafted here from the
                  provenance log (which model did what, which decisions a person made). They are drafts by
                  construction: an AI cannot state who the authors are, what they contributed or what interests
                  they hold. Each stays a blocker until a person has edited it, removed every [bracketed]
                  placeholder and marked it FINAL with their name.
  references      every reference confirmed by Crossref under a matching title, none retracted.
  table           every row cites at least one paper, every paper cited in a row is a CORE paper of the selected
                  corpus, and the table is estimated to fit one page.
  compliance      the journal limits (tools/compliance.py); a broken hard limit is a blocker.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from .tags import cited_records

DECLARATIONS = {
    "author_contributions": "Author contributions and biographies",
    "ai_use_disclosure": "AI use disclosure",
    "competing_interests": "Competing interests",
}
STATUS_RE = re.compile(r"^STATUS:\s*(DRAFT|FINAL)\b[ \t]*(.*)$", re.M)
PLACEHOLDER_RE = re.compile(r"\[[A-Z][^\]\n]{2,}\]")
DRAFT_BANNER = ("STATUS: DRAFT\n"
                "<!-- Generated from the provenance log. Edit the text below so that it is true and complete, replace "
                "every [BRACKETED] placeholder, then change the first line to:  STATUS: FINAL <your name>\n"
                "     Nothing above the line of dashes is exported. -->\n"
                "----------\n")

AGENT_ROLES = {
    "A02-SP": "drafted the review scope from the authors' topic statement",
    "A03-LM": "proposed database search strategies",
    "A04-CQ": "screened retrieved records against the authors' selection criteria",
    "A05-KE": "extracted findings from the selected papers",
    "A06-SV": "audited each extracted finding against its source text",
    "A07-SYN": "proposed a synthesis of the validated findings",
    "A08-OL": "proposed the manuscript outline",
    "A09-WRI": "drafted the manuscript text from the approved synthesis",
    "A10-RV": "checked each drafted claim against the validated findings",
    "A11-RC": "critiqued the draft",
    "A12-EDI": "edited the draft for language and journal format",
}
CHECKPOINT_ROLES = {
    "CP1": "approved the scope, perspective and selection criteria",
    "CP2": "selected the papers to include",
    "CP_SYN": "approved the alignment of the synthesis plan with the review question",
    "CP3": "approved the thesis and adopted or rejected each proposed interpretation",
    "CP_LEDGER": "approved the allocation of evidence to sections",
    "CP_CONTRARY": "decided how contrary evidence is presented",
}


# ---------------------------------------------------------------------------------------------- declarations
def draft_declarations(provenance_summary: dict) -> dict[str, str]:
    """Draft text for the three declarations, from the provenance summary (Run._provenance_summary)."""
    models = provenance_summary.get("models_by_agent") or {}
    lines = []
    for agent in sorted(models):
        used = ", ".join(sorted(models[agent]))
        lines.append(f"- {used} {AGENT_ROLES.get(agent, 'ran pipeline step ' + agent)}.")
    decisions: dict[str, int] = {}
    for d in provenance_summary.get("human_decisions") or []:
        decisions[d.get("checkpoint", "?")] = decisions.get(d.get("checkpoint", "?"), 0) + 1
    human = [f"- {CHECKPOINT_ROLES[cp]} ({n} recorded decision{'s' if n != 1 else ''})."
             for cp, n in sorted(decisions.items()) if cp in CHECKPOINT_ROLES]
    mixed = provenance_summary.get("mixed_model_agents") or []
    ai = ("During the preparation of this work the authors used large language models, run through a scripted "
          "pipeline, for the following tasks:\n" + ("\n".join(lines) or "- [LIST EACH MODEL AND TASK]") + "\n\n"
          + (f"For {', '.join(mixed)} more than one model produced output.\n\n" if mixed else "")
          + "Every model output was checked by code against the source text or the validated findings, and the "
          "authors made the following decisions themselves:\n" + ("\n".join(human) or "- [LIST THE AUTHORS' DECISIONS]")
          + "\n\nThe perspective of the review, the selection of evidence and the conclusions are the authors' own. "
          "The authors reviewed and edited all text and take full responsibility for the content of the published "
          "article. No large language model is listed as an author.\n\n"
          "[CONFIRM THAT THIS LIST IS COMPLETE, INCLUDING ANY AI TOOL USED OUTSIDE THE PIPELINE, AND DELETE THIS LINE]")
    contrib = ("[AUTHOR INITIALS] conceived the review and defined its scope and perspective. "
               "[AUTHOR INITIALS] selected the literature, approved the synthesis and the conclusions, and verified "
               "the extracted evidence against the source papers. [AUTHOR INITIALS] wrote and revised the manuscript. "
               "All authors read and approved the final manuscript.\n\n"
               "[ADD A SHORT BIOGRAPHY FOR EACH AUTHOR IF THE JOURNAL REQUESTS ONE]\n\n"
               "Recorded in the pipeline's provenance log, for reference while writing this statement:\n"
               + ("\n".join(human) or "- no human decision was recorded"))
    interests = ("The authors declare no competing interests.\n\n"
                 "[CONFIRM FOR EVERY AUTHOR, OR REPLACE WITH EACH AUTHOR'S FINANCIAL AND NON-FINANCIAL INTERESTS, "
                 "THEN DELETE THIS LINE]")
    return {"author_contributions": contrib, "ai_use_disclosure": ai, "competing_interests": interests}


def _digest(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def write_declaration_drafts(final_dir: Path, provenance_summary: dict) -> dict[str, dict]:
    """Write a draft file for each declaration that has none. A file a person has started editing is never
    overwritten. Returns declaration_state()."""
    d = Path(final_dir) / "declarations"
    d.mkdir(parents=True, exist_ok=True)
    drafts = draft_declarations(provenance_summary)
    index_path = d / "drafts.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    for key, text in drafts.items():
        f = d / f"{key}.md"
        if not f.exists():
            f.write_text(DRAFT_BANNER + text + "\n", encoding="utf-8")
            index[key] = _digest(text)
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return declaration_state(final_dir)


def declaration_state(final_dir: Path) -> dict[str, dict]:
    """{key: {heading, text, final, by, problems}} read from final/declarations/*.md."""
    d = Path(final_dir) / "declarations"
    index_path = d / "drafts.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    out = {}
    for key, heading in DECLARATIONS.items():
        f = d / f"{key}.md"
        problems: list[str] = []
        text, final, by = "", False, ""
        if not f.exists():
            problems.append("no declaration file")
        else:
            raw = f.read_text(encoding="utf-8")
            m = STATUS_RE.search(raw)
            body = raw.split("----------", 1)[1] if "----------" in raw else STATUS_RE.sub("", raw, count=1)
            text = body.strip()
            final = bool(m and m.group(1) == "FINAL")
            by = (m.group(2).strip() if m else "")
            if not final:
                problems.append("still marked STATUS: DRAFT")
            elif not by:
                problems.append("marked FINAL without the name of the person who finalised it")
            if PLACEHOLDER_RE.search(text):
                problems.append("contains unresolved [PLACEHOLDER] text")
            if not text:
                problems.append("is empty")
            if key != "competing_interests" and index.get(key) and _digest(text) == index[key]:
                problems.append("is identical to the generated draft: it has not been edited")
        out[key] = {"heading": heading, "text": text, "final": final and not problems, "by": by, "problems": problems,
                    "file": f"declarations/{key}.md"}
    return out


def back_matter(state: dict[str, dict]) -> list[tuple[str, str]]:
    """Back-matter sections for the export. A declaration that is not final is exported visibly as a draft."""
    out = []
    for key, heading in DECLARATIONS.items():
        s = state[key]
        text = s["text"] if s["final"] else ("**DRAFT — NOT FOR SUBMISSION.** " + (s["text"] or "Not written."))
        out.append((heading, text))
    return out


# ---------------------------------------------------------------------------------------------------- table
# Word export geometry (manuscript_export.render_docx): Letter page, 1-inch margins, 8 pt cells, landscape when
# a table has more than 5 columns. Estimates err towards "does not fit".
PT_PER_INCH = 72.0
CELL_FONT_PT = 8.0
CHAR_WIDTH_EM = 0.52          # average Arial glyph width, as a share of the font size
LINE_HEIGHT = 1.2
CELL_PADDING_PT = 5.0
CAPTION_FONT_PT = 11.0
CAPTION_LINE_HEIGHT = 1.5
NOTE_FONT_PT = 9.0


def _lines(text: str, width_pt: float, font_pt: float) -> int:
    per_line = max(1, int(width_pt / (font_pt * CHAR_WIDTH_EM)))
    return max(1, sum(math.ceil(max(1, len(part)) / per_line) for part in str(text or "").split("\n")))


def table_page_estimate(table: dict) -> dict:
    """Estimated height of one table in the Word export, against one page."""
    cols = max(1, len(table.get("columns") or []))
    landscape = cols > 5
    width = (11.0 if landscape else 8.5) * PT_PER_INCH - 2 * PT_PER_INCH
    height = (8.5 if landscape else 11.0) * PT_PER_INCH - 2 * PT_PER_INCH
    col_width = width / cols - CELL_PADDING_PT * 2
    used = _lines(table.get("caption", ""), width, CAPTION_FONT_PT) * CAPTION_FONT_PT * CAPTION_LINE_HEIGHT
    for row in [table.get("columns") or []] + list(table.get("rows") or []):
        used += max((_lines(c, col_width, CELL_FONT_PT) for c in row), default=1) * CELL_FONT_PT * LINE_HEIGHT \
            + CELL_PADDING_PT
    for note in table.get("notes") or []:
        used += _lines(note, width, NOTE_FONT_PT) * NOTE_FONT_PT * CAPTION_LINE_HEIGHT
    return {"estimated_height_pt": round(used, 1), "page_height_pt": round(height, 1), "landscape": landscape,
            "pages": round(used / height, 2), "fits_one_page": used <= height}


def table_problems(tables: list[dict], corpus: dict[str, dict], max_pages: float = 1.0) -> list[str]:
    """Why the tables are not submission-ready. `tables`: built tables with the raw [@ID] citations still in
    their cells, plus the exported caption and notes. `corpus`: {record_id: selected-corpus record}."""
    problems = []
    for t in tables:
        name = f"Table {str(t.get('display_id', '?'))[1:] or '?'}"
        for n, row in enumerate(t.get("rows") or [], 1):
            ids = cited_records(" ".join(str(c) for c in row))
            if not ids:
                problems.append(f"{name}, row {n}: cites no paper")
                continue
            for rid in dict.fromkeys(ids):
                rec = corpus.get(rid)
                if rec is None:
                    problems.append(f"{name}, row {n}: {rid} is not in the selected corpus")
                elif rec.get("tier") != "CORE":
                    problems.append(f"{name}, row {n}: {rid} is a {rec.get('tier') or 'untiered'} paper; table rows "
                                    "are CORE papers only (contrary evidence from other tiers belongs in the text)")
        est = table_page_estimate(t)
        if est["pages"] > max_pages:
            problems.append(f"{name}: estimated at {est['pages']} pages ({len(t.get('rows') or [])} rows); the "
                            f"journal allows {max_pages:g}. Shorten cells or remove rows at CP_LEDGER")
    return problems


# --------------------------------------------------------------------------------------------------- status
def status(final_dir: Path, reference_problems: dict, table_issues: list[str], compliance: dict,
           retraction: dict | None = None, science_flags: list[dict] | None = None) -> dict:
    """Recompute submission readiness from what is on disk and the checks the export ran."""
    blockers: list[str] = []
    for key, s in declaration_state(final_dir).items():
        for p in s["problems"]:
            blockers.append(f"{s['heading']} ({s['file']}): {p}")
    for number, problems in sorted(reference_problems.items(), key=lambda x: int(x[0])):
        for p in problems:
            blockers.append(f"Reference {number}: {p}")
    blockers += [f"Table: {p}" for p in table_issues]
    for c in compliance.get("checks", []):
        if not c["pass"] and c.get("hard", True):
            blockers.append(f"Journal limit {c['rule']}: {c['detail']}")
    for r in (retraction or {}).get("unchecked", []):
        blockers.append(f"Retraction status unknown for {r['record_id']}: {r['reason']}")
    if science_flags:
        from . import science_lint
        reviewed_path = Path(final_dir) / "science_lint_reviewed.json"
        reviewed = json.loads(reviewed_path.read_text(encoding="utf-8")) if reviewed_path.exists() else {}
        for f in science_lint.unreviewed(science_flags, reviewed):
            blockers.append(f"Wording to check ({f['rule']}, {f['where']}, key {f['key']}): \"{f['sentence'][:140]}\" "
                            f"{f['advice']} Record your review in final/science_lint_reviewed.json.")
    return {"submission_ready": not blockers, "blockers": blockers,
            "note": "submission_ready is a checklist result, not a judgement of the science: the authors remain "
                    "responsible for reading the manuscript and every reference before submitting."}
