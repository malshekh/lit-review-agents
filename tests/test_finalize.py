"""End to end through stage_outline's display-item build and stage_finalize, on a synthetic run (no API calls)."""
import json

import pytest

from litreview import orchestrator as orch
from test_display_and_export import CORPUS, FINDINGS, SYNTH


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(orch.notify, "send", lambda *a, **k: False)
    monkeypatch.setattr(orch.references, "crossref_lookup", lambda *a, **k: None)
    r = orch.Run("test")
    r.save_state({"stage": "finalize", "status": "READY", "counters": {}, "current_manuscript": "m04_proof"})
    plan = {"sections": [{"section_id": "S1", "level": 1}, {"section_id": "S2", "level": 2}],
            "display_items": [{"display_id": "F1", "type": "FIGURE_EVIDENCE_MAP", "origin": "ORIGINAL",
                               "source_proposition_ids": ["P1", "P2"]},
                              {"display_id": "T1", "type": "TABLE_EVIDENCE_SUMMARY", "source_proposition_ids": ["P1"],
                               "columns_or_panels": ["Study", "Species", "Key finding"]}]}
    r.save("manuscript_plan.json", plan)
    r.save("synthesis_approved.json", SYNTH)
    r.save("validated_findings.json", FINDINGS)
    r.save("selected_corpus.json", [{**c, "title": "T", "venue": "V"} for c in CORPUS])
    r.save("manuscripts/m04_proof.json", {
        "title": "X lowers Y in rodents", "abstract": "Abstract text.", "keywords": ["X"],
        "sections": [{"section_id": "S1", "heading": "Introduction",
                      "text_markdown": "X matters [@R0002] {{F1}}. ⟦P1⟧"},
                     {"section_id": "S2", "heading": "Rodent studies",
                      "text_markdown": "In rodents X lowered Y [@R0001] {{T1}}. ⟦P1⟧"}],
        "figure_legends": [{"display_id": "F1", "legend": "Evidence map [@R0001]. ⟦P1⟧"}],
        "table_captions": [{"display_id": "T1", "caption": "Rodent studies of X."}]})
    r._build_display_items(plan)
    from litreview.verification_job import VerificationJob
    from litreview.synthesis_registry import offline_tokens
    from test_verification_job import ScriptedVerifier
    pkg=r.load('synthesis_approved.json')
    job=VerificationJob(tmp_path/'verification',r._current(),plan,pkg,r._verification_registry(pkg),
        r.load('display_items.json'),r.cfg['scientific_verification'],ScriptedVerifier(),offline_tokens,{'fixture':True})
    r.save('rv_final.json',job.run())
    return r


def test_finalize_writes_docx_with_tables_and_numbered_citations(run):
    docx = pytest.importorskip("docx")
    assert run.stage_finalize(run.state()) == "done"
    final = run.dir / "final"
    md = (final / "manuscript.md").read_text(encoding="utf-8")
    # text citations numbered first (R0002 -> 1, R0001 -> 2); R0003 appears only in the table -> 3
    assert "X matters [1] Fig. 1." in md and "### Rodent studies" in md and "⟦" not in md
    assert "| Smith et al. (2021) [2] | mouse |" in md and "[3]" in md
    assert "![Figure 1](display_items/F1.png)" in md and (final / "display_items" / "F1.png").exists()
    d = docx.Document(str(final / "manuscript.docx"))
    assert len(d.tables) == 1 and d.tables[0].cell(3, 0).text == "R0003 [3]"
    assert len(d.inline_shapes) == 1
    assert json.loads((final / "compliance.json").read_text(encoding="utf-8"))["references"] == 3


def test_table_only_citations_count_as_cited(run):
    rep = run._deterministic_report(run._current())
    assert "R0003" not in rep["selected_papers_not_cited"]


@pytest.mark.parametrize('change',['text','table','synthesis','evidence','missing_report','blocking'])
def test_release_requires_current_verified_version(run,change):
    if change=='text':
        m=run._current();m['abstract']='Changed assertion';run.save('manuscripts/m04_proof.json',m)
    elif change=='table':
        tables=run.load('display_items.json');tables[-1]['caption']='Changed scientific caption';run.save('display_items.json',tables)
    elif change=='synthesis':
        pkg=run.load('synthesis_approved.json');pkg['propositions'][0]['assertion']='Changed conclusion';run.save('synthesis_approved.json',pkg)
    elif change=='evidence':
        fs=run.load('validated_findings.json');fs[0]['span']='Changed source';run.save('validated_findings.json',fs)
    elif change=='missing_report':run.save('rv_final.json',{})
    else:
        rv=run.load('rv_final.json');rv['findings']=[{'severity':'BLOCKING'}];run.save('rv_final.json',rv)
    with pytest.raises(orch.Pause,match='current complete A10'):
        run.stage_finalize(run.state())
