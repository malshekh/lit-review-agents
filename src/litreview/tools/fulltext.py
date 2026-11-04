"""Open-access full text by section, from Europe PMC (PMC articles only).

Returns {} when no legal open full text is available; the paper is then processed at
abstract level and every finding is marked ABSTRACT (A05-KE Â§2). Never scrape paywalled text.
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
    return _sections(root)


def _sections(root, strict=False) -> dict[str, str]:
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
    sections = {k: " ".join(v.split()) for k, v in sections.items()}
    if strict:
        sections.update(_structured_material(root))
    return sections


class FullTextUnavailable(ValueError):
    """Required full text is unavailable, incomplete, mismatched or not verifiable."""


def _digest(sections):
    import hashlib, json
    return hashlib.sha256(json.dumps(sections, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def verify_cached_source(record, sections, source):
    import hashlib, base64
    if not isinstance(source, dict) or not isinstance(sections, dict):
        raise FullTextUnavailable("Full-text cache/provenance must be objects")
    try:
        raw = base64.b64decode((source or {}).get("xml_base64", ""), validate=True)
    except (ValueError, TypeError) as exc:
        raise FullTextUnavailable("Cached source encoding invalid") from exc
    if (not isinstance(source, dict) or source.get("verified") is not True
            or source.get("pmid") != str(record.get("pmid"))
            or source.get("pmcid") != record.get("pmcid")
            or source.get("url") != URL.format(pmcid=record.get("pmcid"))
            or source.get("sections_sha256") != _digest(sections)
            or not isinstance(source.get("xml_base64"), str)
            or source.get("xml_sha256") != hashlib.sha256(raw).hexdigest()
            or not source.get("body_sections")
            or any(not sections.get(k, "").strip() for k in source["body_sections"])):
        raise FullTextUnavailable("Missing or mismatched full-text identity/body/hash provenance")
    try:
        tree = ET.fromstring(base64.b64decode(source["xml_base64"], validate=True))
    except (ValueError, ET.ParseError) as exc:
        raise FullTextUnavailable("Cached source XML invalid") from exc
    ids = {x.get("pub-id-type"): (x.text or "").strip() for x in tree.findall("./front/article-meta/article-id")}
    if (ids.get("pmid") != str(record.get("pmid"))
            or _pmc_identity(ids) != record.get("pmcid", "").removeprefix("PMC")
            or (record.get("doi") and ids.get("doi", "").lower() != record["doi"].lower())):
        raise FullTextUnavailable("Cached source XML identity mismatch")
    body = tree.find("./body")
    names = [(sec.findtext("title") or "Untitled").strip() for sec in body.findall("./sec")] if body is not None else []
    expected = _sections(tree, strict=True)
    expected.setdefault("Abstract", "")
    if (not names or len(names) != len(set(names)) or names != source["body_sections"]
            or _digest(expected) != _digest(sections)):
        raise FullTextUnavailable("Cached source body/section mapping mismatch")


def fetch_verified_sections(record, timeout=60):
    """Materialize the required article only after verifying XML identity and body.

    This verifies source identity/content presence, not scientific completeness or quality.
    Raw XML is retained in the returned source envelope for offline identity reinspection.
    """
    import hashlib, datetime, base64
    pmid, pmcid = str(record.get("pmid") or ""), record.get("pmcid")
    if not pmid or not pmcid:
        raise FullTextUnavailable("Required PMID/PMCID missing")
    url = URL.format(pmcid=pmcid)
    try:
        response = requests.get(url, timeout=timeout)
        if response.status_code != 200:
            raise FullTextUnavailable(f"Full-text HTTP status {response.status_code}")
        raw = response.content
        tree = ET.fromstring(raw)
    except (requests.RequestException, ET.ParseError) as exc:
        raise FullTextUnavailable("Full-text retrieval/XML parse failed") from exc
    ids = {x.get("pub-id-type"): (x.text or "").strip()
           for x in tree.findall("./front/article-meta/article-id")}
    if (ids.get("pmid") != pmid or _pmc_identity(ids) != pmcid.removeprefix("PMC")
            or (record.get("doi") and ids.get("doi", "").lower() != record["doi"].lower())):
        raise FullTextUnavailable("Full-text XML PMID/PMCID/DOI identity mismatch")
    body = tree.find("./body")
    if body is None or not " ".join(body.itertext()).strip():
        raise FullTextUnavailable("Full-text body missing")
    sections = _sections(tree, strict=True)
    names = [(sec.findtext("title") or "Untitled").strip() for sec in body.findall("./sec")]
    if not names or any(not sections.get(n, "").strip() for n in names):
        raise FullTextUnavailable("Full-text body sections missing")
    # Keep the established section-count contract while identity/body verification is explicit.
    sections.setdefault("Abstract", "")
    source = {"verified": True, "pmid": pmid, "pmcid": pmcid, "doi": ids.get("doi"), "url": url,
              "retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "xml_sha256": hashlib.sha256(raw).hexdigest(), "sections_sha256": _digest(sections),
              "body_sections": names, "xml_base64": base64.b64encode(raw).decode("ascii")}
    verify_cached_source(record, sections, source)
    return sections, source


def _pmc_identity(ids):
    values = {ids[k].removeprefix("PMC") for k in ("pmc", "pmcid", "pmcaid", "pmcaiid") if ids.get(k)}
    return next(iter(values)) if len(values) == 1 else ""


def _text(node):
    return " ".join(" ".join(node.itertext()).split()) if node is not None else ""


def _grid(table):
    """Keep cell boundaries, headings, row labels, spans and exact textual numbers."""
    rows = []
    raw = []
    pending = {}
    header_rows = []
    for ri, tr in enumerate(table.findall(".//tr")):
        row, cells, col = [], [], 0
        def advance():
            nonlocal col
            while (ri, col) in pending:
                row.append(pending[(ri, col)]); col += 1
        advance()
        for cell in list(tr):
            if cell.tag not in ("td", "th"): continue
            advance()
            text = _text(cell)
            try: span, height = int(cell.get("colspan", "1")), int(cell.get("rowspan", "1"))
            except ValueError as exc: raise FullTextUnavailable("Table cell span invalid") from exc
            if not (1 <= span <= 100 and 1 <= height <= 100):
                raise FullTextUnavailable("Table span unsupported")
            cells.append({"text": text, "column": col, "colspan": span, "rowspan": height, "heading": cell.tag == "th"})
            for offset in range(span):
                row.append(text)
                for delta in range(1, height):pending[(ri+delta, col+offset)] = text
            col += span
        advance()
        if cells and all(c["heading"] for c in cells): header_rows.append(ri)
        rows.append(row);raw.append(cells)
    if not rows or not any(any(c for c in row) for row in rows) or not header_rows:
        raise FullTextUnavailable("Required table is not machine-readable with headings and cells")
    return {"header_row_indices": header_rows, "rows": rows, "cells": raw}


def _structured_material(tree):
    import json, re
    from ..paths import SCHEMAS_DIR
    ids = {x.get("pub-id-type"): (x.text or "").strip() for x in tree.findall("./front/article-meta/article-id")}
    path = SCHEMAS_DIR / "source_material_contracts" / f"{ids.get('pmid')}.json"
    contract = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    body = tree.find("./body")
    body_sections = body.findall("./sec") if body is not None else []
    for group in contract.get("body_groups", []):
        matches = [n for n in body_sections if group in (n.findtext("title") or "").lower()]
        if not matches or not any(_text(p) for n in matches for p in n.findall(".//p")):
            raise FullTextUnavailable(f"Required substantive body section absent: {group}")
    tabs = tree.findall(".//table-wrap")
    figs = tree.findall(".//fig")
    table_ids = {n.get("id") for n in tabs}
    figure_ids = {n.get("id") for n in figs}
    if not set(contract.get("table_ids", [])) <= table_ids:
        raise FullTextUnavailable("Required table missing from extraction input")
    if not set(contract.get("figure_ids", [])) <= figure_ids:
        raise FullTextUnavailable("Required figure/legend missing from extraction input")
    for node in tree.findall(".//xref"):
        target = table_ids if node.get("ref-type") == "table" else figure_ids if node.get("ref-type") == "fig" else None
        if target is not None and not set((node.get("rid") or "").split()) <= target:
            raise FullTextUnavailable("Referenced table or figure absent")
    content, table_report, figure_report = {}, [], []
    for index, node in enumerate(tabs, 1):
        table = node.find(".//table")
        if table is None: raise FullTextUnavailable("Image-only or missing table requires source remediation")
        info = {"id": node.get("id"), "label": node.findtext("label") or str(index),
                "caption": _text(node.find("caption")), "footnotes": _text(node.find("table-wrap-foot")), **_grid(table)}
        content[f"Table {info['label']}"] = json.dumps(info, ensure_ascii=False)
        content[f"Verbatim table {info['label']}"] = _text(node)
        table_report.append({"id": info["id"], "rows": len(info["rows"]), "machine_readable": True})
    for index, node in enumerate(figs, 1):
        caption = _text(node.find("caption"))
        if not caption: raise FullTextUnavailable("Figure legend missing from extraction input")
        info = {"id": node.get("id"), "label": node.findtext("label") or str(index), "legend": caption,
                "graphic_hrefs": [v for g in node.findall(".//graphic") for k,v in g.attrib.items() if k.endswith("href")],
                "image_inspected": False, "figure_only_information": "NOT_EXTRACTED"}
        content[f"Figure legend {info['label']}"] = json.dumps(info, ensure_ascii=False)
        content[f"Verbatim figure legend {info['label']}"] = caption
        figure_report.append({"id": info["id"], "legend_available": True, "image_inspected": False})
    supplements = [{"id": node.get("id"), "description": _text(node),
                   "hrefs": [v for n in node.iter() for k,v in n.attrib.items() if k.endswith("href")],
                   "status": "NOT_RETRIEVED_NOT_INSPECTED"} for node in tree.findall(".//supplementary-material")]
    content["Source access and completeness"] = json.dumps({"tables": table_report, "figures": figure_report,
        "supplementary_material": supplements, "figure_only_information": "Images not inspected; do not infer image-only measurements",
        "supplements_assessed": False}, ensure_ascii=False)
    return content
