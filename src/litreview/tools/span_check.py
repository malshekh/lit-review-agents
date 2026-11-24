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
        for key in ('raw_value', 'p_value', 'n', 'variance_or_ci'):
            for n in numbers_in(str(q.get(key) or '')):
                if n not in in_span:return False
        unit = q.get('raw_unit')
        if unit and unit not in ('NOT_REPORTED','NOT_APPLICABLE'):
            def unit_text(s):
                return unicodedata.normalize('NFKC', s).replace('\u03bc','u')
            u = re.sub(r'\s+', '', unit_text(unit))
            pattern = (r'(?<![A-Za-z])' if u[:1].isalpha() else '') + r'\s*'.join(re.escape(c) for c in u)
            pattern += r'(?![A-Za-z])' if u[-1:].isalpha() else ''
            if not re.search(pattern, unit_text(span)):
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


def passed(result: dict) -> bool:
    return (all(result.get(k) is True for k in ('span_found', 'numbers_match', 'premise_spans_found'))
            and result.get('location_matches') is not False)


def repair_findings(extraction: dict, sections: dict[str, str]) -> dict:
    """Restore unique literal source boundaries; never choose among numerical readings.

    Expand an explicit ellipsis only if all quoted pieces occur in order in one
    unique bounded source passage. A missing trailing value can be extended only
    when it immediately follows the exact quote (not in a neighboring sentence).
    The replacement is always a verbatim substring of the supplied source.
    """
    import copy
    out = copy.deepcopy(extraction)
    for f, gate in zip(out.get('findings', []), check_findings(extraction, sections)):
        if passed(gate):continue
        original = f.get('span', '')
        candidates = []
        parts = re.split(r'\s*(?:\.{3}|\u2026)\s*', original)
        if 1 < len(parts) <= 4 and all(len(p) >= 12 for p in parts):
            pattern = r'[\s\S]{0,1200}?'.join(re.escape(p).replace(r'\ ', r'\s+') for p in parts)
            for section, text in sections.items():
                for match in re.finditer(pattern, text):
                    candidates.append((section, match.start(), match.end(), match.group()))
        elif gate['span_found'] and not gate['numbers_match'] and not numbers_in(original):
            qs = f.get('quantities') or []
            if len(qs) == 1 and re.fullmatch(r'\d+(?:\.\d+)?', str(qs[0].get('raw_value', ''))):
                value = str(qs[0]['raw_value'])
                for section, text in sections.items():
                    pattern = re.escape(original) + r'\s*[:=]?\s*' + re.escape(value) + r'(?![\d.])'
                    unit = qs[0].get('raw_unit')
                    if unit and unit not in ('NOT_REPORTED','NOT_APPLICABLE'):
                        unit = unicodedata.normalize('NFKC', unit).replace('\u03bc','u')
                        pattern += r'\s*' + r'\s*'.join('[u\u00b5\u03bc]' if c=='u' else re.escape(c)
                                                        for c in re.sub(r'\s+','',unit))
                        if unit[-1:].isalpha():pattern += r'(?![A-Za-z])'
                    for match in re.finditer(pattern, text):
                        candidates.append((section, match.start(), match.end(), match.group()))
        if len(candidates) != 1:continue
        section, start, end, replacement = candidates[0]
        trial = {**f, 'span':replacement, 'span_location':{**(f.get('span_location') or {}), 'section':section}}
        if not passed(check_findings({'findings':[trial]}, sections)[0]):continue
        f.update(span=replacement, span_location=trial['span_location'])
        f.setdefault('span_corrections', []).append({'original_span':original, 'corrected_span':replacement,
            'section':section, 'start':start, 'end':end, 'method':'unique_literal_boundary_expansion'})
    return out
