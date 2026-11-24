"""The run specification: the researcher's outline and corpus manifest as explicit, validated, fingerprinted inputs.

Two files are given when a run is created (`litreview new --outline outline.json --corpus corpus.json`) and can be
checked for free beforehand (`litreview spec-check`). Templates: docs/run_spec/.

OUTLINE   Stable section IDs, headings, the QUESTIONS each section investigates, its intended contribution, an
          approximate word budget and scope boundaries. A section states questions, never the conclusion the
          agents are to reach: every question must end in a question mark, and the outline has no field for
          findings. Evidence that fits no section is not dropped: A08 records it as outside the outline and code
          puts it in the unmapped-evidence queue for the researcher (data/unmapped_evidence.json).

CORPUS    At most `max_papers` papers (15). For each: an identifier (PMID or DOI), why it was selected, its
          scientific importance, the reading level intended, the source files, and the access actually obtained.
          Importance and access are separate facts: a CORE paper can be available only as an abstract, and it is
          then read, and described, as an abstract. `actual_access` records what was really available (full
          text or abstract; figures inspected; supplements inspected), and it travels with the paper so that no
          agent describes methods, figures or supplements it was never given.

Both files are copied into the run with their fingerprints (input/run_spec.json), together with a snapshot of
what the run executes under: models, prompt and schema hashes, the price table and the limits.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import jsonschema

SECTION_ID = r"^S\d+(\.\d+){0,2}$"
OUTLINE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["outline_version", "working_title", "sections"],
    "properties": {
        "outline_version": {"type": "integer", "minimum": 1},
        "working_title": {"type": "string", "minLength": 3},
        "review_question": {"type": "string"},
        "scope_statement": {"type": "string"},
        "length_policy": {"enum": ["TARGET", "CEILING"]},
        "length_note": {"type": "string"},
        "global_instructions": {"type": "array", "items": {"type": "string", "minLength": 3}},
        "sections": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["section_id", "heading", "questions", "intended_contribution", "word_budget", "scope"],
            "properties": {
                "section_id": {"type": "string", "pattern": SECTION_ID},
                "parent_section_id": {"type": ["string", "null"]},
                "heading": {"type": "string", "minLength": 2},
                "questions": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 8}},
                "intended_contribution": {"type": "string", "minLength": 8},
                "word_budget": {"type": "integer", "minimum": 0},
                "guidance": {"type": "array", "items": {"type": "string", "minLength": 3}},
                "avoid": {"type": "array", "items": {"type": "string", "minLength": 3}},
                "scope": {"type": "object", "additionalProperties": False, "required": ["includes", "excludes"],
                          "properties": {"includes": {"type": "array", "items": {"type": "string"}},
                                         "excludes": {"type": "array", "items": {"type": "string"}}}}}}}}}
CORPUS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["manifest_version", "papers"],
    "properties": {
        "manifest_version": {"type": "integer", "minimum": 1},
        "papers": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["paper_id", "title", "selection_reason", "scientific_importance", "intended_reading_level",
                         "actual_access"],
            "properties": {
                "paper_id": {"type": "string", "pattern": r"^P\d{2,3}$"},
                "pmid": {"type": ["string", "null"], "pattern": r"^\d{1,9}$"},
                "doi": {"type": ["string", "null"], "pattern": r"^10\.\d{4,9}/\S+$"},
                "title": {"type": "string", "minLength": 5},
                "selection_reason": {"type": "string", "minLength": 15},
                "scientific_importance": {"enum": ["CORE", "SUPPORTING", "CONTEXT"]},
                "intended_reading_level": {"enum": ["FULL_TEXT", "ABSTRACT"]},
                "source_files": {"type": "array", "items": {"type": "string"}},
                "informs_sections": {"type": "array", "items": {"type": "string", "pattern": SECTION_ID}},
                "actual_access": {"type": "object", "additionalProperties": False,
                                  "required": ["level", "figures_inspected", "supplements_inspected"],
                                  "properties": {"level": {"enum": ["FULL_TEXT", "ABSTRACT"]},
                                                 "figures_inspected": {"type": "boolean"},
                                                 "supplements_inspected": {"type": "boolean"},
                                                 "note": {"type": "string"}}}}}}}}
CONCLUSION_WORDS = re.compile(r"\b(demonstrat\w*|prov\w+|establish\w*|confirm\w*|show(s|ed|ing)? that)\b", re.I)


class SpecError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def _fp(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def outline_problems(outline: dict) -> list[str]:
    try:
        jsonschema.validate(outline, OUTLINE_SCHEMA)
    except jsonschema.ValidationError as exc:
        return [f"outline: {exc.message} (at {'/'.join(map(str, exc.absolute_path)) or 'top level'})"]
    problems, ids = [], [s["section_id"] for s in outline["sections"]]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"outline: section_id {dup} is used more than once; IDs must be stable and unique")
    for s in outline["sections"]:
        if s.get("parent_section_id") and s["parent_section_id"] not in ids:
            problems.append(f"outline {s['section_id']}: parent {s['parent_section_id']} does not exist")
        children = [c for c in outline["sections"] if c.get("parent_section_id") == s["section_id"]]
        if children and sum(c["word_budget"] for c in children) > s["word_budget"]:
            problems.append(f"outline {s['section_id']}: its subsections' budgets ({sum(c['word_budget'] for c in children)}) "
                            f"exceed its own ({s['word_budget']}); a chapter budget includes its subsections")
        for q in s["questions"]:
            if not q.strip().endswith("?"):
                problems.append(f"outline {s['section_id']}: \"{q[:70]}\" is not a question. A section lists questions to "
                                "investigate, not conclusions for the agents to prove")
        if CONCLUSION_WORDS.search(s["heading"]):
            problems.append(f"outline {s['section_id']}: the heading \"{s['heading']}\" asserts a result; headings name "
                            "the topic, the evidence decides the message")
    return problems


def corpus_problems(manifest: dict, limits: dict, base_dir: Path | None = None, outline: dict | None = None) -> list[str]:
    try:
        jsonschema.validate(manifest, CORPUS_SCHEMA)
    except jsonschema.ValidationError as exc:
        return [f"corpus: {exc.message} (at {'/'.join(map(str, exc.absolute_path)) or 'top level'})"]
    papers, problems = manifest["papers"], []
    max_papers, max_full = int(limits.get("max_papers", 15)), limits.get("max_full_text")
    if len(papers) > max_papers:
        problems.append(f"corpus: {len(papers)} papers; this run allows at most {max_papers}")
    full = [p for p in papers if p["intended_reading_level"] == "FULL_TEXT"]
    if max_full is not None and len(full) > int(max_full):
        problems.append(f"corpus: {len(full)} papers are marked for full-text reading; the priced plan allows {max_full}")
    seen: dict[str, str] = {}
    sections = {s["section_id"] for s in (outline or {}).get("sections", [])}
    for p in papers:
        pid = p["paper_id"]
        keys = [k for k in (f"pmid:{p.get('pmid')}" if p.get("pmid") else None,
                            f"doi:{(p.get('doi') or '').lower()}" if p.get("doi") else None, f"id:{pid}") if k]
        if not p.get("pmid"):
            problems.append(f"corpus {pid}: needs a PMID (papers are retrieved by PubMed identifier; a DOI alone is "
                            "not enough in this version)")
        for k in keys:
            if k in seen:
                problems.append(f"corpus {pid}: same {k.split(':')[0]} as {seen[k]}")
            seen[k] = pid
        access = p["actual_access"]
        if p["intended_reading_level"] == "FULL_TEXT" and access["level"] != "FULL_TEXT":
            problems.append(f"corpus {pid}: marked for full-text reading but only the abstract was obtained. Change the "
                            "intended level to ABSTRACT (its importance stays as it is) or obtain the full text")
        if access["level"] == "ABSTRACT" and (access["figures_inspected"] or access["supplements_inspected"]):
            problems.append(f"corpus {pid}: figures or supplements cannot have been inspected for an abstract-only paper")
        if access["level"] == "FULL_TEXT" and base_dir is not None:
            for f in p.get("source_files") or []:
                if not (Path(base_dir) / f).is_file():
                    problems.append(f"corpus {pid}: source file {f} not found")
        for sid in p.get("informs_sections") or []:
            if sections and sid not in sections:
                problems.append(f"corpus {pid}: informs section {sid}, which the outline does not have")
    return problems


def check(outline: dict, manifest: dict, limits: dict, base_dir: Path | None = None) -> dict:
    """Validate both inputs together. Raises SpecError listing every problem; returns the summary otherwise."""
    problems = outline_problems(outline) + corpus_problems(manifest, limits, base_dir, outline)
    if problems:
        raise SpecError(problems)
    papers = manifest["papers"]
    informed = {sid for p in papers for sid in p.get("informs_sections") or []}
    return {"sections": len(outline["sections"]), "word_budget": total_words(outline),
            "papers": len(papers),
            "full_text": sum(p["intended_reading_level"] == "FULL_TEXT" for p in papers),
            "abstract": sum(p["intended_reading_level"] == "ABSTRACT" for p in papers),
            "core_read_as_abstract": [p["paper_id"] for p in papers if p["scientific_importance"] == "CORE"
                                      and p["intended_reading_level"] == "ABSTRACT"],
            "sections_no_paper_is_expected_to_inform": sorted(
                s["section_id"] for s in outline["sections"] if informed and s["section_id"] not in informed),
            "outline_sha256": _fp(outline), "corpus_sha256": _fp(manifest)}


def total_words(outline: dict) -> int:
    """The manuscript's word budget: top-level sections only (a chapter's budget includes its subsections)."""
    return sum(s["word_budget"] for s in outline["sections"] if not s.get("parent_section_id"))


def chapters(outline: dict) -> list[dict]:
    """Top-level sections with their subsection IDs."""
    return [{**s, "children": [c["section_id"] for c in outline["sections"] if c.get("parent_section_id") == s["section_id"]]}
            for s in outline["sections"] if not s.get("parent_section_id")]


def check_outline(outline: dict, limits: dict) -> dict:
    """A discovery run: the outline alone. The corpus is found by the pipeline and frozen at CP2."""
    problems = outline_problems(outline)
    if problems:
        raise SpecError(problems)
    return {"mode": "DISCOVERY", "sections": len(outline["sections"]), "word_budget": total_words(outline),
            "max_papers": int(limits.get("max_papers", 15)), "outline_sha256": _fp(outline)}


def install_discovery(run_dir: Path, outline: dict, limits: dict) -> dict:
    summary = check_outline(outline, limits)
    d = Path(run_dir) / "input"
    d.mkdir(parents=True, exist_ok=True)
    (d / "outline.json").write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")
    spec = {**summary, "configuration": configuration_snapshot()}
    (d / "run_spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return spec


def framework_from_outline(outline: dict) -> dict:
    """The theme framework for an outlined run: one primary theme per leaf section (a section with no
    subsections), in outline order. A02 may propose others; the researcher's outline decides."""
    parents = {s.get("parent_section_id") for s in outline["sections"]}
    leaves = [s for s in outline["sections"] if s["section_id"] not in parents]
    themes = []
    for n, s in enumerate(leaves, 1):
        themes.append({"theme_id": f"T{n}", "name": s["heading"], "outline_section_id": s["section_id"],
                       "scope": " ".join(s["questions"] + (s.get("guidance") or [])),
                       "includes": "; ".join(s["scope"]["includes"]) or "as the section's questions describe",
                       "excludes": "; ".join(s["scope"]["excludes"] + (s.get("avoid") or [])) or "none stated"})
    return {"primary_themes": themes,
            "count_justification": f"One theme per subsection of the researcher's outline ({len(themes)} subsections)."}


def outline_brief(outline: dict) -> dict:
    """The outline as agents before A08 receive it: questions, guidance and scope, without word budgets."""
    return {"review_question": outline.get("review_question"), "scope_statement": outline.get("scope_statement"),
            "global_instructions": outline.get("global_instructions") or [],
            "sections": [{k: s.get(k) for k in ("section_id", "parent_section_id", "heading", "questions", "guidance",
                                                "avoid", "scope") if s.get(k) is not None} for s in outline["sections"]]}


def generated_manifest(run_dir: Path) -> dict | None:
    p = Path(run_dir) / "data" / "corpus_manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def manifest_of(run_dir: Path) -> dict | None:
    """The run's corpus manifest: the researcher's (input/) or, in a discovery run, the one generated at CP2."""
    return load(run_dir)[1] or generated_manifest(run_dir)


def _norm_title(t: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).split())


def propose_selection(quals: list[dict], records: list[dict], framework: dict | None, max_papers: int) -> list[dict]:
    """A proposed selection for CP2, from the screening results alone: qualified records, strongest tier first,
    chosen greedily to cover as many outline subsections (themes) as possible, with at least one contrary-evidence
    paper when screening found any. Access does not enter: an important paper available only as an abstract is
    proposed like any other. Returns [{record_id, reason}] in selection order. The researcher confirms or changes it."""
    rank = {"CORE": 0, "SUPPORTING": 1, "CONTEXT": 2, "PERIPHERAL": 3}
    by_id = {r["record_id"]: r for r in records}
    pool = [q for q in quals if q.get("disposition") == "QUALIFIED" and q["record_id"] in by_id]
    pool.sort(key=lambda q: (rank.get(q.get("proposed_tier"), 4), -int(by_id[q["record_id"]].get("year") or 0)))
    theme_names = {t["theme_id"]: t.get("outline_section_id") or t["theme_id"] for t in (framework or {}).get("primary_themes", [])}
    chosen, covered, titles = [], set(), set()

    def take(q, why):
        title = _norm_title(by_id[q["record_id"]].get("title"))
        if title in titles:
            return
        titles.add(title)
        themes = [t for t in q.get("themes") or [] if t in theme_names]
        covered.update(themes)
        chosen.append({"record_id": q["record_id"],
                       "reason": f"{why}; screened {q.get('proposed_tier') or 'untiered'}; covers "
                                 + (", ".join(f"{t} ({theme_names[t]})" for t in themes) or "no outline subsection")
                                 + (f"; screening reason: {q.get('reason')}" if q.get("reason") else "")})
    contrary = [q for q in pool if q.get("is_contrary_evidence") and rank.get(q.get("proposed_tier"), 4) <= 1]
    if contrary and max_papers:
        take(contrary[0], "contrary evidence")
    while len(chosen) < max_papers:
        left = [q for q in pool if q["record_id"] not in {c["record_id"] for c in chosen}
                and _norm_title(by_id[q["record_id"]].get("title")) not in titles]
        if not left:
            break
        gain = lambda q: len(set(q.get("themes") or []) - covered)   # noqa: E731
        best = max(left, key=lambda q: (gain(q) > 0, -rank.get(q.get("proposed_tier"), 4), gain(q)))
        take(best, "adds uncovered subsections" if gain(best) else "strongest remaining")
    return chosen


def build_manifest(selected: list[dict], quals: dict, proposals: dict, framework: dict | None, outline: dict | None,
                   cp2_fingerprint: str, access: dict | None = None) -> dict:
    """The corpus manifest generated from discovery and screening, frozen when CP2 is approved. `access`: the free
    access check of each paper (Run._access_check), so the reading level is what retrieval actually obtained; an
    unresolved lookup is budgeted as full text. Without it the level is estimated from a known PMCID."""
    section_of = {t["theme_id"]: t.get("outline_section_id") for t in (framework or {}).get("primary_themes", [])}
    papers = []
    for n, r in enumerate(selected, 1):
        q = quals.get(r["record_id"], {})
        papers.append({
            "paper_id": f"P{n:02d}", "record_id": r["record_id"], "pmid": str(r["pmid"]) if r.get("pmid") else None,
            "doi": r.get("doi"), "title": r.get("title"),
            "selection_reason": proposals.get(r["record_id"]) or ("selected by the researcher at CP2; screening reason: "
                                                                   + str(q.get("reason") or "not given")),
            "scientific_importance": q.get("proposed_tier") or "SUPPORTING",
            "intended_reading_level": ((access or {}).get(r["record_id"]) or {}).get("level_for_budget")
                                      or ("FULL_TEXT" if r.get("pmcid") else "ABSTRACT"),
            "informs_sections": sorted({section_of[t] for t in q.get("themes") or [] if section_of.get(t)}),
            "actual_access": ({k: access[r["record_id"]].get(k) for k in ("category", "level_read", "figure_legends_read",
                                                                          "figure_images_inspected", "supplements_inspected")}
                              if access and r["record_id"] in access else None)})
    return {"manifest_version": 1, "generated_from": "DISCOVERY_AND_SCREENING", "frozen_at_checkpoint": "CP2",
            "cp2_fingerprint": cp2_fingerprint, "papers": papers}


def chapter_word_report(outline: dict, sections: list[dict], words_of, tolerance: float = 0.15) -> list[dict]:
    """Words written per chapter against its target. sections: manuscript sections with section_id and text."""
    written = {}
    for s in sections:
        written[s.get("section_id")] = written.get(s.get("section_id"), 0) + words_of(s.get("text_markdown") or "")
    out = []
    for ch in chapters(outline):
        n = written.get(ch["section_id"], 0) + sum(written.get(c, 0) for c in ch["children"])
        target = ch["word_budget"]
        out.append({"section_id": ch["section_id"], "heading": ch["heading"], "target": target, "written": n,
                    "within_tolerance": abs(n - target) <= tolerance * target,
                    "by_subsection": {c: written.get(c, 0) for c in ch["children"]}})
    return out


def configuration_snapshot() -> dict:
    """What the run executes under: models, prompt and schema hashes, prices and limits (for input/run_spec.json)."""
    from . import config
    from .agents.base import build_system_prompt
    from .agents.registry import AGENTS
    from .paths import SCHEMAS_DIR
    cfg = config.load("pipeline")
    return {"agents": {a: {"provider": m.provider, "model": m.model, "max_tokens": m.max_tokens, "effort": m.effort,
                           "system_prompt_sha256": hashlib.sha256(build_system_prompt(a).encode("utf-8")).hexdigest()}
                       for a in AGENTS for m in [config.agent_model(a)]},
            "schemas": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(SCHEMAS_DIR.glob("*.json"))},
            "prices_sha256": _fp(config.load("prices")),
            "limits_sha256": _fp({k: cfg.get(k) for k in ("loops", "synthesis", "scientific_verification", "bridge",
                                                          "validation", "extraction", "admission", "batch")})}


def install(run_dir: Path, outline: dict, manifest: dict, limits: dict, base_dir: Path | None = None) -> dict:
    summary = check(outline, manifest, limits, base_dir)
    d = Path(run_dir) / "input"
    d.mkdir(parents=True, exist_ok=True)
    (d / "outline.json").write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "corpus_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    spec = {**summary, "configuration": configuration_snapshot()}
    (d / "run_spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return spec


def load(run_dir: Path) -> tuple[dict | None, dict | None]:
    d = Path(run_dir) / "input"
    out = []
    for name in ("outline.json", "corpus_manifest.json"):
        p = d / name
        out.append(json.loads(p.read_text(encoding="utf-8")) if p.exists() else None)
    return out[0], out[1]


def paper_for(manifest: dict | None, record: dict) -> dict | None:
    """The manifest entry of a retrieved record, matched by PMID or DOI."""
    if not manifest:
        return None
    pmid, doi = str(record.get("pmid") or ""), str(record.get("doi") or "").lower()
    for p in manifest["papers"]:
        if (pmid and p.get("pmid") == pmid) or (doi and (p.get("doi") or "").lower() == doi):
            return p
    return None


def selection_problems(manifest: dict, selected: list[dict]) -> list[str]:
    """The CP2 selection must be exactly the manifest: nothing added by the search, nothing missing."""
    matched = {}
    extra = []
    for r in selected:
        p = paper_for(manifest, r)
        if p is None:
            extra.append(r.get("record_id"))
        else:
            matched[p["paper_id"]] = r.get("record_id")
    missing = [p["paper_id"] for p in manifest["papers"] if p["paper_id"] not in matched]
    out = []
    if extra:
        out.append(f"selected but not in the corpus manifest: {', '.join(map(str, extra))}")
    if missing:
        out.append(f"in the corpus manifest but not selected (not retrieved, or deselected): {', '.join(missing)}")
    return out


def source_access(paper: dict, level_read: str, sections: dict | None = None) -> dict:
    """What an agent may say it had access to for this paper. The pipeline sends text only: figure legends may be in
    the text, figure images never are, so `figure_images_inspected` is always false here. What the researcher
    inspected by hand is kept separately and does not widen what an agent may claim."""
    a = paper["actual_access"]
    legends = level_read == "FULL_TEXT" and any(k.lower().startswith(("figure legend", "verbatim figure legend"))
                                                for k in (sections or {}))
    return {"level": level_read, "figure_legends_read": legends, "figure_images_inspected": False,
            "supplements_inspected": bool(a["supplements_inspected"]) and level_read == "FULL_TEXT",
            "researcher_inspected_figures": bool(a.get("figures_inspected")),
            "scientific_importance": paper["scientific_importance"], "note": a.get("note", "")}


def plan_problems(plan: dict, outline: dict) -> tuple[list[str], dict]:
    """(problems, coverage) of an A08 plan against the researcher's outline: the plan uses the outline's section
    IDs and invents none. A section the evidence cannot fill is reported, never padded."""
    ids = {s["section_id"] for s in outline["sections"]}
    planned = {s.get("section_id"): s for s in plan.get("sections", [])}
    problems = [f"plan section {sid} is not in the researcher's outline" for sid in planned if sid not in ids]
    empty = sorted(sid for sid in ids if sid not in planned or not (planned[sid].get("ordered_items") or []))
    return problems, {"outline_sections": len(ids), "sections_with_evidence": len(ids) - len(empty),
                      "sections_without_evidence": empty}


def unmapped(ledger: list[dict]) -> list[dict]:
    """Evidence A08 placed in no section: the review queue. Nothing here is written about until the researcher
    decides (extend the outline, or accept that it stays out, with the reason on record)."""
    return [{"item_id": e["item_id"], "outcome": e["outcome"], "reason": e.get("reason")}
            for e in ledger if e.get("section_id") in (None, "") and e.get("outcome") == "NOT_INDIVIDUALLY_DISCUSSED"]
