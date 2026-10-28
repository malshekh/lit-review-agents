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


def detail_report(events: list[dict], entries: list[dict]) -> dict | None:
    """How often A10 asks for detail and for how much, so it can be seen whether scoping pays. If most passes
    ask for the full MAX_DETAIL, one large call has become two medium ones."""
    passes = [e for e in events if e.get("type") == "tool_run" and e.get("tool") == "verification_scope"]
    if not passes:
        return None
    sent = [p["summary"].get("detail_sent", p["summary"].get("detail_requested", 0)) for p in passes]
    asked = [p["summary"].get("detail_requested", 0) for p in passes]

    def calls(detail: bool) -> dict:
        rows = [e for e in entries if e["agent"] == "A10-RV" and e["step"].endswith("_detail") == detail]
        tokens = [e["input_tokens"] + e.get("cached_input_tokens", 0) + e.get("cache_write_tokens", 0)
                  + e.get("cache_write_1h_tokens", 0) for e in rows]
        return {"calls": len(rows), "cost_usd": round(sum(e["cost_usd"] or 0 for e in rows), 4),
                "input_tokens_avg": round(sum(tokens) / len(tokens)) if tokens else None}
    at_cap = sum(n >= MAX_DETAIL for n in sent)
    with_requests = sum(n > 0 for n in asked)
    if not with_requests:
        verdict = "NO_REQUESTS"
    elif at_cap * 2 >= len(passes):
        verdict = "ROUTINELY_AT_CAP"      # scoping may not pay: two medium calls instead of one large
    elif with_requests * 2 >= len(passes):
        verdict = "FREQUENT"
    else:
        verdict = "RARE"
    return {"passes": len(passes), "passes_with_requests": with_requests, "records_requested": asked,
            "records_sent": sent, "passes_at_cap": at_cap, "cap": MAX_DETAIL, "verdict": verdict,
            "first_calls": calls(False), "detail_calls": calls(True),
            "scope": [{"step": p["step"], "bound_in_full": p["summary"].get("bound_in_full"),
                       "contradiction_index": p["summary"].get("contradiction_index")} for p in passes]}


def detail_report_text(r: dict | None) -> str:
    if not r:
        return "A10 detail rounds: A10 has not run yet."
    f, d = r["first_calls"], r["detail_calls"]
    note = {"NO_REQUESTS": "A10 has not asked for any record in full.",
            "RARE": "Rare requests: scoping is working as intended.",
            "FREQUENT": "Frequent requests: watch the detail-call cost against the first-call saving.",
            "ROUTINELY_AT_CAP": "Routinely at the cap: one large call has become two medium ones; scoping may "
                                "not pay."}[r["verdict"]]
    return (f"A10 detail rounds: {r['passes_with_requests']} of {r['passes']} passes asked for records in full; "
            f"records requested per pass {r['records_requested']} (cap {r['cap']}, reached {r['passes_at_cap']}x). "
            f"First calls: {f['calls']}, ${f['cost_usd']:.2f}, ~{f['input_tokens_avg'] or 0:,d} input tokens each. "
            f"Detail calls: {d['calls']}, ${d['cost_usd']:.2f}"
            + (f", ~{d['input_tokens_avg']:,d} input tokens each" if d["input_tokens_avg"] else "") + f". {note}")


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
