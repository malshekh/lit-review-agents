"""String-level consolidation of theme labels before synthesis.

Code may merge names, never meanings: labels merge only when they are identical after normalizing
case, punctuation, whitespace, boilerplate prefixes ("mechanistic:", "Clinical trials —") and a
trailing plural "s". Whether two differently worded themes are the same is a scientific judgement
that belongs to A07-SYN, which must declare the basis of every group it forms. If merging still
leaves many themes, nothing is merged and A07 does the grouping.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

_PREFIX = re.compile(r"^(?:mechanistic|mechanism|background|clinical trials?|preclinical|clinical)\s*(?::|—|–|\s-\s)\s*",
                     re.IGNORECASE)


def normalize(label: str) -> str:
    s = unicodedata.normalize("NFKC", label).lower().strip()
    s = _PREFIX.sub("", s)
    s = re.sub(r"[_/\-–—]+", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in s.split())


def consolidate(counts: dict[str, int], max_after_merge: int = 40) -> tuple[dict[str, str], dict]:
    """counts: {theme label: number of findings}. Returns ({label: merged label}, summary).
    The merged label is the group's most used original label. If merging leaves `max_after_merge` or
    more themes, the mapping is the identity and summary["applied"] is False."""
    groups: dict[str, list[str]] = defaultdict(list)
    for label in counts:
        groups[normalize(label)].append(label)
    mapping = {lab: max(g, key=lambda x: (counts[x], x)) for g in groups.values() for lab in g}
    merged = {k: sorted(v) for k, v in ((mapping[g[0]], g) for g in groups.values()) if len(v) > 1}
    applied = len(groups) < max_after_merge and bool(merged)
    summary = {"themes_before": len(counts), "themes_after_merge": len(groups), "threshold": max_after_merge,
               "applied": applied, "merged_groups": merged if applied else {},
               "note": ("merged" if applied else
                        "no labels identical after normalization" if not merged else
                        f"{len(groups)} themes after merge (>= {max_after_merge}): sent unmerged for A07 to group")}
    return (mapping if applied else {lab: lab for lab in counts}), summary
