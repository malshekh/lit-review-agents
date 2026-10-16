"""Gate 1 for A06-SV: does each extracted span occur verbatim in the paper, and do its numbers match?"""
from __future__ import annotations

import re
import unicodedata

_QUOTES = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-",
           "\u2212": "-", "\u00a0": " ", "\u2009": " "}
_NUM_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for a, b in _QUOTES.items():
        text = text.replace(a, b)
    text = re.sub(r"-\s*\n\s*", "", text)        # rejoin hyphenated line breaks
    return re.sub(r"\s+", " ", text).strip().lower()


def span_found(span: str, source_text: str) -> bool:
    return bool(span) and normalize(span) in normalize(source_text)


def numbers_in(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUM_RE.findall(normalize(text))}


def numbers_match(span: str, quantities: list[dict]) -> bool:
    """Every raw value recorded for a finding must appear in its span."""
    in_span = numbers_in(span)
    for q in quantities or []:
        for n in numbers_in(str(q.get("raw_value", ""))):
            if n not in in_span:
                return False
    return True


def check_findings(extraction: dict, sections: dict[str, str]) -> list[dict]:
    """Return gate1 results for every finding in an A05-KE output.

    sections: {section_name: text} for the paper as A05-KE inspected it.
    """
    full = "\n".join(sections.values())
    results = []
    for f in extraction.get("findings", []):
        span = f.get("span", "")
        loc = (f.get("span_location") or {}).get("section") or ""
        sec_text = sections.get(loc, "")
        results.append({
            "finding_id": f.get("finding_id"),
            "span_found": span_found(span, full),
            "location_matches": span_found(span, sec_text) if sec_text else None,
            "numbers_match": numbers_match(span, f.get("quantities", [])),
            "premise_spans_found": all(span_found(p, full) for p in f.get("premise_spans", []) or []),
        })
    return results
