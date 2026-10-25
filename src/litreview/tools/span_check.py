"""Gate 1 for A06-SV: does each extracted span occur verbatim in the paper, and do its numbers match?"""
from __future__ import annotations

import re
import unicodedata

_QUOTES = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-",
           "\u2212": "-", "\u00a0": " ", "\u2009": " "}
# A sign belongs to a number only when it does not follow a digit: "12.1-56.3" is a range, not -56.3.
_NUM_RE = re.compile(r"(?:(?<![\d.])[-+])?\d+(?:[.,]\d+)?")
# "figure 8 h", "fig. 8 h-j", "table 1", "supplementary figure s2 b": number plus optional panel letters
_DISPLAY_REF_RE = re.compile(r"\b(fig(?:ure)?s?\.?|tables?)\s*(s?\d+)((?:\s*[a-z]\b(?:\s*[-,]\s*[a-z]\b)*)?)")


def _compact_ref(m: re.Match) -> str:
    return f"{m.group(1)} {m.group(2)}{re.sub(r'\s+', '', m.group(3))}"


def normalize(text: str) -> str:
    """Normalize for verbatim comparison. Applied identically to span and paper, so it only removes
    differences that come from text extraction (spacing, quote styles, line breaks), never wording."""
    text = unicodedata.normalize("NFKC", text)
    for a, b in _QUOTES.items():
        text = text.replace(a, b)
    text = re.sub(r"-\s*\n\s*", "", text)        # rejoin hyphenated line breaks
    text = re.sub(r"\s+", " ", text).strip().lower()
    text = re.sub(r"([(\[])\s+", r"\1", text)    # "( figure" -> "(figure"
    text = re.sub(r"\s+([)\]])", r"\1", text)    # "8h )" -> "8h)"
    return _DISPLAY_REF_RE.sub(_compact_ref, text)  # "figure 8 h" -> "figure 8h"


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
