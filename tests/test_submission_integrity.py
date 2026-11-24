"""P0 submission integrity: citations, retractions, Crossref, declarations, the table and journal limits."""
import json

import pytest

from litreview import orchestrator as orch
from litreview.tools import compliance, references, submission
from test_finalize import run  # noqa: F401 — the synthetic run at the finalize stage


# --------------------------------------------------------------------------------------- citations (item 10)
def test_unknown_citation_id_raises_instead_of_printing_an_empty_bracket():
    numbers = {"R0001": 1, "R0002": 2}
    assert references.render_citations("A [@R0002; @R0001] b [@R0001].", numbers) == "A [1,2] b [1]."
    with pytest.raises(references.UnknownCitation, match="R0099"):
        references.render_citations("Claim [@R0099].", numbers)
    with pytest.raises(references.UnknownCitation, match="R0099"):   # a partly known citation is not trimmed
        references.render_citations("Claim [@R0001; @R0099].", numbers)
    with pytest.raises(references.UnknownCitation, match="no record"):
        references.render_citations("Claim [@ ].", numbers)


def test_export_stops_on_a_citation_outside_the_selected_corpus(run):  # noqa: F811
    m = run._current()
    m["sections"][0]["text_markdown"] = "X matters [@R0777] {{F1}}. ⟦P1⟧"
    run.save("manuscripts/m04_proof.json", m)
    run._verification_current = lambda report, manuscript: True   # isolate the export from A10 currency
    with pytest.raises(orch.Pause, match="R0777"):
        run.stage_finalize(run.state())
    assert not (run.dir / "final" / "manuscript.md").exists()


# ------------------------------------------------------------------------------- Crossref and retractions
class Resp:
    def __init__(self, status, payload=None):
        self.status_code, self._payload = status, payload

    def json(self):
        return self._payload


@pytest.fixture
def real_lookup(monkeypatch):
    """The real crossref_lookup (conftest replaces it with an offline stub) over a scripted requests.get."""
    import importlib
    import requests
    real = importlib.reload(references).crossref_lookup
    calls = []

    def install(script):
        replies = iter(script)

        def get(url, params=None, timeout=None):
            calls.append(url)
            r = next(replies)
            if isinstance(r, Exception):
                raise r
            return r
        monkeypatch.setattr(requests, "get", get)
        return calls
    return real, install


def test_crossref_retries_then_caches_and_distinguishes_outage_from_not_found(tmp_path, real_lookup):
    import requests
    lookup, install = real_lookup
    calls = install([requests.ConnectionError("down"), Resp(503), Resp(200, {"message": {"title": ["T"]}})])
    assert lookup("10.1/x", cache_dir=tmp_path, sleep=lambda s: None) == {"title": ["T"]}
    assert len(calls) == 3
    assert lookup("10.1/x", cache_dir=tmp_path, sleep=lambda s: None) == {"title": ["T"]} and len(calls) == 3  # cached
    install([Resp(404)])
    assert lookup("10.1/none", cache_dir=tmp_path) is None            # no such DOI: a cached negative answer
    install([Resp(500)] * 4)
    with pytest.raises(references.LookupFailed, match="after 4 attempts"):
        lookup("10.1/down", cache_dir=tmp_path, sleep=lambda s: None)  # an outage is never read as "no metadata"
    assert not (tmp_path / "x").exists()


RECORD = {"record_id": "R0001", "doi": "10.1/x", "title": "Disulfiram and copper in glioblastoma",
          "authors": ["Smith A", "Jones B", "Li C", "Khan D", "Ng E", "Roy F", "Sato G"], "venue": "J Test", "year": 2021}
META = {"title": ["Disulfiram and copper in glioblastoma."], "author": [{"family": "Smith", "given": "Ana"}],
        "container-title": ["Journal of Tests"], "volume": "5", "page": "1-9", "issued": {"date-parts": [[2021]]}}


def test_reference_uses_crossref_only_when_the_title_matches():
    text, problems, meta = references.build_reference(RECORD, lookup=lambda *a, **k: META)
    assert text == "Smith, A. Disulfiram and copper in glioblastoma. *Journal of Tests* **5**, 1-9 (2021)." and not problems
    wrong = {**META, "title": ["A randomized trial of statins in heart failure"]}
    text, problems, meta = references.build_reference(RECORD, lookup=lambda *a, **k: wrong)
    assert meta is None and "different title" in problems[0]
    assert "statins" not in text and text.startswith("Smith A et al. Disulfiram")   # never the other paper's metadata


def test_fallback_reference_keeps_every_author_and_never_prints_a_marker():
    five = {**RECORD, "doi": "", "authors": RECORD["authors"][:5]}
    text, problems, _ = references.build_reference(five)
    assert text == "Smith A, Jones B, Li C, Khan D & Ng E Disulfiram and copper in glioblastoma. *J Test* (2021)."
    assert "CHECK FORMAT" not in text and "et al" not in text and problems == [
        "no DOI: formatted from the retrieved record; check authors, journal, volume and pages"]
    text, _, _ = references.build_reference({**RECORD, "doi": ""})
    assert text.startswith("Smith A et al. ")                          # six or more: first author et al.


def test_outage_is_reported_as_a_problem_not_swallowed():
    def down(*a, **k):
        raise references.LookupFailed("Crossref could not be reached")
    text, problems, meta = references.build_reference(RECORD, lookup=down)
    assert meta is None and "Crossref unavailable" in problems[0]


RETRACTED = {**META, "updated-by": [{"type": "retraction", "DOI": "10.1/notice"}]}


def test_retraction_report_lists_unchecked_records_instead_of_assuming_them_clean():
    records = [RECORD, {"record_id": "R0002", "doi": "10.1/r", "title": "R"}, {"record_id": "R0003", "title": "N"},
               {"record_id": "R0004", "doi": "10.1/gone", "title": "G"}]
    table = {"10.1/x": META, "10.1/r": RETRACTED, "10.1/gone": None}
    rep = references.retraction_report(records, lookup=lambda doi, *a, **k: table[doi])
    assert [r["record_id"] for r in rep["retracted"]] == ["R0002"] and rep["checked"] == 2
    assert {r["record_id"]: r["reason"] for r in rep["unchecked"]} == {
        "R0003": "no DOI", "R0004": "DOI not found in Crossref"}


def test_export_stops_on_a_retracted_cited_paper_unless_the_researcher_recorded_why(run, monkeypatch):  # noqa: F811
    corpus = run.load("selected_corpus.json")
    for c in corpus:
        c["doi"] = "10.1/" + c["record_id"]
    run.save("selected_corpus.json", corpus)
    run._verification_current = lambda report, manuscript: True
    monkeypatch.setattr(references, "crossref_lookup",
                        lambda doi, *a, **k: {**(RETRACTED if doi.endswith("R0001") else META), "title": ["T"]})
    with pytest.raises(orch.Pause, match="R0001 are retracted"):
        run.stage_finalize(run.state())
    assert not (run.dir / "final" / "manuscript.md").exists()
    cp = orch.checkpoints.cp_dir(run.dir)
    (cp / "CP2_approved.json").write_text(json.dumps(
        {"retraction_exceptions": {"R0001": "cited as the retracted source of the claim, and said so in the text"}}),
        encoding="utf-8")
    assert run.stage_finalize(run.state()) == "done"
    status = json.loads((run.dir / "final" / "submission_status.json").read_text(encoding="utf-8"))
    assert any("RETRACTED" in b for b in status["blockers"])           # still listed for the authors


# ------------------------------------------------------------------------------------ declarations (item 13)
SUMMARY = {"models_by_agent": {"A05-KE": {"claude-sonnet-5-5": 12}, "A07-SYN": {"claude-opus-5": 5, "claude-sonnet-5-5": 1}},
           "mixed_model_agents": ["A07-SYN"],
           "human_decisions": [{"checkpoint": "CP2"}, {"checkpoint": "CP3"}, {"checkpoint": "CP3"}]}


def test_declarations_are_drafted_from_provenance_and_block_until_a_person_finalises_them(tmp_path):
    state = submission.write_declaration_drafts(tmp_path, SUMMARY)
    ai = state["ai_use_disclosure"]
    assert "claude-opus-5, claude-sonnet-5-5 proposed a synthesis" in ai["text"] and "A07-SYN more than one model" in ai["text"]
    assert "selected the papers to include (1 recorded decision)" in ai["text"]
    assert not any(s["final"] for s in state.values())
    assert submission.back_matter(state)[1][1].startswith("**DRAFT — NOT FOR SUBMISSION.**")
    f = tmp_path / "declarations" / "competing_interests.md"
    # marking FINAL is not enough while a placeholder remains, and a name is required
    f.write_text(f.read_text(encoding="utf-8").replace("STATUS: DRAFT", "STATUS: FINAL"), encoding="utf-8")
    probs = submission.declaration_state(tmp_path)["competing_interests"]["problems"]
    assert any("without the name" in p for p in probs) and any("PLACEHOLDER" in p for p in probs)
    f.write_text("STATUS: FINAL May Khalid\n----------\nThe authors declare no competing interests.\n", encoding="utf-8")
    done = submission.declaration_state(tmp_path)["competing_interests"]
    assert done["final"] and done["by"] == "May Khalid" and done["text"] == "The authors declare no competing interests."
    # a draft is never overwritten once a person has touched the file
    submission.write_declaration_drafts(tmp_path, {"models_by_agent": {}})
    assert submission.declaration_state(tmp_path)["competing_interests"]["final"]


def test_finalising_an_unedited_generated_draft_is_refused(tmp_path):
    submission.write_declaration_drafts(tmp_path, {"models_by_agent": {"A05-KE": {"m": 1}}, "human_decisions": []})
    f = tmp_path / "declarations" / "ai_use_disclosure.md"
    raw = f.read_text(encoding="utf-8")
    cleaned = raw.replace("STATUS: DRAFT", "STATUS: FINAL A. Author", 1).replace(
        "[CONFIRM THAT THIS LIST IS COMPLETE, INCLUDING ANY AI TOOL USED OUTSIDE THE PIPELINE, AND DELETE THIS LINE]", "")
    f.write_text(cleaned.replace("- [LIST THE AUTHORS' DECISIONS]", "- approved the scope."), encoding="utf-8")
    assert submission.declaration_state(tmp_path)["ai_use_disclosure"]["final"]
    f.write_text(raw.replace("STATUS: DRAFT", "STATUS: FINAL A. Author", 1), encoding="utf-8")
    assert not submission.declaration_state(tmp_path)["ai_use_disclosure"]["final"]


def test_export_is_not_submission_ready_until_declarations_are_final(run):  # noqa: F811
    run._verification_current = lambda report, manuscript: True
    assert run.stage_finalize(run.state()) == "done"
    final = run.dir / "final"
    status = json.loads((final / "submission_status.json").read_text(encoding="utf-8"))
    assert status["submission_ready"] is False
    assert any("AI use disclosure" in b and "DRAFT" in b for b in status["blockers"])
    md = (final / "manuscript.md").read_text(encoding="utf-8")
    assert "DRAFT — NOT FOR SUBMISSION" in md and "TO BE WRITTEN BY THE AUTHORS" not in md and "CHECK FORMAT" not in md
    for key in submission.DECLARATIONS:
        (final / "declarations" / f"{key}.md").write_text(f"STATUS: FINAL May Khalid\n----------\nWritten by the authors ({key}).\n",
                                                          encoding="utf-8")
    after = run.submission_check()
    assert not any("declarations/" in b for b in after["blockers"])
    assert after["submission_ready"] is False     # the fixture's references and table still block


# ------------------------------------------------------------------------------------------ table (item 14)
def _table(rows, cols=("Study", "System", "Key observation")):
    return {"display_id": "T1", "caption": "Comparative evidence.", "columns": list(cols), "rows": rows, "notes": []}


def test_every_table_row_must_cite_a_core_paper_of_the_corpus():
    corpus = {"R0001": {"tier": "CORE"}, "R0002": {"tier": "SUPPORTING"}}
    rows = [["Smith (2021) [@R0001]", "mouse", "lower"], ["Li (2019) [@R0002]", "rat", "lower"],
            ["Unknown [@R0009]", "cell", "none"], ["No citation", "cell", "none"]]
    probs = submission.table_problems([_table(rows)], corpus)
    assert len(probs) == 3 and "row 2: R0002 is a SUPPORTING paper" in probs[0]
    assert "row 3: R0009 is not in the selected corpus" in probs[1] and "row 4: cites no paper" in probs[2]
    assert submission.table_problems([_table(rows[:1])], corpus) == []


def test_a_table_longer_than_one_page_is_a_problem():
    corpus = {"R0001": {"tier": "CORE"}}
    row = ["Smith (2021) [@R0001]", "glioblastoma stem-like cells", "copper-dependent loss of viability " * 6]
    short, long = _table([row] * 8), _table([row] * 60)
    assert submission.table_page_estimate(short)["fits_one_page"]
    est = submission.table_page_estimate(long)
    assert not est["fits_one_page"] and est["pages"] > 1
    assert any("estimated at" in p for p in submission.table_problems([long], corpus))


# --------------------------------------------------------------------------------- journal limits (item 15)
def _ms(**over):
    base = {"title": "Copper-dependent cytotoxicity of disulfiram in glioblastoma models",
            "abstract": "A short abstract.", "keywords": ["a", "b", "c", "d", "e", "f"],
            "sections": [{"text_markdown": "Body text [@R0001]. ⟦P1⟧"}], "references": ["R0001"],
            "display_items": [{"display_id": "T1"}]}
    return {**base, **over}


@pytest.mark.parametrize("change,rule", [
    ({"title": " ".join(["word"] * 21)}, "title_max_words"),
    ({"abstract": " ".join(["word"] * 201)}, "abstract_max_words"),
    ({"sections": [{"text_markdown": " ".join(["word"] * 5001)}]}, "main_text_max_words"),
    ({"keywords": list("abcdefg")}, "keywords_max"),
    ({"display_items": [{"display_id": "T1"}, {"display_id": "F1"}]}, "display_items_max"),
    ({"sections": [{"text_markdown": "As shown before (Smith et al., 2020), it works."}]}, "references_numeric_style"),
    ({"sections": [{"text_markdown": "A claim.[^1]"}]}, "no_footnotes"),
    ({"sections": [{"text_markdown": "A claim¹ with a superscript note."}]}, "no_footnotes"),
])
def test_each_broken_journal_limit_fails_the_check(change, rule):
    assert compliance.check(_ms())["all_pass"]
    res = compliance.check(_ms(**change))
    assert not res["all_pass"] and rule in res["failed"]


def test_limits_at_the_boundary_pass():
    res = compliance.check(_ms(title=" ".join(["word"] * 20), abstract=" ".join(["word"] * 200),
                               sections=[{"text_markdown": " ".join(["word"] * 5000)}]))
    assert res["all_pass"], res["failed"]


def test_a12_stage_stops_on_a_broken_limit(run):  # noqa: F811
    run.save("manuscript_plan.json", {"display_items": [{"display_id": "T1"}]})
    with pytest.raises(orch.Pause, match="breaks journal limits: title_max_words"):
        run._compliance_gate(_ms(title=" ".join(["word"] * 25)), "A12-EDI PROOF")
    assert run.load("compliance_latest.json")["failed"] == ["title_max_words"]
    run._compliance_gate(_ms(), "A12-EDI PROOF")   # within every limit: no pause


def test_journal_config_matches_the_limits_the_researcher_named():
    from litreview import config
    lim = config.load("journal_scirev")
    assert (lim["limits"]["title_max_words"], lim["limits"]["abstract_max_words"], lim["limits"]["main_text_max_words"],
            lim["limits"]["keywords_max"], lim["limits"]["display_items_max"]) == (20, 200, 5000, 6, 1)
    assert lim["limits"]["footnotes_allowed"] is False and lim["references"]["style"] == "nature_numeric"
