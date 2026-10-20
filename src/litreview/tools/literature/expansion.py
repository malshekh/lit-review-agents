"""Citation expansion (A03-LM §4.5): backward (references) and forward (citations) from qualified seeds.

Depth 1 seeds are records A04-CQ qualified as PRIMARY evidence from the families A03-LM named for
expansion, plus every qualified contrary-evidence record — so heavily cited supportive work does
not crowd out less-cited counter-evidence. Depth 2 (config `citation_expansion.depth: 2`, for
sparse topics) seeds from the depth-1 records A04-CQ then qualified, by the same rule. Uses
Semantic Scholar. Citation count is discovery metadata only, never a signal of importance.
"""
from __future__ import annotations

from .base import Record
from .semanticscholar import neighbours


def _qualified_primary(q: dict) -> bool:
    return q.get("disposition") == "QUALIFIED" and q.get("role") != "CONTEXT"


def choose_seeds(quals: list[dict], records: list[dict], seed_families: list[str]) -> list[dict]:
    by_id = {r["record_id"]: r for r in records}
    seeds = []
    for q in quals:
        if not _qualified_primary(q):
            continue
        rec = by_id.get(q["record_id"])
        if not rec:
            continue
        from_family = bool(set(rec.get("query_family_ids", [])) & set(seed_families))
        if from_family or q.get("is_contrary_evidence"):
            seeds.append(rec)
    return seeds


def choose_next_seeds(quals: list[dict], records: list[dict], found_at_depth: int) -> list[dict]:
    """Seeds for the next depth: qualified, non-context records first found at `found_at_depth`."""
    by_id = {r["record_id"]: r for r in records}
    return [by_id[q["record_id"]] for q in quals if _qualified_primary(q) and q["record_id"] in by_id
            and (by_id[q["record_id"]].get("expansion") or {}).get("depth") == found_at_depth]


def expand(seeds: list[dict], directions: list[str], max_per_seed: int, max_total: int,
           depth: int = 1) -> tuple[list[Record], list[dict]]:
    found: list[Record] = []
    log: list[dict] = []
    for seed in seeds:
        for direction in directions:
            if len(found) >= max_total:
                log.append({"depth": depth, "note": f"expansion cap reached ({max_total} new records at this "
                                                    "depth); remaining seeds not expanded"})
                return found, log
            fam = "CITEXP:" + ("FWD" if direction == "citations" else "BWD")
            recs, err = neighbours(seed, direction, max_per_seed, fam)
            for r in recs:
                r.expansion = {"seed_record_id": seed["record_id"], "direction": direction, "depth": depth}
            found += recs[: max_total - len(found)]
            log.append({"depth": depth, "seed": seed["record_id"], "direction": direction,
                        "returned": len(recs), "error": err})
    return found, log
