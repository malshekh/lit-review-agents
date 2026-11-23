"""Reference handling: Crossref lookup, retraction check, numbering by first citation, Nature-style formatting.

Nature style (journal_scirev.yaml): numbered in order of first citation, in square brackets;
all authors unless 6 or more, then first author et al.; 'Surname, I.'; sentence-case title;
italic abbreviated journal; bold volume; page range or article number; year in parentheses.

Crossref is asked once per DOI per run: answers (including "not found") are cached on disk, transient failures
(timeouts, 429, 5xx) are retried with backoff, and a lookup that still fails raises LookupFailed instead of
being read as "no metadata": an outage must never turn into a silently unchecked retraction or a guessed
reference. A record Crossref cannot confirm, or whose Crossref title does not match the paper that was read,
is formatted from the corpus record with every author it has and reported as a problem that blocks
submission-ready; the manuscript text never carries a marker such as [CHECK FORMAT].
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import requests

from .tags import CITE_RE, cited_records

CROSSREF = "https://api.crossref.org/works/"
RETRACTION_TYPES = {"retraction", "removal", "withdrawal"}
CONCERN_TYPES = {"expression_of_concern", "expression-of-concern", "expression of concern"}
TITLE_MATCH_MIN = 0.85


class LookupFailed(RuntimeError):
    """Crossref could not be reached for a DOI after every retry. Not the same as 'no such DOI'."""


class UnknownCitation(ValueError):
    """The text cites a record ID that has no number or no corpus record."""


def _cache_file(cache_dir: Path, doi: str) -> Path:
    return Path(cache_dir) / (hashlib.sha256(doi.strip().lower().encode("utf-8")).hexdigest()[:32] + ".json")


def crossref_lookup(doi: str, mailto: str | None = None, timeout: int = 20, cache_dir: Path | None = None,
                    retries: int = 3, sleep=time.sleep) -> dict | None:
    """The Crossref `message` for a DOI; None when Crossref has no such DOI (404). Raises LookupFailed when it
    cannot be reached. With cache_dir, a previous answer for the DOI is returned without a request."""
    doi = (doi or "").strip()
    if not doi:
        return None
    if cache_dir is not None:
        f = _cache_file(cache_dir, doi)
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))["message"]
    params = {"mailto": mailto} if mailto else None
    last = ""
    for attempt in range(retries + 1):
        try:
            r = requests.get(CROSSREF + doi, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}: {exc}"
        else:
            if r.status_code == 200:
                message = r.json().get("message")
                break
            if r.status_code == 404:
                message = None
                break
            last = f"HTTP {r.status_code}"
            if r.status_code not in (408, 425, 429) and r.status_code < 500:
                raise LookupFailed(f"Crossref refused the lookup of {doi}: {last}")
        if attempt < retries:
            sleep(min(2 ** attempt, 30))
    else:
        raise LookupFailed(f"Crossref could not be reached for {doi} after {retries + 1} attempts ({last})")
    if cache_dir is not None:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        _cache_file(cache_dir, doi).write_text(json.dumps(
            {"doi": doi, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "message": message}, ensure_ascii=False),
            encoding="utf-8")
    return message


def _relations(crossref_msg: dict) -> list[str]:
    rels = (crossref_msg.get("updated-by") or []) + (crossref_msg.get("update-to") or [])
    return [str(rel.get("type", "")).lower() for rel in rels]


def is_retracted(crossref_msg: dict) -> bool:
    """Crossref marks retractions via 'update-to' / 'updated-by' relations (Retraction Watch data included)."""
    return any(t in RETRACTION_TYPES for t in _relations(crossref_msg or {}))


def has_expression_of_concern(crossref_msg: dict) -> bool:
    return any(t in CONCERN_TYPES for t in _relations(crossref_msg or {}))


def retraction_report(records: list[dict], mailto: str | None = None, cache_dir: Path | None = None,
                      lookup=None) -> dict:
    """Retraction status of every record: {"retracted": [...], "concern": [...], "unchecked": [...], "checked": n}.
    `unchecked` lists records with no DOI or an unreachable/unknown DOI: they are reported, never assumed clean."""
    lookup = lookup or crossref_lookup
    out = {"retracted": [], "concern": [], "unchecked": [], "checked": 0}
    for r in records:
        rid, doi = r.get("record_id"), (r.get("doi") or "").strip()
        if not doi:
            out["unchecked"].append({"record_id": rid, "reason": "no DOI"})
            continue
        try:
            msg = lookup(doi, mailto, cache_dir=cache_dir)
        except LookupFailed as exc:
            out["unchecked"].append({"record_id": rid, "doi": doi, "reason": str(exc)})
            continue
        if msg is None:
            out["unchecked"].append({"record_id": rid, "doi": doi, "reason": "DOI not found in Crossref"})
            continue
        out["checked"] += 1
        if is_retracted(msg):
            out["retracted"].append({"record_id": rid, "doi": doi, "title": r.get("title")})
        elif has_expression_of_concern(msg):
            out["concern"].append({"record_id": rid, "doi": doi, "title": r.get("title")})
    return out


def number_citations(sections_text: list[str]) -> dict[str, int]:
    """Assign numbers to record IDs in order of first citation."""
    order: dict[str, int] = {}
    for text in sections_text:
        for rid in cited_records(text):
            if rid not in order:
                order[rid] = len(order) + 1
    return order


def render_citations(text: str, numbers: dict[str, int], where: str = "text") -> str:
    """Replace every [@ID; @ID] with [n,m]. An ID without a number, or an empty citation, raises: the old
    renderer dropped unknown IDs and could print "[]", which reads as a citation and supports nothing."""
    def cite(match):
        ids = [p.strip().lstrip("@") for p in match.group(1).split(";") if p.strip().lstrip("@")]
        unknown = [i for i in ids if i not in numbers]
        if unknown or not ids:
            raise UnknownCitation(f"{where}: citation {match.group(0)!r} names "
                                  + (f"unknown record ID(s) {', '.join(unknown)}" if unknown else "no record"))
        return "[" + ",".join(str(n) for n in sorted({numbers[i] for i in ids})) + "]"
    return CITE_RE.sub(cite, text)


def _norm_title(title: str) -> str:
    t = unicodedata.normalize("NFKD", re.sub(r"<[^>]+>", "", title or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t.lower()).split())


def title_similarity(crossref_msg: dict, record_title: str) -> float:
    cr = _norm_title((crossref_msg.get("title") or [""])[0])
    ours = _norm_title(record_title)
    if not cr or not ours:
        return 0.0
    return SequenceMatcher(None, cr, ours).ratio()


def _author(a: dict) -> str:
    family = a.get("family", "").strip()
    initials = " ".join(f"{p[0]}." for p in a.get("given", "").replace("-", " ").split() if p)
    return f"{family}, {initials}".strip(", ") or (a.get("name") or "").strip()


def _join_authors(names: list[str]) -> str:
    names = [n for n in names if n]
    if len(names) >= 6:
        return f"{names[0]} et al."
    if not names:
        return ""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " & " + names[-1]


def format_nature(meta: dict) -> str:
    """meta uses Crossref field names: author, title, container-title-short/container-title,
    volume, page or article-number, issued, DOI."""
    auth = _join_authors([_author(a) for a in meta.get("author") or []])
    title = re.sub(r"<[^>]+>", "", (meta.get("title") or [""])[0]).rstrip(".")
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


def format_from_record(record: dict) -> str:
    """Nature-style reference from the corpus record alone (no Crossref metadata): every author the record has,
    under the same six-author rule, with whatever of venue and year is known. Author strings are used as
    retrieved, so their form (initials, order) still needs a human check; the caller reports that."""
    auth = _join_authors([str(a).strip() for a in record.get("authors") or []])
    title = str(record.get("title") or "").rstrip(".")
    venue, year = record.get("venue") or "", record.get("year") or ""
    out = f"{auth} {title}." + (f" *{venue}*" if venue else "") + (f" ({year})." if year else "")
    return " ".join(out.split())


def build_reference(record: dict, mailto: str | None = None, cache_dir: Path | None = None,
                    lookup=None) -> tuple[str, list[str], dict | None]:
    """(reference text without its number, problems, Crossref message or None) for one cited record."""
    lookup = lookup or crossref_lookup
    problems: list[str] = []
    rid = record.get("record_id")
    if not record.get("title"):
        raise UnknownCitation(f"cited record {rid} has no corpus entry (no title): it cannot be referenced")
    meta = None
    doi = (record.get("doi") or "").strip()
    if not doi:
        problems.append("no DOI: formatted from the retrieved record; check authors, journal, volume and pages")
    else:
        try:
            meta = lookup(doi, mailto, cache_dir=cache_dir)
        except LookupFailed as exc:
            problems.append(f"Crossref unavailable ({exc}): formatted from the retrieved record; re-run the export")
        else:
            if meta is None:
                problems.append(f"DOI {doi} is not in Crossref: formatted from the retrieved record; check it")
            else:
                sim = title_similarity(meta, record["title"])
                if sim < TITLE_MATCH_MIN:
                    problems.append(
                        f"DOI {doi} resolves to a different title in Crossref (similarity {sim:.2f}: "
                        f"{(meta.get('title') or [''])[0][:120]!r}); the DOI may belong to another paper. "
                        "Formatted from the retrieved record; correct the DOI")
                    meta = None
    if meta is not None:
        if is_retracted(meta):
            problems.append("RETRACTED according to Crossref: remove the citation or record why it is cited")
        elif has_expression_of_concern(meta):
            problems.append("expression of concern recorded in Crossref: check before citing")
        text = format_nature(meta)
        if not (meta.get("author") or []):
            problems.append("Crossref lists no authors: add them by hand")
    else:
        text = format_from_record(record)
    return text, problems, meta
