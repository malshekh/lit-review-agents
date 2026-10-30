import json

import pytest

from litreview.tools import display_items as di
from litreview.tools import manuscript_export as mx

SYNTH = {"propositions": [
    {"proposition_id": "P1", "assertion": "X lowers Y in rodents", "supporting_finding_ids": ["R0001:F1", "R0002:F1"],
     "conflicting_finding_ids": ["R0003:F1"], "ceiling": {"disposition": "SUPPORTED_WITH_CONSTRAINTS"}},
    {"proposition_id": "P2", "assertion": "X binds Z", "supporting_finding_ids": ["R0002:F2"]}]}


def _finding(fid, system, species, polarity="POSITIVE"):
    return {"finding_id": fid, "record_id": fid.split(":")[0], "subject": "E1", "predicate": "DECREASES",
            "object": "E2", "polarity": polarity, "span": "X reduced Y by -30% (p = 0.01; n = 8).", "disposition": "SUPPORTED",
            "constraints": ["single dose"], "quantities": [{"measured_property": "Y", "raw_value": "-30",
                                                            "raw_unit": "%", "p_value": "0.01", "n": "8"}],
            "context": {"evidence_system": system, "species": species, "dose_or_concentration": "NOT_REPORTED"},
            "entities": {"E1": {"mention": "compound X"}, "E2": {"mention": "Y", "approved_symbol": "YGENE", "normalization_state": "RESOLVED"}}}


FINDINGS = [_finding("R0001:F1", "IN_VIVO", "mouse"), _finding("R0002:F1", "IN_VIVO", "rat"),
            _finding("R0002:F2", "IN_VITRO", "NOT_REPORTED"), _finding("R0003:F1", "IN_VIVO", "mouse", "NULL")]
CORPUS = [{"record_id": "R0001", "authors": ["Ana Smith", "B Jones"], "year": 2021},
          {"record_id": "R0002", "authors": ["Chen Li"], "year": 2019},
          {"record_id": "R0003", "authors": [], "year": None}]


def test_table_rows_come_only_from_validated_findings():
    item = {"display_id": "T1", "type": "TABLE_EVIDENCE_SUMMARY", "source_proposition_ids": ["P1"],
            "columns_or_panels": ["Study", "Species", "Dose", "Key finding", "Effect size", "Supports or conflicts",
                                  "Reviewer notes"]}
    t = di.build_table(item, SYNTH, FINDINGS, CORPUS)
    assert t["status"] == "BUILT" and len(t["rows"]) == 3
    assert t["rows"][0][:4] == ["Smith et al. (2021) [@R0001]", "mouse", "NR", "compound X decreases YGENE"]
    assert t["rows"][0][4] == "Y -30 % (P = 0.01; n = 8)"
    assert [r[5] for r in t["rows"]] == ["supporting", "supporting", "conflicting"]
    assert t["rows"][2][0] == "R0003 [@R0003]"            # no authors/year: falls back to the record ID
    assert t["unmapped_columns"] == ["Reviewer notes"] and t["rows"][0][6] == ""


def test_unknown_source_ids_are_reported_not_filled():
    t = di.build_table({"display_id": "T2", "source_proposition_ids": ["P9", "R0001:F1"]}, SYNTH, FINDINGS, CORPUS)
    assert len(t["rows"]) == 1 and any("P9" in w for w in t["warnings"])


def test_evidence_map_counts_and_png(tmp_path):
    rows, _ = di.evidence_rows({"source_proposition_ids": ["P1", "P2"]}, SYNTH, FINDINGS, CORPUS)
    props, systems, counts = di.evidence_map_data(rows)
    assert props == ["P1", "P2"] and systems == ["In vitro", "In vivo"]
    assert counts[("P1", "In vivo")] == [2, 1] and counts[("P2", "In vitro")] == [1, 0]
    pytest.importorskip("matplotlib")
    item = {"display_id": "F1", "type": "FIGURE_EVIDENCE_MAP", "source_proposition_ids": ["P1", "P2"],
            "origin": "ORIGINAL"}
    res = di.build_figure(item, SYNTH, FINDINGS, CORPUS, tmp_path)
    assert res["status"] == "BUILT" and (tmp_path / "F1.png").stat().st_size > 1000


def test_schematic_gets_brief_never_a_drawing(tmp_path):
    item = {"display_id": "F2", "type": "FIGURE_SCHEMATIC", "source_proposition_ids": ["P1"], "origin": "ADAPTED_FROM",
            "adapted_from_record_id": "R0002", "must_distinguish": "step 2 unresolved"}
    res = di.build_figure(item, SYNTH, FINDINGS, CORPUS, tmp_path)
    brief = (tmp_path / "F2_brief.md").read_text(encoding="utf-8")
    assert res["status"] == "BRIEF_ONLY" and res["image"] is None
    assert "step 2 unresolved" in brief and "copyright permission" in brief and "SUPPORTED_WITH_CONSTRAINTS" in brief


def test_build_all_writes_json_and_csv(tmp_path):
    plan = {"display_items": [{"display_id": "T1", "type": "TABLE_COMPARISON", "source_proposition_ids": ["P2"]},
                              {"display_id": "bad"}]}
    built = di.build_all(plan, SYNTH, FINDINGS, CORPUS, tmp_path)
    assert [b["status"] for b in built] == ["BUILT", "EMPTY"]
    assert json.loads((tmp_path / "T1.json").read_text(encoding="utf-8"))["rows"]
    assert (tmp_path / "T1.csv").read_text(encoding="utf-8-sig").startswith("Study,System,Finding,Evidence")


DOC = {"title": "X and Y", "abstract": "An abstract.", "keywords": ["x", "y"],
       "sections": [{"heading": "Introduction", "level": 1,
                     "text": "First paragraph with **bold** and *italic* [1].\n\n### A sub-heading\n\n- one\n- two"}],
       "references": ["1. Smith, A. Title. *J. Test* **3**, 1 (2021)."],
       "back_matter": [("Competing interests", "[TO BE WRITTEN BY THE AUTHORS]")],
       "figures": [{"display_id": "F1", "legend": "Evidence map.", "image": None, "brief": "F1_brief.md"}],
       "tables": [{"display_id": "T1", "caption": "Studies.", "columns": ["Study", "Finding"],
                   "rows": [["Smith (2021) [1]", "a | b"]], "notes": ["NR, not reported."]}]}


def test_markdown_render():
    md = mx.render_markdown(DOC)
    assert md.index("## References") < md.index("## Figure legends") < md.index("## Tables")
    assert "| Smith (2021) [1] | a \\| b |" in md and "see display_items/F1_brief.md" in md


def test_docx_render(tmp_path):
    docx = pytest.importorskip("docx")
    path = mx.render_docx(DOC, tmp_path / "m.docx")
    d = docx.Document(str(path))
    text = [p.text for p in d.paragraphs]
    assert text[0] == "X and Y" and "A sub-heading" in text and "one" in text
    bold = [r.text for p in d.paragraphs for r in p.runs if r.bold]
    assert "bold" in bold and "Keywords:" in bold
    assert len(d.tables) == 1 and d.tables[0].cell(1, 1).text == "a | b"
