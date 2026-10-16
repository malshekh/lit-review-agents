"""Semantic Scholar Academic Graph API. Docs: https://api.semanticscholar.org/api-docs/

- search():     bulk search (boolean syntax), or seed-based recommendations when the
                query starts with "recommend:".
- citations() / references(): used by citation expansion.
Set S2_API_KEY in .env for higher rate limits.
"""
from __future__ import annotations

import os
import re
import time

import requests

from .base import Record, SearchResult

GRAPH = "https://api.semanticscholar.org/graph/v1"
RECS = "https://api.semanticscholar.org/recommendations/v1/papers/"
FIELDS = "paperId,title,abstract,authors,year,venue,publicationTypes,externalIds,isOpenAccess"


def _headers() -> dict:
    key = os.environ.get("S2_API_KEY")
    return {"x-api-key": key} if key else {}


def _get(url: str, params: dict, retries: int = 3) -> requests.Response:
    for i in range(retries):
        r = requests.get(url, params=params, headers=_headers(), timeout=30)
        if r.status_code != 429:
            return r
        time.sleep(2 ** i)   # rate-limited: back off
    return r


def to_record(p: dict, family_id: str, source: str = "semanticscholar") -> Record:
    ext = p.get("externalIds") or {}
    return Record(
        source=source, title=p.get("title") or "", abstract=p.get("abstract") or "",
        authors=[a.get("name", "") for a in p.get("authors") or []], year=p.get("year"),
        venue=p.get("venue") or "", publication_type=p.get("publicationTypes") or [],
        doi=ext.get("DOI"), pmid=str(ext["PubMed"]) if ext.get("PubMed") else None,
        pmcid=f"PMC{ext['PubMedCentral']}" if ext.get("PubMedCentral") else None,
        is_preprint="arXiv" in ext or (p.get("venue") or "").lower() in {"biorxiv", "medrxiv", "arxiv"},
        open_access=p.get("isOpenAccess"), s2_id=p.get("paperId"), query_family_id=family_id)


def _ids(text: str) -> list[str]:
    out = []
    for t in [x.strip() for x in re.split(r"[,\n]", text) if x.strip()]:
        out.append(t if ":" in t and not t.lower().startswith("10.") else f"DOI:{t}")
    return out


def search(query: str, family_id: str, max_records: int = 200) -> SearchResult:
    try:
        if query.lower().startswith("recommend:"):
            pos, _, neg = query[len("recommend:"):].partition(";")
            neg = neg.split(":", 1)[1] if ":" in neg else neg
            r = requests.post(RECS, params={"fields": FIELDS, "limit": min(max_records, 500)},
                              json={"positivePaperIds": _ids(pos), "negativePaperIds": _ids(neg)},
                              headers=_headers(), timeout=30)
            r.raise_for_status()
            papers = r.json().get("recommendedPapers", [])
            return SearchResult("semanticscholar", family_id, query, len(papers),
                                [to_record(p, family_id) for p in papers])
        records, token, total = [], None, None
        while len(records) < max_records:
            params = {"query": query, "fields": FIELDS}
            if token:
                params["token"] = token
            r = _get(f"{GRAPH}/paper/search/bulk", params)
            if r.status_code == 400:
                return SearchResult("semanticscholar", family_id, query, None, [], f"QUERY_INVALID: {r.text[:200]}")
            r.raise_for_status()
            data = r.json()
            total = data.get("total", total)
            records += [to_record(p, family_id) for p in data.get("data", [])]
            token = data.get("token")
            if not token:
                break
        return SearchResult("semanticscholar", family_id, query, total, records[:max_records])
    except requests.RequestException as exc:
        return SearchResult("semanticscholar", family_id, query, None, [], f"SEARCH_FAILED: {exc}")


def _paper_id(rec: dict) -> str | None:
    if rec.get("s2_id"):
        return rec["s2_id"]
    if rec.get("doi"):
        return f"DOI:{rec['doi']}"
    if rec.get("pmid"):
        return f"PMID:{rec['pmid']}"
    return None


def neighbours(rec: dict, direction: str, limit: int, family_id: str) -> tuple[list[Record], str | None]:
    """direction: 'citations' (papers citing rec, forward) or 'references' (cited by rec, backward)."""
    pid = _paper_id(rec)
    if not pid:
        return [], "NO_IDENTIFIER"
    key = "citingPaper" if direction == "citations" else "citedPaper"
    try:
        r = _get(f"{GRAPH}/paper/{pid}/{direction}", {"fields": FIELDS, "limit": min(limit, 1000)})
        if r.status_code == 404:
            return [], "NOT_FOUND_IN_S2"
        r.raise_for_status()
        papers = [row.get(key) or {} for row in r.json().get("data", []) or []]
        papers = [p for p in papers if p.get("title")]
        papers.sort(key=lambda p: p.get("year") or 0, reverse=True)
        return [to_record(p, family_id) for p in papers[:limit]], None
    except requests.RequestException as exc:
        return [], f"SEARCH_FAILED: {exc}"
