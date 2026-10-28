"""What A10-RV is sent: the findings the manuscript's claims are bound to, in full, and a compact
contradiction index of every other validated finding.

Sending every validated finding in full puts A10 over GPT-6.1's 272k long-context threshold (run
20261025-100039: 210,724 tokens of findings alone). Sending only the cited ones would hide exactly what
verification must catch: a finding that contradicts a claim is, by construction, not cited by it. So every
uncited finding stays visible, reduced to its ID, its assertion (A06's plain-language limit, else its
source span) and its disposition: enough to flag a conflict and request the record, not the record itself.

Binding chain: manuscript tags (⟦P3,K1⟧) and the plan's claim-bearing proposition lists (title, abstract,
headings, display items) -> package and plan items with that ID -> the finding IDs they hold, following
proposition references (`*proposition_ids`, `established_by`) but not group membership, which would pull in
every sibling proposition.
"""
from __future__ import annotations

import json
import re

from . import tags

FINDING_RE = re.compile(r"\bR\d{4,}:F\d+\b")
MAX_DETAIL = 40   # records sent in the detail round; the rest of a longer request is logged as ignored


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def _follows(key: str) -> bool:
    return "proposition_id" in key or key == "established_by"


def _index(*docs) -> dict[str, list[dict]]:
    """Every dict that names itself with an `..._id` key, under that ID (P3 is both a package proposition
    and a plan item)."""
    idx: dict[str, list[dict]] = {}
    for doc in docs:
        for d in _walk(doc):
            for k, v in d.items():
                if k.endswith("_id") and isinstance(v, str) and v:
                    idx.setdefault(v, []).append(d)
    return idx


def seeds(manuscript: dict, plan: dict) -> set[str]:
    """Item IDs the manuscript's claim-bearing elements are bound to."""
    out = set()
    for text in _strings(manuscript):
        out |= {i for _, ids in tags.bindings(text) for i in ids if i != "ORG"}
    for d in _walk(plan or {}):
        for k, v in d.items():
            if "proposition_ids" in k and isinstance(v, list):
                out |= {x for x in v if isinstance(x, str)}
    return out


def bound_findings(ids: set[str], idx: dict[str, list[dict]]) -> set[str]:
    found, seen, queue = set(), set(), list(ids)
    while queue:
        i = queue.pop()
        if i in seen:
            continue
        seen.add(i)
        for d in idx.get(i, []):
            found |= set(FINDING_RE.findall(json.dumps(d, ensure_ascii=False)))
            for k, v in d.items():
                if _follows(k):
                    queue += [x for x in (v if isinstance(v, list) else [v]) if isinstance(x, str) and x in idx]
    return found


def index_line(f: dict) -> dict:
    assertion = f.get("plain_language_limit") or (f.get("span") or "")[:300]
    return {"finding_id": f["finding_id"], "assertion": assertion, "disposition": f.get("disposition")}


def scope(manuscript: dict, plan: dict, package: dict, findings: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """(full records bound to the manuscript, contradiction index of the rest, sizes for provenance)."""
    ids = seeds(manuscript, plan)
    bound = bound_findings(ids, _index(package or {}, plan or {}))
    bound |= set(FINDING_RE.findall(json.dumps(manuscript, ensure_ascii=False)))
    full = [f for f in findings if f["finding_id"] in bound]
    index = [index_line(f) for f in findings if f["finding_id"] not in bound]
    stats = {"findings_total": len(findings), "bound_in_full": len(full), "contradiction_index": len(index),
             "tagged_items": len(ids),
             "chars_full": len(json.dumps(full, ensure_ascii=False)),
             "chars_index": len(json.dumps(index, ensure_ascii=False)),
             "chars_all_findings_in_full": len(json.dumps(findings, ensure_ascii=False))}
    return full, index, stats


def requested(rv: dict, index: list[dict]) -> tuple[list[str], list[str]]:
    """Finding IDs A10 asked to see in full that are in the index, capped at MAX_DETAIL; and the rest."""
    in_index = {i["finding_id"] for i in index}
    asked = []
    for r in rv.get("detail_requests") or []:
        fid = r.get("finding_id") if isinstance(r, dict) else r
        if isinstance(fid, str) and fid not in asked:
            asked.append(fid)
    ok = [f for f in asked if f in in_index]
    return ok[:MAX_DETAIL], ok[MAX_DETAIL:] + [f for f in asked if f not in in_index]
