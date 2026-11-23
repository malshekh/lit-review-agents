"""Deterministic checks for wording that overstates what a source can support.

Each rule exists as a prompt instruction (prompts/shared) AND here as code with regression fixtures
(tests/test_science_rules.py), because an instruction alone was not enough in the pilot. A flag is not a verdict:
it marks a sentence a person or A10 must look at, with the reason. Flags are listed with the export and block
submission-ready until each has been reviewed (final/science_lint_reviewed.json).

  COPPER_ABSENCE          "without copper", "copper-free": a paper that reports no copper supplement has not shown
                          copper-free conditions (serum, medium and tissue supply copper).
  NULL_FROM_NONSIGNIFICANCE  "had no effect", "did not alter", "was ineffective", "equivalent": absence of a
                          significant difference is not absence of an effect.
  UNDEFINED_MEDIAN        a median survival that was "not defined" is not a benefit, and it is "not reached" only
                          if the source says so.
  PERCENT_WITHOUT_COMPARATOR  "x% viability" with no reference named: a percentage does not identify its control.
  REPLICATION_CLAIM       "independently replicated", "consistent across studies": needs A06's independence count;
                          several papers on one underlying study are one study.
  ABSTRACT_OVERREACH      a sentence citing only abstract-level papers that describes methods, figures,
                          supplements, sample size or bias assessment.
"""
from __future__ import annotations

import hashlib
import re

from .tags import CITE_RE, cited_records, strip_tags

RULES = [
    ("COPPER_ABSENCE",
     re.compile(r"\b(copper[- ]free|without (added |supplemental |exogenous )?copper|in the absence of copper|no copper\b(?! supplement))", re.I),
     "The source must have excluded or measured copper. If it only reports no supplement, write "
     "\"no copper supplementation reported\"."),
    ("NULL_FROM_NONSIGNIFICANCE",
     re.compile(r"\b(ha[sd] no effect|show(ed|s) no effect|no effect on|did not (alter|affect|change|influence|improve|reduce|increase)|"
                r"was ineffective|were ineffective|is ineffective|(was|were) equivalent|no difference (in|between)|failed to (affect|alter|improve))\b", re.I),
     "Write this only if the source established the absence of an effect. A non-significant comparison is "
     "\"did not differ significantly\", with the values, n and test the source gives."),
    ("UNDEFINED_MEDIAN",
     re.compile(r"\bmedian (overall |progression[- ]free )?survival\b[^.]{0,80}\b(not reached|undefined|not defined|could not be (defined|estimated))", re.I),
     "Report the median in the source's own words. \"Not defined\" is not \"not reached\" unless the source says so, "
     "and neither is a survival benefit without a reported test."),
    ("PERCENT_WITHOUT_COMPARATOR",
     re.compile(r"\b\d+(\.\d+)?\s?(±\s?\d+(\.\d+)?\s?)?%\s+(viability|survival|growth|inhibition|of control)\b", re.I),
     "Name the comparator the percentage refers to, or say the source does not state it."),
    ("REPLICATION_CLAIM",
     re.compile(r"\b(independent(ly)? (replicat|confirm|validat)\w*|replicated (in|by|across)|consistent(ly)? across (studies|reports|groups|laboratories)|"
                r"(two|three|four|five|several|multiple) independent (studies|groups|cohorts))\b", re.I),
     "Needs the independence count from the theme audit. Papers reporting the same study, cohort or dataset are one study."),
]
COMPARATOR_NAMED = re.compile(r"\b(relative to|compared (with|to)|versus|vs\.?|of (the )?(untreated|vehicle|parental|control)|"
                              r"(untreated|vehicle|parental) (cells|control|group)|control (cells|group))\b", re.I)
ABSTRACT_OVERREACH = re.compile(r"\b(method(s|ology)?|figure|fig\.|supplement(ary)?|sample size|risk of bias|randomi[sz]\w+|blind(ed|ing)|"
                                r"power calculation|statistical analysis plan|western blot|flow cytometry)\b", re.I)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[(])")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_SPLIT.split(" ".join(strip_tags(text).split())) if s.strip()]


def key(sentence: str, rule: str) -> str:
    return hashlib.sha256(f"{rule}|{' '.join(sentence.split())}".encode("utf-8")).hexdigest()[:16]


def check_text(text: str, access: dict[str, str] | None = None, where: str = "") -> list[dict]:
    """Flags for one piece of manuscript text. access: {record_id: "FULL_TEXT" | "ABSTRACT"} for the cited papers."""
    out = []
    for s in sentences(text):
        cited = cited_records(s)
        plain = CITE_RE.sub("", s)
        for rule, pattern, advice in RULES:
            m = pattern.search(plain)
            if not m:
                continue
            if rule == "PERCENT_WITHOUT_COMPARATOR" and COMPARATOR_NAMED.search(plain):
                continue
            out.append({"rule": rule, "match": m.group(0), "sentence": s, "where": where, "cited": cited,
                        "advice": advice, "key": key(s, rule)})
        if cited and access and all(access.get(r) == "ABSTRACT" for r in cited):
            m = ABSTRACT_OVERREACH.search(plain)
            if m:
                out.append({"rule": "ABSTRACT_OVERREACH", "match": m.group(0), "sentence": s, "where": where,
                            "cited": cited, "key": key(s, "ABSTRACT_OVERREACH"),
                            "advice": "Every cited paper here was read as an abstract only. Say only what the abstracts "
                                      "state; methods, figures, supplements and bias were not available."})
    return out


def check_manuscript(manuscript: dict, access: dict[str, str] | None = None) -> list[dict]:
    flags = []
    for name in ("title", "abstract"):
        flags += check_text(manuscript.get(name) or "", access, name)
    for s in manuscript.get("sections", []):
        flags += check_text(s.get("text_markdown") or "", access, f"section {s.get('section_id') or s.get('heading')}")
    return flags


def unreviewed(flags: list[dict], reviewed: dict | None) -> list[dict]:
    """Flags without a recorded review. reviewed: {key: {"by": name, "note": text}}."""
    done = {k for k, v in (reviewed or {}).items() if str((v or {}).get("by") or "").strip()}
    return [f for f in flags if f["key"] not in done]
