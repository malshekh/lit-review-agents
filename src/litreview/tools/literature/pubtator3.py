"""PubTator3 (NCBI) entity-normalized search. Docs: https://www.ncbi.nlm.nih.gov/research/pubtator3/api

Search returns PMIDs with titles; abstracts are fetched from PubMed so A04-CQ can screen them.
"""
from __future__ import annotations

import time

import requests

from . import pubmed
from .base import SearchResult

URL = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/search/"


def search(query: str, family_id: str, max_records: int = 200) -> SearchResult:
    pmids: list[str] = []
    total = None
    try:
        page = 1
        while len(pmids) < max_records:
            r = requests.get(URL, params={"text": query, "page": page}, timeout=30)
            if r.status_code == 400:
                return SearchResult("pubtator3", family_id, query, None, [], f"QUERY_INVALID: {r.text[:200]}")
            r.raise_for_status()
            data = r.json()
            total = data.get("count", total)
            batch = [str(x["pmid"]) for x in data.get("results", []) if x.get("pmid")]
            if not batch:
                break
            pmids += batch
            if page >= int(data.get("total_pages", page)):
                break
            page += 1
            time.sleep(0.34)   # NCBI: max ~3 requests/second
        records = pubmed.fetch_by_pmids(pmids[:max_records], family_id)
        for rec in records:
            rec.source = "pubtator3"
    except (requests.RequestException, ValueError) as exc:
        return SearchResult("pubtator3", family_id, query, total, [], f"SEARCH_FAILED: {exc}")
    return SearchResult("pubtator3", family_id, query, total, records)
