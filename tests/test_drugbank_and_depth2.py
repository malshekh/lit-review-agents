from litreview.tools import normalization as n
from litreview.tools.literature import expansion
from litreview.tools.literature.base import Record
from conftest import FakeResp

S = {"key": "k", "base_url": "https://api.drugbank.com/v1", "region": None}


def test_drugbank_resolves_and_reads_groups(fake_get):
    calls = fake_get({"/drug_names": {"products": [{"name": "Aspirin 81", "ingredients": [
                          {"drugbank_id": "DB00945", "name": "Acetylsalicylic acid"}]}]},
                      "/drugs/DB00945": {"drugbank_id": "DB00945", "groups": ["Approved", "Vet_approved"]}})
    r = n.drugbank("aspirin", S)
    assert r == {"drugbank_state": "RESOLVED", "drugbank_id": "DB00945", "drugbank_groups": ["approved", "vet_approved"]}
    assert calls[0][1]["q"] == "aspirin"


def test_drugbank_several_ids_is_ambiguous(fake_get):
    fake_get({"/drug_names": [{"drugbank_id": "DB1", "name": "a"}, {"drugbank_id": "DB2", "name": "b"}]})
    assert n.drugbank("x", S)["drugbank_state"] == "AMBIGUOUS"


def test_crosscheck_flags_disagreement_and_keeps_chembl(monkeypatch):
    monkeypatch.setattr(n, "drugbank_settings", lambda: S)
    monkeypatch.setattr(n, "drugbank", lambda name, s: {"drugbank_state": "RESOLVED", "drugbank_id": "DB1",
                                                         "drugbank_groups": ["investigational", "withdrawn"]})
    r = n._drugbank_crosscheck({"drug_status_verified": "APPROVED", "max_clinical_phase": 4.0}, "x")
    assert r["drug_status_verified"] == "APPROVED"               # ChEMBL is never overwritten
    assert "DrugBank groups" in r["drug_status_conflict"] and "withdrawn" in r["drug_status_conflict"]


def test_drugbank_failure_keeps_chembl_and_is_not_cached(monkeypatch, tmp_path, fake_get):
    monkeypatch.setattr(n, "drugbank_settings", lambda: S)
    fake_get({"chembl": {"molecules": [{"molecule_chembl_id": "CHEMBL25", "pref_name": "ASPIRIN", "max_phase": "4"}]},
              "pubchem": {"IdentifierList": {"CID": [2244]}}, "drugbank": FakeResp(None, 401)})
    cache = tmp_path / "cache.json"
    ext = n.normalize_entities({"entities": [{"type": "APPROVED_DRUG", "mention": "aspirin"}]}, cache)
    e = ext["entities"][0]
    assert e["normalized_id"] == "CHEMBL25" and e["drugbank_state"] == "LOOKUP_FAILED"
    assert cache.read_text(encoding="utf-8").strip() == "{}"


def test_drugbank_off_by_default():
    assert n.drugbank_settings() is None


def test_depth2_seeds_are_qualified_depth1_records_only():
    records = [{"record_id": "R1"}, {"record_id": "R2", "expansion": {"depth": 1}},
               {"record_id": "R3", "expansion": {"depth": 1}}, {"record_id": "R4", "expansion": {"depth": 1}}]
    quals = [{"record_id": "R1", "disposition": "QUALIFIED", "role": "PRIMARY"},
             {"record_id": "R2", "disposition": "QUALIFIED", "role": "PRIMARY"},
             {"record_id": "R3", "disposition": "EXCLUDED"},
             {"record_id": "R4", "disposition": "QUALIFIED", "role": "CONTEXT"}]
    assert [s["record_id"] for s in expansion.choose_next_seeds(quals, records, 1)] == ["R2"]


def test_expand_tags_depth(monkeypatch):
    monkeypatch.setattr(expansion, "neighbours", lambda rec, d, k, fam: ([Record(source="s2", title="t")], None))
    found, log = expansion.expand([{"record_id": "R2"}], ["citations"], 5, 10, depth=2)
    assert found[0].expansion["depth"] == 2 and log[0]["depth"] == 2
    assert expansion.expand([{"record_id": "R2"}], ["citations"], 5, 0, depth=2)[0] == []
