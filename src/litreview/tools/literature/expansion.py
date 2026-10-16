"""Citation expansion (A03-LM §4.5): backward (references) and forward (citations) from qualified seeds.

Seeds are records A04-CQ qualified as PRIMARY evidence from the families A03-LM named for
expansion, plus every qualified contrary-evidence record — so heavily cited supportive work does
not crowd out less-cited counter-evidence. Uses Semantic Scholar; depth 1. Citation count is
discovery metadata only, never a signal of importance.
"""
from __future__ import annotations

from .base import Record
from .semanticscholar import neighbours


def choose_seeds(quals: list[dict], records: list[dict], seed_families: list[str]) -> list[dict]:
    by_id = {r["record_id"]: r for r in records}
    seeds = []
    for q in quals:
        if q.get("disposition") != "QUALIFIED" or q.get("role") == "CONTEXT":
            continue
        rec = by_id.get(q["record_id"])
        if not rec:
            continue
        from_family = bool(set(rec.get("query_family_ids", [])) & set(seed_families))
        if from_family or q.get("is_contrary_evidence"):
            seeds.append(rec)
    return seeds


def expand(seeds: list[dict], directions: list[str], max_per_seed: int, max_total: int) -> tuple[list[Record], list[dict]]:
    found: list[Record] = []
    log: list[dict] = []
    for seed in seeds:
        for direction in directions:
            if len(found) >= max_total:
                log.append({"note": f"max_total {max_total} reached; remaining seeds not expanded"})
                return found, log
            fam = "CITEXP:" + ("FWD" if direction == "citations" else "BWD")
            recs, err = neighbours(seed, direction, max_per_seed, fam)
            for r in recs:
                r.expansion = {"seed_record_id": seed["record_id"], "direction": direction, "depth": 1}
            found += recs[: max_total - len(found)]
            log.append({"seed": seed["record_id"], "direction": direction, "returned": len(recs), "error": err})
    return found, log
