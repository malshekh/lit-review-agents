"""OpenAlex works search. Docs: https://docs.openalex.org/"""
from __future__ import annotations

import os

import requests

from .base import Record, SearchResult

URL = "https://api.openalex.org/works"


def _abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = sorted((p, w) for w, ps in inv.items() for p in ps)
    return " ".join(w for _, w in pos)


def search(query: str, family_id: str, max_records: int = 200) -> SearchResult:
    """`query` is an OpenAlex filter string, e.g. 'title_and_abstract.search:biosensor,publication_year:>2015'."""
    records: list[Record] = []
    cursor, count = "*", None
    mailto = os.environ.get("OPENALEX_EMAIL")
    api_key = os.environ.get("OPENALEX_API_KEY")
    try:
        while cursor and len(records) < max_records:
            params = {"filter": query, "per-page": 100, "cursor": cursor}
            if mailto:
                params["mailto"] = mailto
            if api_key:
                params["api_key"] = api_key
            r = requests.get(URL, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            count = data.get("meta", {}).get("count", count)
            for w in data.get("results", []):
                ids = w.get("ids") or {}
                records.append(Record(
                    source="openalex", title=w.get("title") or "",
                    abstract=_abstract(w.get("abstract_inverted_index")),
                    authors=[a["author"]["display_name"] for a in w.get("authorships", []) if a.get("author")],
                    year=w.get("publication_year"),
                    venue=((w.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
                    publication_type=[w.get("type", "")],
                    doi=(w.get("doi") or "").replace("https://doi.org/", "") or None,
                    pmid=(ids.get("pmid") or "").rsplit("/", 1)[-1] or None,
                    open_access=(w.get("open_access") or {}).get("is_oa"),
                    query_family_id=family_id))
            cursor = data.get("meta", {}).get("next_cursor")
    except requests.RequestException as exc:
        return SearchResult("openalex", family_id, query, count, records, f"SEARCH_FAILED: {exc}")
    return SearchResult("openalex", family_id, query, count, records[:max_records])
