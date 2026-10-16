"""Proposition tags written by A09-WRI: every sentence ends with ⟦P12,P14⟧, ⟦K3⟧, ⟦AI2⟧ or ⟦ORG⟧."""
from __future__ import annotations

import re

TAG_RE = re.compile(r"\s*⟦([^⟧]*)⟧")
CITE_RE = re.compile(r"\[@([^\]]+)\]")
DISPLAY_RE = re.compile(r"\{\{([FT]\d+)\}\}")
GAP_RE = re.compile(r"\[\[GAP:([^\]]+)\]\]")


def strip_tags(text: str) -> str:
    """Remove proposition tags for rendering or word counting."""
    return TAG_RE.sub("", text)


def bindings(text: str) -> list[tuple[str, list[str]]]:
    """Return (sentence, [item_ids]) for every tagged sentence."""
    out, last = [], 0
    for m in TAG_RE.finditer(text):
        sentence = text[last:m.start()].strip()
        ids = [i.strip() for i in m.group(1).split(",") if i.strip()]
        out.append((sentence, ids))
        last = m.end()
    tail = text[last:].strip()
    if tail:
        out.append((tail, []))  # untagged trailing text
    return out


def cited_records(text: str) -> list[str]:
    ids: list[str] = []
    for m in CITE_RE.finditer(text):
        ids += [p.strip().lstrip("@") for p in m.group(1).split(";")]
    return ids
