import requests

from litreview.tools import normalization as n


def test_human_gene_resolves_via_hgnc(fake_get):
    fake_get({"genenames.org/fetch/symbol/TP53": {"response": {"docs": [
        {"hgnc_id": "HGNC:11998", "symbol": "TP53", "name": "tumor protein p53"}]}}})
    r = n.normalize_one({"type": "GENE", "mention": "TP53", "molecule_species": "human"})
    assert r["normalization_state"] == "RESOLVED" and r["normalized_id"] == "HGNC:11998"


def test_gene_without_species_is_not_looked_up(fake_get):
    calls = fake_get({})
    r = n.normalize_one({"type": "GENE", "mention": "Trp53"})
    assert r["normalization_state"] == "UNRESOLVED" and not calls


def test_mouse_gene_uses_mygene(fake_get):
    fake_get({"mygene.info": {"hits": [{"symbol": "Trp53", "name": "transformation related protein 53",
                                         "MGI": "MGI:98834", "entrezgene": 22059}]}})
    r = n.normalize_one({"type": "GENE", "mention": "Trp53", "molecule_species": "mouse"})
    assert r["normalized_id"] == "MGI:98834" and r["taxon"] == "NCBITaxon:10090"


def test_drug_approval_from_chembl(fake_get):
    fake_get({"chembl": {"molecules": [{"molecule_chembl_id": "CHEMBL25", "pref_name": "ASPIRIN", "max_phase": "4.0",
                                        "molecule_synonyms": [{"molecule_synonym": "Acetylsalicylic acid"}]}]},
              "pubchem": {"IdentifierList": {"CID": [2244]}}})
    r = n.normalize_one({"type": "APPROVED_DRUG", "mention": "aspirin"})
    assert r["drug_status_verified"] == "APPROVED" and r["pubchem"] == "PubChem CID:2244"


def test_cellosaurus_problematic_flag(fake_get):
    fake_get({"cellosaurus": {"Cellosaurus": {"cell-line-list": [{
        "accession-list": [{"type": "primary", "value": "CVCL_0030"}],
        "species-list": [{"label": "Homo sapiens"}],
        "comment-list": [{"category": "Problematic cell line", "value": "Contaminated."}]}]}}})
    r = n.normalize_one({"type": "CELL_LINE", "mention": "HeLa"})
    assert r["normalized_id"] == "RRID:CVCL_0030" and r["problematic_cell_line"] and r["species_of_origin"] == ["Homo sapiens"]


def test_ols_disease_ambiguous(fake_get):
    fake_get({"ols4": {"response": {"docs": [{"obo_id": "MONDO:1", "label": "x a"}, {"obo_id": "MONDO:2", "label": "x b"}]}}})
    r = n.normalize_one({"type": "DISEASE", "mention": "x"})
    assert r["normalization_state"] == "AMBIGUOUS" and len(r["candidates"]) == 2


def test_network_failure_is_lookup_failed_not_unresolved(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(requests, "get", boom)
    ext = {"entities": [{"entity_id": "E1", "type": "DISEASE", "mention": "asthma"}]}
    out = n.normalize_entities(ext, tmp_path / "cache.json")
    assert out["entities"][0]["normalization_state"] == "LOOKUP_FAILED"
    assert "DISEASE|asthma|" not in (tmp_path / "cache.json").read_text()  # failures are not cached
