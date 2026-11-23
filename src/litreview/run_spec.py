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
    return {"sections": len(outline["sections"]), "word_budget": sum(s["word_budget"] for s in outline["sections"]),
            "papers": len(papers),
            "full_text": sum(p["intended_reading_level"] == "FULL_TEXT" for p in papers),
            "abstract": sum(p["intended_reading_level"] == "ABSTRACT" for p in papers),
            "core_read_as_abstract": [p["paper_id"] for p in papers if p["scientific_importance"] == "CORE"
                                      and p["intended_reading_level"] == "ABSTRACT"],
            "sections_no_paper_is_expected_to_inform": sorted(
                s["section_id"] for s in outline["sections"] if informed and s["section_id"] not in informed),
            "outline_sha256": _fp(outline), "corpus_sha256": _fp(manifest)}


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


def source_access(paper: dict, level_read: str) -> dict:
    """What an agent may say it had access to for this paper."""
    a = paper["actual_access"]
    return {"level": level_read, "figures_inspected": bool(a["figures_inspected"]) and level_read == "FULL_TEXT",
            "supplements_inspected": bool(a["supplements_inspected"]) and level_read == "FULL_TEXT",
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
