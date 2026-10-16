"""Open-access full text by section, from Europe PMC (PMC articles only).

Returns {} when no legal open full text is available; the paper is then processed at
abstract level and every finding is marked ABSTRACT (A05-KE §2). Never scrape paywalled text.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"


def fetch_sections(pmcid: str | None, timeout: int = 60) -> dict[str, str]:
    if not pmcid:
        return {}
    try:
        r = requests.get(URL.format(pmcid=pmcid), timeout=timeout)
        if r.status_code != 200:
            return {}
        root = ET.fromstring(r.content)
    except (requests.RequestException, ET.ParseError):
        return {}
    sections: dict[str, str] = {}
    abstract = root.find(".//abstract")
    if abstract is not None:
        sections["Abstract"] = " ".join(abstract.itertext())
    body = root.find(".//body")
    if body is not None:
        for sec in body.findall("./sec"):
            title = (sec.findtext("title") or "Untitled").strip()
            sections[title] = " ".join(sec.itertext())
    for i, fig in enumerate(root.findall(".//fig"), 1):
        cap = fig.find("caption")
        if cap is not None:
            sections[f"Figure legend {fig.findtext('label') or i}"] = " ".join(cap.itertext())
    for i, tab in enumerate(root.findall(".//table-wrap"), 1):
        sections[f"Table {tab.findtext('label') or i}"] = " ".join(tab.itertext())
    return {k: " ".join(v.split()) for k, v in sections.items()}
