from litreview.tools.literature.base import Record
from litreview.tools.literature.dedup import deduplicate


def test_dedup_by_doi_keeps_all_retrieval_paths():
    a = Record(source="pubmed", title="A study", doi="10.1/x", query_family_id="QF01")
    b = Record(source="europepmc", title="A study.", doi="10.1/X", query_family_id="QF03", abstract="abs")
    recs, stats = deduplicate([a, b])
    assert stats["unique"] == 1
    assert recs[0]["query_family_ids"] == ["QF01", "QF03"]
    assert recs[0]["abstract"] == "abs"
