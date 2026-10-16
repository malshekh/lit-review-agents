"""Europe PMC REST API. Docs: https://europepmc.org/RestfulWebService"""
from __future__ import annotations

import requests

from .base import Record, SearchResult

URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def search(query: str, family_id: str, max_records: int = 200) -> SearchResult:
    records: list[Record] = []
    cursor, hit_count = "*", None
    try:
        while len(records) < max_records:
            r = requests.get(URL, params={"query": query, "format": "json", "resultType": "core",
                                          "pageSize": min(100, max_records - len(records)),
                                          "cursorMark": cursor}, timeout=30)
            r.raise_for_status()
            data = r.json()
            hit_count = data.get("hitCount", hit_count)
            items = data.get("resultList", {}).get("result", [])
            if not items:
                break
            for it in items:
                records.append(Record(
                    source="europepmc", title=it.get("title", ""), abstract=it.get("abstractText", ""),
                    authors=[a.get("fullName", "") for a in (it.get("authorList") or {}).get("author", [])],
                    year=int(it["pubYear"]) if it.get("pubYear", "").isdigit() else None,
                    venue=(it.get("journalInfo") or {}).get("journal", {}).get("title", ""),
                    publication_type=(it.get("pubTypeList") or {}).get("pubType", []),
                    doi=it.get("doi"), pmid=it.get("pmid"), pmcid=it.get("pmcid"),
                    is_preprint=it.get("source") == "PPR", open_access=it.get("isOpenAccess") == "Y",
                    query_family_id=family_id))
            nxt = data.get("nextCursorMark")
            if not nxt or nxt == cursor:
                break
            cursor = nxt
    except requests.RequestException as exc:
        return SearchResult("europepmc", family_id, query, hit_count, records, f"SEARCH_FAILED: {exc}")
    return SearchResult("europepmc", family_id, query, hit_count, records[:max_records])
