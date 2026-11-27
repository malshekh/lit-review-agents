"""Reviewed table transcription in provider request material and local extraction acceptance."""
import json
import xml.etree.ElementTree as ET

import jsonschema
import pytest

from litreview import config, extraction_mode, orchestrator
from litreview.batch_stage import BatchStage
from litreview.paths import SCHEMAS_DIR
from litreview.tools import fulltext, span_check
from test_a05_ordinary_json import canonical


def test_table_signal_and_location_survive_wire_and_validation(tmp_path, monkeypatch):
    contract = json.loads((SCHEMAS_DIR / "source_material_contracts/42409644.json").read_bytes())
    table = contract["reviewed_image_tables"]["tbl1"]
    tree = ET.fromstring("""<article><front><article-meta><article-id pub-id-type="pmid">42409644</article-id>
      <article-id pub-id-type="pmcid">PMC13397890</article-id><article-id pub-id-type="doi">10.1021/acs.nanolett.6c01777</article-id>
      </article-meta></front><body><table-wrap id="tbl1"><label>1</label><graphic xmlns:xlink="http://www.w3.org/1999/xlink"
      xlink:href="nl6c01777_0010.jpg"/><table-wrap-foot><fn><p/></fn></table-wrap-foot></table-wrap></body></article>""")
    tree.find(".//fn/p").text = table["footnote"]
    sections = fulltext._sections(tree, strict=True)
    slot = "Table 1 | Daunorubicin | Concentration-based PCA"
    span = sections[slot]
    assert span == "Daunorubicin | Concentration-based PCA | (TAT)₆-(10,2) | red | wavelength shift"
    monkeypatch.setattr(orchestrator, "RUNS_DIR", tmp_path)
    run = orchestrator.Run("offline")
    step = "A05-KE_R0078"
    payload = {"content_level": "FULL_TEXT", "record": {"record_id": "R0078", "content": sections}}
    stage = BatchStage(run, "A05-KE", [(step, payload)], lambda *_: None, lambda _: frozenset())
    model = config.agent_model("A05-KE")
    requests, _ = stage._requests(model, {"fixture": step})
    wire = json.dumps(requests[0], ensure_ascii=False)
    assert span in wire and table["footnote"] in wire
    extraction = canonical(span, "wavelength shift", "NOT_APPLICABLE")
    extraction["sections_inspected"] = [slot, "Table 1"]
    extraction["entities"][0]["mention"] = "daunorubicin"
    extraction["entities"][1]["mention"] = "(TAT)₆-(10,2)"
    extraction["contexts"][0]["fields"].pop("matrix")
    finding = extraction["findings"][0]
    finding.update(quantities=[], span_location={"section": slot})
    accepted = extraction_mode.accept(json.dumps(extraction), payload)
    run.save("extractions/R0078.json", accepted)
    run.save("fulltext/R0078.json", sections)
    monkeypatch.setattr(run, "_extraction_vendor", lambda *_: "anthropic")
    captured = []
    monkeypatch.setattr(run, "run_many", lambda agent, items, *a, **kw: captured.extend(items))
    run._validate_papers(["R0078"])
    validator_input = captured[0][1]
    assert validator_input["paper_text"][slot] == span
    assert span_check.passed(validator_input["gate1_results"][0])
    finding["span"] = span.replace("wavelength shift", "intensity change")
    with pytest.raises(jsonschema.ValidationError, match="span/location"):
        extraction_mode.accept(json.dumps(extraction), payload)
    tree.find(".//fn/p").text = "Reversed legend"
    with pytest.raises(fulltext.FullTextUnavailable, match="legend mismatch"):
        fulltext._sections(tree, strict=True)
