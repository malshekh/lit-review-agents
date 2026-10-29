"""Normalization status and scientific validity are separate checks.

An identifier never decides whether a finding is supported; a conflicting identifier is unusable everywhere
(kept only in the audit record); an identity change after validation sends the finding back to A06; and an
abbreviation resolves only through the source's own expansion of it."""
import json

import pytest

from litreview import evidence as ev
from litreview import model_record
from litreview import orchestrator as orch
from litreview.tools import normalization as n

WRONG = {"normalization_state": "RESOLVED", "normalization_source": "OLS4/CHEBI", "normalized_id": "CHEBI:81585",
         "approved_name": "cis-11-Methyl-2-dodecenoic acid"}


def _run(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    run = orch.Run("t")
    run.save_state({"stage": "validate", "status": "READY", "counters": {}})
    run.save("selected_corpus.json", [{"record_id": "R0001"}])
    run.save("fulltext/R0001.json", {"Abstract": "We repurposed disulfiram (DSF) against glioblastoma."})
    run.save("extractions/R0001.json", {
        "record_id": "R0001",
        "entities": [{"entity_id": "E1", "mention": "DSF", "type": "APPROVED_DRUG", **WRONG},
                     {"entity_id": "E2", "mention": "growth", "type": "PHENOTYPE", "normalization_state": "UNRESOLVED"}],
        "findings": [{"finding_id": "F1", "subject_entity_id": "E1", "object_entity_id": "E2", "predicate": "DECREASES",
                      "span": "DSF suppressed growth by 92%.", "context_id": "C1"}],
        "contexts": [{"context_id": "C1", "fields": {}}]})
    return run


def _validation(disposition="SUPPORTED", **extra):
    return {"record_id": "R0001", "validations": [{"finding_id": "F1", "gate1": "PASSED", "gate2": "ALIGNED",
                                                  "disposition": disposition, "plain_language_limit": "l"}], **extra}


def test_a06_conflict_strips_the_identity_everywhere_and_keeps_it_only_in_the_audit(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch)
    run._save_validation("R0001", _validation(normalization_conflicts=[
        {"entity_id": "E1", "mention": "DSF", "attached_id": "CHEBI:81585",
         "source_says": "disulfiram (DSF)", "reason": "the paper expands DSF as disulfiram"}]))
    e1 = run.load("extractions/R0001.json")["entities"][0]
    assert e1["normalization_state"] == "CONFLICT" and e1["normalized_id"] is None and e1["mention"] == "DSF"
    assert "approved_name" not in e1
    audit = run.load("normalization_audit.json")
    assert audit[0]["conflicting_id"] == "CHEBI:81585" and audit[0]["raised_by"] == "A06-SV"
    assert audit[0]["source_spans"] == ["DSF suppressed growth by 92%."]
    assert [r["conflicting_id"] for r in run.load("normalization_conflicts.json")] == ["CHEBI:81585"]
    vf = run._validated_findings(run.load("selected_corpus.json"))
    blob = json.dumps(vf)
    assert "CHEBI:81585" not in blob and "dodecenoic" not in blob             # never reaches A06 theme, A07, A10
    assert vf[0]["entities"]["E1"] == {"mention": "DSF", "type": "APPROVED_DRUG", "normalization_state": "CONFLICT"}
    # scientific validity is judged against the mention: the finding stands, and the stripping is not an
    # identity change (A06 raised it and validated against the mention)
    assert vf[0]["eligibility"]["status"] == "SUPPORTING"


def test_a_registered_conflicting_id_is_rejected_for_any_later_entity(tmp_path, monkeypatch):
    reg = tmp_path / "conflicts.json"
    n.register_conflicts(reg, [{"conflicting_id": "CHEBI:81585", "mention": "DSF", "raised_by": "A06-SV"}])
    monkeypatch.setattr(n, "normalize_one", lambda e, text=None: dict(WRONG))
    ext = {"entities": [{"entity_id": "E9", "mention": "diffusible signal factor", "type": "NATURAL_PRODUCT"}],
           "findings": []}
    n.normalize_entities(ext, tmp_path / "cache.json", conflicts_path=reg, record_id="R0009")
    assert ext["entities"][0]["normalization_state"] == "CONFLICT" and ext["entities"][0]["normalized_id"] is None
    assert ext["_normalization_audit"][0]["raised_by"] == "REGISTRY"


def test_correcting_an_identity_never_promotes_a_finding_by_itself(tmp_path, monkeypatch):
    """Held and accepted findings alike wait for A06 once an identity they were validated against changes."""
    run = _run(tmp_path, monkeypatch)
    held = {"record_id": "R0001", "validations": [{"finding_id": "F1", "gate1": "PASSED", "gate2": "ENTITY_MISMATCH",
                                                  "disposition": "BLOCKED_ALIGNMENT"}],
            "defect_reports": [{"finding_id": "F1", "defect_type": "ENTITY_MISMATCH",
                                "recorded": "E1 resolves to cis-11-Methyl-2-dodecenoic acid"}]}
    run._save_validation("R0001", held)
    corpus = run.load("selected_corpus.json")
    assert run._validated_findings(corpus)[0]["eligibility"]["status"] == "HELD_FOR_CORRECTION"
    ext = run.load("extractions/R0001.json")
    ext["entities"][0].update(normalized_id="CHEMBL964", approved_name="DISULFIRAM")    # identity corrected
    run.save("extractions/R0001.json", ext)
    after = run._validated_findings(corpus)[0]["eligibility"]
    assert after["status"] == "REVALIDATION_REQUIRED" and after["disposition"] == "BLOCKED_ALIGNMENT"
    # the R0125 case: a finding accepted against the wrong identity is surfaced, not silently kept
    run._save_validation("R0001", _validation())
    ext["entities"][0].update(normalized_id="CHEMBL965")
    run.save("extractions/R0001.json", ext)
    assert run._validated_findings(corpus)[0]["eligibility"]["status"] == "REVALIDATION_REQUIRED"
    # only a fresh validation, against the identity now attached, decides
    run._save_validation("R0001", _validation("SUPPORTED_WITH_CONSTRAINTS"))
    assert run._validated_findings(corpus)[0]["eligibility"]["status"] == "SUPPORTING"


def test_unresolved_or_ambiguous_identity_never_decides_validity():
    for state in ("AMBIGUOUS", "UNRESOLVED", "CONFLICT", "RESOLVED"):
        ext = {"entities": [{"entity_id": "E1", "mention": "U373MG", "normalization_state": state}],
               "findings": [{"finding_id": "F1", "subject_entity_id": "E1"}, {"finding_id": "F2", "subject_entity_id": "E1"}]}
        val = {"validations": [{"finding_id": "F1", "disposition": "SUPPORTED"},
                               {"finding_id": "F2", "disposition": "DOES_NOT_ESTABLISH"}]}
        assert {k: v["status"] for k, v in ev.annotate_paper(ext, val).items()} == \
            {"F1": "SUPPORTING", "F2": "NOT_ESTABLISHED"}


def test_only_a_resolved_identity_is_ever_projected():
    amb = {"mention": "U373MG", "normalization_state": "AMBIGUOUS", "normalized_id": "RRID:CVCL_2219",
           "identity_warnings": ["Misidentification possible: ..."]}
    assert n.usable_identity(amb) == {"identity_warnings": ["Misidentification possible: ..."]}
    assert n.usable_identity({**WRONG, "normalization_state": "CONFLICT"}) == {}
    assert n.usable_identity(WRONG)["normalized_id"] == "CHEBI:81585"


# ------------------------------------------------------------------ abbreviations (offline)
def _route(monkeypatch, ols_docs=(), chembl=(), cids=(), cello=()):
    def get(url, params=None):
        if "ols4" in url:
            return {"response": {"docs": [d for d in ols_docs
                                          if n._squash(params["q"]) in {n._squash(d["label"])} | n._syns(d)]}}
        if "chembl" in url:
            return {"molecules": list(chembl)}
        if "pubchem" in url:
            return {"IdentifierList": {"CID": list(cids)}}
        if "cellosaurus" in url:
            return {"Cellosaurus": {"cell-line-list": list(cello)}}
        return None
    monkeypatch.setattr(n, "_get", get)


SIGNAL = {"obo_id": "CHEBI:81585", "label": "cis-11-Methyl-2-dodecenoic acid", "synonym": ["DSF"]}
CARBODIIMIDE = {"obo_id": "CHEBI:53093", "label": "1,3-di(p-tolyl)carbodiimide", "synonym": ["DTC"]}
DISULFIRAM = {"molecule_chembl_id": "CHEMBL964", "pref_name": "DISULFIRAM", "max_phase": "4",
              "molecule_synonyms": [{"molecule_synonym": "Disulfiram"}]}


def test_source_expansion_takes_precedence_over_an_ontology_hit_on_the_abbreviation(monkeypatch):
    _route(monkeypatch, ols_docs=[SIGNAL], chembl=[DISULFIRAM], cids=[3117])
    r = n.normalize_one({"type": "APPROVED_DRUG", "mention": "DSF"}, "the potential of repurposing disulfiram (DSF) in GBM")
    assert r["normalization_state"] == "RESOLVED" and r["normalized_id"] == "CHEMBL964"
    assert r["resolved_from"] == "SOURCE_EXPANSION" and r["expansion"]["long_form"] == "disulfiram"
    assert r["abbreviation_candidates_overridden"] == ["CHEBI:81585 cis-11-Methyl-2-dodecenoic acid"]


def test_an_abbreviation_without_a_source_expansion_is_never_resolved(monkeypatch):
    _route(monkeypatch, ols_docs=[CARBODIIMIDE])
    r = n.normalize_one({"type": "TOOL_COMPOUND", "mention": "DTC"}, "the primary DSF metabolite DTC was less toxic")
    assert r["normalization_state"] == "AMBIGUOUS" and r["normalized_id"] is None
    assert r["candidates"] == ["CHEBI:53093 1,3-di(p-tolyl)carbodiimide"]
    _route(monkeypatch)
    assert n.normalize_one({"type": "PHENOTYPE", "mention": "ORR"}, "")["normalization_state"] == "UNRESOLVED"


def test_source_and_ontology_contradiction_is_a_conflict_with_no_identity(monkeypatch, tmp_path):
    _route(monkeypatch, ols_docs=[SIGNAL])      # "disulfiram" itself resolves nowhere here
    ext = {"entities": [{"entity_id": "E1", "mention": "DSF", "type": "NATURAL_PRODUCT"}],
           "findings": [{"finding_id": "F1", "subject_entity_id": "E1", "span": "DSF killed cells."}]}
    reg = tmp_path / "conflicts.json"
    n.normalize_entities(ext, tmp_path / "cache.json", sections={"Abstract": "disulfiram (DSF) killed cells"},
                         conflicts_path=reg, record_id="R0001")
    e = ext["entities"][0]
    assert e["normalization_state"] == "CONFLICT" and e["normalized_id"] is None and e["mention"] == "DSF"
    a = ext["_normalization_audit"][0]
    assert a["conflicting_id"] == ["CHEBI:81585"] and a["source_spans"] == ["DSF killed cells."]
    assert [r["conflicting_id"] for r in json.loads(reg.read_text())] == ["CHEBI:81585"]


def test_ols_resolves_only_a_unique_exact_label_in_its_own_ontology(monkeypatch):
    _route(monkeypatch, ols_docs=[{"obo_id": "UBERON:0000120", "label": "blood brain barrier", "synonym": ["BBB"]},
                                  {"obo_id": "HP:6000634", "label": "Exacerbated by opiate medication", "synonym": ["x y"]}])
    assert n.ols("blood-brain barrier", "uberon")["normalized_id"] == "UBERON:0000120"   # hyphen ignored
    assert n.ols("x y", "mondo")["normalization_state"] == "UNRESOLVED"                   # only a foreign term
    assert n.ols("x y", "hp")["normalization_state"] == "AMBIGUOUS"                       # synonym only: unproven


def test_find_expansion():
    assert n.find_expansion("TMZ", "with temozolomide (TMZ) and RT")["long_form"] == "temozolomide"
    two = n.find_expansion("DDC", "diethyldithiocarbamate (DDC) ... dual drug combination (DDC)")
    assert two["conflicting_long_forms"] == ["diethyldithiocarbamate", "dual drug combination"]
    assert n.find_expansion("DTC", "the metabolite DTC") is None


def test_renormalizing_replaces_every_stale_identity_field(monkeypatch, tmp_path):
    _route(monkeypatch, ols_docs=[SIGNAL], chembl=[DISULFIRAM], cids=[3117])
    ext = {"entities": [{"entity_id": "E1", "mention": "DSF", "type": "APPROVED_DRUG", **WRONG}], "findings": []}
    n.normalize_entities(ext, tmp_path / "cache.json", sections={"A": "disulfiram (DSF)"})
    assert ext["entities"][0]["normalized_id"] == "CHEMBL964" and ext["entities"][0]["approved_name"] == "DISULFIRAM"


# ------------------------------------------------------------------ Cellosaurus (offline)
def line(acc, ident, *syns, problem=None):
    return {"accession-list": [{"type": "primary", "value": acc}],
            "name-list": [{"type": "identifier", "value": ident}] + [{"type": "synonym", "value": s} for s in syns],
            "species-list": [{"label": "Homo sapiens"}],
            "comment-list": [{"category": "Problematic cell line", "value": problem}] if problem else []}


DERIVATIVES = [line("CVCL_C8XQ", "U251MG-Luc"), line("CVCL_F6CF", "EDITGENE U251MG-CopGFP", "U251MG-CopGFP"),
               line("CVCL_F5UX", "EDITGENE U251MG-FLUC", "U251MG-FLUC")]


def test_the_parent_is_found_among_derivative_heavy_results_and_derivatives_stay_themselves(monkeypatch):
    _route(monkeypatch, cello=DERIVATIVES + [line("CVCL_0021", "U-251MG", "U251MG", "U-251 MG")])
    assert n.cellosaurus("U251MG")["normalized_id"] == "RRID:CVCL_0021"
    assert n.cellosaurus("U251MG-Luc")["normalized_id"] == "RRID:CVCL_C8XQ"
    _route(monkeypatch, cello=[line("CVCL_0021", "U-251MG", "U251MG")])
    assert n.cellosaurus("U251MG-Luc")["normalization_state"] == "UNRESOLVED"          # never the parent


def test_u373mg_stays_ambiguous_with_a_candidate_level_warning(monkeypatch):
    _route(monkeypatch, cello=[line("CVCL_2219", "U-373MG ATCC", "U373MG", problem="Misidentified/contaminated. "
                                    "Shown to be a U-251MG derivative."),
                               line("CVCL_2818", "U-373MG Uppsala", "U373MG")])
    r = n.cellosaurus("U373MG")
    assert r["normalization_state"] == "AMBIGUOUS" and r["candidates"] == ["CVCL_2219", "CVCL_2818"]
    assert [d["problematic"] for d in r["candidate_details"]] == [True, False]
    assert r["identity_warnings"][0].startswith("Misidentification possible: candidate U-373MG ATCC (CVCL_2219)")
    assert "does not establish that the stock was misidentified" in r["identity_warnings"][0]
    assert "problematic_cell_line" not in r            # a property of a resolved line, not asserted here


def test_code_names_are_not_abbreviations_and_self_expanded_mentions_use_their_head(monkeypatch):
    assert not n.is_abbreviation("BI-2536") and not n.is_abbreviation("LY364947") and n.is_abbreviation("5-FU")
    assert n.split_self_expanded("glioblastoma (GBM)") == ("glioblastoma", "GBM")
    assert n.split_self_expanded("medial prefrontal cortex (mPFC)") == ("medial prefrontal cortex", "mPFC")
    assert n.split_self_expanded("copper (II)") is None and n.split_self_expanded("cells (HeLa)") is None
    _route(monkeypatch, ols_docs=[{"obo_id": "MONDO:0018177", "label": "glioblastoma", "synonym": ["GBM"]}])
    r = n.normalize_one({"type": "DISEASE", "mention": "glioblastoma (GBM)"})
    assert r["normalized_id"] == "MONDO:0018177" and r["resolved_from"] == "MENTION_HEAD"
