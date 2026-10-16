"""ClinicalTrials.gov API v2. Docs: https://clinicaltrials.gov/data-api/api

Registered trials — including terminated, withdrawn and unpublished ones — are a key source of
contrary evidence and of publication-bias signals. Query syntax (A03-LM):
  plain text                         -> query.term
  cond:X && intr:Y && term:Z         -> query.cond / query.intr / query.term
"""
from __future__ import annotations

import requests

from .base import Record, SearchResult

URL = "https://clinicaltrials.gov/api/v2/studies"
_FIELD = {"cond": "query.cond", "intr": "query.intr", "term": "query.term", "titles": "query.titles",
          "outc": "query.outc", "spons": "query.spons"}


def _params(query: str) -> dict:
    parts = [p.strip() for p in query.split("&&")]
    params = {}
    for p in parts:
        k, sep, v = p.partition(":")
        if sep and k.strip().lower() in _FIELD:
            params[_FIELD[k.strip().lower()]] = v.strip()
        else:
            params["query.term"] = (params.get("query.term", "") + " " + p).strip()
    return params


def to_record(study: dict, family_id: str) -> Record:
    ps = study.get("protocolSection", {})
    ident, status = ps.get("identificationModule", {}), ps.get("statusModule", {})
    desc, design = ps.get("descriptionModule", {}), ps.get("designModule", {})
    start = (status.get("startDateStruct") or {}).get("date", "")
    refs = (ps.get("referencesModule") or {}).get("references", [])
    result_pmid = next((x.get("pmid") for x in refs if x.get("type") == "RESULT" and x.get("pmid")), None)
    return Record(
        source="clinicaltrials", title=ident.get("officialTitle") or ident.get("briefTitle", ""),
        abstract=desc.get("briefSummary", ""), authors=[], year=int(start[:4]) if start[:4].isdigit() else None,
        venue="ClinicalTrials.gov",
        publication_type=["Clinical trial registration", status.get("overallStatus", ""),
                          *(design.get("phases") or []),
                          "HAS_RESULTS" if study.get("hasResults") else "NO_POSTED_RESULTS"],
        pmid=result_pmid, nct_id=ident.get("nctId"), query_family_id=family_id)


def search(query: str, family_id: str, max_records: int = 200) -> SearchResult:
    records: list[Record] = []
    token, total = None, None
    try:
        while len(records) < max_records:
            params = {**_params(query), "pageSize": min(100, max_records - len(records)), "countTotal": "true",
                      "format": "json"}
            if token:
                params["pageToken"] = token
            r = requests.get(URL, params=params, timeout=30)
            if r.status_code == 400:
                return SearchResult("clinicaltrials", family_id, query, None, [], f"QUERY_INVALID: {r.text[:200]}")
            r.raise_for_status()
            data = r.json()
            total = data.get("totalCount", total)
            records += [to_record(s, family_id) for s in data.get("studies", [])]
            token = data.get("nextPageToken")
            if not token:
                break
    except requests.RequestException as exc:
        return SearchResult("clinicaltrials", family_id, query, total, records, f"SEARCH_FAILED: {exc}")
    return SearchResult("clinicaltrials", family_id, query, total, records[:max_records])
