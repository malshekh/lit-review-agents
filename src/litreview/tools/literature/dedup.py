"""Deduplicate records across sources by DOI, then PMID, then normalized title + year.

Every retrieval path is kept: a merged record lists all query families that found it.
"""
from __future__ import annotations

import re

from .base import Record


def _title_key(r: Record) -> str:
    return re.sub(r"[^a-z0-9]", "", (r.title or "").lower())[:120] + f"|{r.year or ''}"


def deduplicate(records: list[Record], existing: list[dict] | None = None) -> tuple[list[dict], dict]:
    """Merge records; `existing` (already-deduplicated dicts) keeps its IDs and new IDs continue after them."""
    merged: dict[str, dict] = {}
    index: dict[str, str] = {}
    for d in existing or []:
        merged[d["record_id"]] = d
        for k in (f"doi:{(d.get('doi') or '').lower()}" if d.get("doi") else None,
                  f"pmid:{d['pmid']}" if d.get("pmid") else None,
                  f"nct:{d['nct_id']}" if d.get("nct_id") else None,
                  f"s2:{d['s2_id']}" if d.get("s2_id") else None,
                  f"title:{re.sub(r'[^a-z0-9]', '', (d.get('title') or '').lower())[:120]}|{d.get('year') or ''}"
                  if d.get("title") else None):
            if k:
                index[k] = d["record_id"]
    n_existing = len(merged)
    for r in records:
        keys = [k for k in (f"doi:{(r.doi or '').lower()}" if r.doi else None,
                            f"pmid:{r.pmid}" if r.pmid else None,
                            f"nct:{r.nct_id}" if r.nct_id else None,
                            f"s2:{r.s2_id}" if r.s2_id else None,
                            f"title:{_title_key(r)}" if r.title else None) if k]
        hit = next((index[k] for k in keys if k in index), None)
        if hit is None:
            rid = f"R{len(merged) + 1:04d}"
            d = r.to_dict()
            d.update(record_id=rid, query_family_ids=[r.query_family_id], sources=[r.source])
            merged[rid] = d
            hit = rid
        else:
            d = merged[hit]
            if r.query_family_id not in d["query_family_ids"]:
                d["query_family_ids"].append(r.query_family_id)
            if r.source not in d["sources"]:
                d["sources"].append(r.source)
            for f in ("abstract", "doi", "pmid", "pmcid", "s2_id", "nct_id"):
                if not d.get(f) and getattr(r, f):
                    d[f] = getattr(r, f)
        for k in keys:
            index[k] = hit
    new = len(merged) - n_existing
    stats = {"retrieved": len(records), "new_unique": new, "total_unique": len(merged),
             "duplicates_merged": len(records) - new}
    return list(merged.values()), stats
