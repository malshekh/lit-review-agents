"""Reference handling: Crossref lookup, numbering by first citation, Nature-style formatting.

Nature style (journal_scirev.yaml): numbered in order of first citation, in square brackets;
all authors unless 6 or more, then first author et al.; 'Surname, I.'; sentence-case title;
italic abbreviated journal; bold volume; page range or article number; year in parentheses.
"""
from __future__ import annotations

import requests

from .tags import cited_records

CROSSREF = "https://api.crossref.org/works/"


def crossref_lookup(doi: str, mailto: str | None = None, timeout: int = 20) -> dict | None:
    params = {"mailto": mailto} if mailto else None
    r = requests.get(CROSSREF + doi, params=params, timeout=timeout)
    if r.status_code != 200:
        return None
    return r.json().get("message")


def is_retracted(crossref_msg: dict) -> bool:
    """Crossref marks retractions via 'update-to' / 'updated-by' relations."""
    for rel in (crossref_msg.get("updated-by") or []) + (crossref_msg.get("update-to") or []):
        if str(rel.get("type", "")).lower() in {"retraction", "removal", "withdrawal"}:
            return True
    return False


def number_citations(sections_text: list[str]) -> dict[str, int]:
    """Assign numbers to record IDs in order of first citation."""
    order: dict[str, int] = {}
    for text in sections_text:
        for rid in cited_records(text):
            if rid not in order:
                order[rid] = len(order) + 1
    return order


def _author(a: dict) -> str:
    family = a.get("family", "").strip()
    initials = " ".join(f"{p[0]}." for p in a.get("given", "").replace("-", " ").split() if p)
    return f"{family}, {initials}".strip(", ")


def format_nature(meta: dict) -> str:
    """meta uses Crossref field names: author, title, container-title-short/container-title,
    volume, page or article-number, issued, DOI."""
    authors = meta.get("author") or []
    if len(authors) >= 6:
        auth = f"{_author(authors[0])} et al."
    elif authors:
        names = [_author(a) for a in authors]
        auth = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " & " + names[-1]
    else:
        auth = ""
    title = (meta.get("title") or [""])[0].rstrip(".")
    journal = ((meta.get("short-container-title") or meta.get("container-title-short")
                or meta.get("container-title") or [""]))
    journal = journal[0] if isinstance(journal, list) else journal
    vol = meta.get("volume", "")
    pages = meta.get("page") or meta.get("article-number") or ""
    year = ""
    parts = (meta.get("issued") or {}).get("date-parts") or [[None]]
    if parts and parts[0] and parts[0][0]:
        year = str(parts[0][0])
    out = f"{auth} {title}. *{journal}*"
    if vol:
        out += f" **{vol}**,"
    if pages:
        out += f" {pages}"
    out += f" ({year})." if year else "."
    return " ".join(out.split())
