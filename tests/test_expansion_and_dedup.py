from litreview.tools.literature import expansion
from litreview.tools.literature.base import Record
from litreview.tools.literature.dedup import deduplicate


def test_seeds_include_contrary_even_outside_seed_families():
    records = [{"record_id": "R1", "query_family_ids": ["QF01"]}, {"record_id": "R2", "query_family_ids": ["QF09"]},
               {"record_id": "R3", "query_family_ids": ["QF09"]}]
    quals = [{"record_id": "R1", "disposition": "QUALIFIED", "role": "PRIMARY"},
             {"record_id": "R2", "disposition": "QUALIFIED", "role": "PRIMARY", "is_contrary_evidence": True},
             {"record_id": "R3", "disposition": "QUALIFIED", "role": "PRIMARY"}]
    assert [s["record_id"] for s in expansion.choose_seeds(quals, records, ["QF01"])] == ["R1", "R2"]


def test_expand_respects_total_cap(monkeypatch):
    monkeypatch.setattr(expansion, "neighbours",
                        lambda rec, d, n, fam: ([Record(source="s2", title=f"{d}{i}", s2_id=f"{d}{i}") for i in range(n)], None))
    found, _ = expansion.expand([{"record_id": "R1"}, {"record_id": "R2"}], ["references", "citations"], 4, 6)
    assert len(found) == 6 and found[0].expansion["seed_record_id"] == "R1"


def test_incremental_dedup_keeps_existing_ids():
    existing = [{"record_id": "R0001", "title": "A", "doi": "10.1/a", "query_family_ids": ["QF01"], "sources": ["pubmed"]}]
    new = [Record(source="s2", title="A", doi="10.1/A", query_family_id="CITEXP:FWD"),
           Record(source="s2", title="B", doi="10.1/b", query_family_id="CITEXP:FWD")]
    merged, stats = deduplicate(new, existing=existing)
    ids = {r["record_id"]: r for r in merged}
    assert stats["new_unique"] == 1 and "R0002" in ids
    assert ids["R0001"]["query_family_ids"] == ["QF01", "CITEXP:FWD"]
