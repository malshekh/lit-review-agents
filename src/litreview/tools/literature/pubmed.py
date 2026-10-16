"""PubMed via NCBI E-utilities. Docs: https://www.ncbi.nlm.nih.gov/books/NBK25501/"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET

import requests

from .base import Record, SearchResult

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"


def _params(extra: dict) -> dict:
    key = os.environ.get("NCBI_API_KEY")
    return {**extra, **({"api_key": key} if key else {})}


def search(query: str, family_id: str, max_records: int = 200) -> SearchResult:
    try:
        r = requests.get(EUTILS + "esearch.fcgi", params=_params(
            {"db": "pubmed", "term": query, "retmax": max_records, "retmode": "json"}), timeout=30)
        r.raise_for_status()
        res = r.json()["esearchresult"]
        if "ERROR" in res:
            return SearchResult("pubmed", family_id, query, None, [], f"QUERY_INVALID: {res['ERROR']}")
        ids, count = res.get("idlist", []), int(res.get("count", 0))
        records = _fetch(ids, family_id) if ids else []
    except (requests.RequestException, KeyError, ET.ParseError) as exc:
        return SearchResult("pubmed", family_id, query, None, [], f"SEARCH_FAILED: {exc}")
    return SearchResult("pubmed", family_id, query, count, records)


def _fetch(ids: list[str], family_id: str) -> list[Record]:
    records: list[Record] = []
    for i in range(0, len(ids), 200):
        r = requests.post(EUTILS + "efetch.fcgi", data=_params(
            {"db": "pubmed", "id": ",".join(ids[i:i + 200]), "retmode": "xml"}), timeout=60)
        r.raise_for_status()
        for art in ET.fromstring(r.content).findall(".//PubmedArticle"):
            a = art.find(".//Article")
            if a is None:
                continue
            abstract = " ".join("".join(t.itertext()) for t in a.findall(".//AbstractText"))
            authors = [f"{x.findtext('LastName', '')} {x.findtext('Initials', '')}".strip()
                       for x in a.findall(".//Author")]
            year = art.findtext(".//PubDate/Year")
            doi = next((e.text for e in art.findall(".//ArticleId") if e.get("IdType") == "doi"), None)
            records.append(Record(
                source="pubmed", title="".join(a.find("ArticleTitle").itertext()) if a.find("ArticleTitle") is not None else "",
                abstract=abstract, authors=authors, year=int(year) if year and year.isdigit() else None,
                venue=a.findtext(".//Journal/ISOAbbreviation", ""),
                publication_type=[p.text for p in a.findall(".//PublicationType") if p.text],
                doi=doi, pmid=art.findtext(".//PMID"), query_family_id=family_id))
    return records
