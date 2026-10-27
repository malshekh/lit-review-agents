"""What A07-SYN receives: the coverage manifest and the frozen corpus, built without duplication.

The corpus is sent identically on every synthesis call (it is the cached prefix), so everything in it is
sent once: each experimental context once per paper (findings reference it by ID), each theme record
once (manifest items reference it), each repeated missing-system gap once (with its occurrence count and
every original occurrence ID, so all of them stay reconstructible).
"""
from __future__ import annotations

from collections import defaultdict

# A06 PER_THEME fields A07 does not use: `limitations` are notes on what A06 inspected, not evidence.
# (`warnings` stay: they carry evidence-relevant flags such as suspected shared origin of two papers.)
THEME_RECORD_DROP = ("limitations",)
# Finding fields A07 does not use: spans were checked by Gate 1 and A06; A07 works from dispositions.
FINDING_DROP = ("span", "context")


def build_manifest(corpus: list[dict], theme_records: dict, inconsistency_items: list[dict]) -> list[dict]:
    """Every item A07 must realize. Conflicts and reach summaries reference their theme record instead of
    copying it; identical missing-system gaps collapse to one item per system string (exact match)."""
    manifest = [{"item_id": f"PAPER:{r['record_id']}", "kind": "SELECTED_PAPER", "record_id": r["record_id"],
                 "required_visibility": "NARRATIVE" if (r.get("tier") == "CORE" and r.get("is_contrary_evidence"))
                 else "CITED"} for r in corpus]
    gaps: dict[str, dict] = {}
    for th, rec in theme_records.items():
        for i, _ in enumerate(rec.get("conflicts", []), 1):
            manifest.append({"item_id": f"CONFLICT:{th}:{i}", "kind": "CONFLICT", "theme_record": th,
                             "conflict_index": i, "required_visibility": "NARRATIVE"})
        manifest.append({"item_id": f"REACH:{th}", "kind": "EVIDENCE_REACH", "theme_record": th,
                         "required_visibility": "NARRATIVE"})
        for m in (rec.get("evidence_reach") or {}).get("systems_missing", []):
            g = gaps.setdefault(m, {"item_id": f"MISSING:{m}", "kind": "SYSTEM_GAP", "system": m,
                                    "occurrence_count": 0, "affected_theme_ids": [], "source_occurrence_ids": [],
                                    "required_visibility": "NARRATIVE"})
            g["occurrence_count"] += 1
            g["affected_theme_ids"].append(th)
            g["source_occurrence_ids"].append(f"MISSING:{th}:{m}")
    manifest += sorted(gaps.values(), key=lambda g: -g["occurrence_count"])
    return manifest + inconsistency_items


def compact_findings(findings: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """Findings without spans, each referencing its context by ID; contexts returned once each."""
    contexts: dict[str, dict] = {}
    out = []
    for f in findings:
        cid = f.get("context_id")
        if cid and cid not in contexts:
            contexts[cid] = f.get("context")
        out.append({k: v for k, v in f.items() if k not in FINDING_DROP})
    return out, contexts


def build_corpus(spec: dict, corpus: list[dict], findings: list[dict], theme_records: dict,
                 manifest: list[dict], framework: dict | None = None) -> dict:
    """The frozen corpus for every A07 call. Key order is fixed so the serialized prefix is byte-identical."""
    compact, contexts = compact_findings(findings)
    return {
        "review_spec": spec,
        "theme_framework": framework,
        "selected_corpus": [{k: r.get(k) for k in ("record_id", "title", "authors", "year", "venue", "tier",
                                                   "themes", "is_preprint", "is_contrary_evidence")}
                            for r in corpus],
        "contexts": contexts,
        "validated_findings": compact,
        "theme_records": {th: {k: v for k, v in rec.items() if k not in THEME_RECORD_DROP}
                          for th, rec in theme_records.items()},
        "coverage_manifest": manifest,
    }


def mandatory_items(manifest: list[dict]) -> dict[str, dict]:
    """Items A07 must realize (NARRATIVE or CITED). DISPLAY and SUPPLEMENTARY inconsistency items are
    placed by code (table notes) or kept in the run record, so they are not A07's to satisfy."""
    return {m["item_id"]: m for m in manifest if m.get("required_visibility") in ("NARRATIVE", "CITED")}


def occurrences(manifest: list[dict]) -> dict[str, list[str]]:
    """Collapsed gap item -> every original per-theme occurrence ID (for reconstruction)."""
    return {m["item_id"]: m["source_occurrence_ids"] for m in manifest if m["kind"] == "SYSTEM_GAP"}


def group_findings(findings: list[dict]) -> dict[str, list[str]]:
    by_record: dict[str, list[str]] = defaultdict(list)
    for f in findings:
        by_record[f["record_id"]].append(f["finding_id"])
    return by_record
