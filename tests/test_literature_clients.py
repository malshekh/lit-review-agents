from litreview.tools.literature import clinicaltrials, pubtator3, semanticscholar
from litreview.tools.literature.base import Record


def test_semanticscholar_bulk_search(fake_get):
    fake_get({"/paper/search/bulk": {"total": 1, "data": [{
        "paperId": "abc", "title": "A biosensor", "abstract": "Text", "year": 2024, "venue": "Anal Chem",
        "authors": [{"name": "Lee J"}], "externalIds": {"DOI": "10.1/x", "PubMed": 123, "PubMedCentral": "999"}}]}})
    res = semanticscholar.search('"biosensor" + cortisol', "QF01", 10)
    r = res.records[0]
    assert res.error is None and r.doi == "10.1/x" and r.pmid == "123" and r.pmcid == "PMC999" and r.s2_id == "abc"


def test_semanticscholar_recommendations(fake_get):
    calls = fake_get({"recommendations": {"recommendedPapers": [{"paperId": "p1", "title": "Rec"}]}}, method="post")
    res = semanticscholar.search("recommend: 10.1/a, 10.1/b ; not: 10.1/c", "QF02", 5)
    assert res.records[0].s2_id == "p1"
    body = calls[0][2]
    assert body["positivePaperIds"] == ["DOI:10.1/a", "DOI:10.1/b"] and body["negativePaperIds"] == ["DOI:10.1/c"]


def test_semanticscholar_neighbours_sorted_newest_first(fake_get):
    fake_get({"/citations": {"data": [{"citingPaper": {"paperId": "old", "title": "Old", "year": 2010}},
                                       {"citingPaper": {"paperId": "new", "title": "New", "year": 2024}}]}})
    recs, err = semanticscholar.neighbours({"doi": "10.1/x"}, "citations", 5, "CITEXP:FWD")
    assert err is None and [r.s2_id for r in recs] == ["new", "old"]


def test_clinicaltrials_field_query_and_mapping(fake_get):
    calls = fake_get({"clinicaltrials.gov": {"totalCount": 1, "studies": [{
        "hasResults": False,
        "protocolSection": {
            "identificationModule": {"nctId": "NCT01", "briefTitle": "Trial of X"},
            "statusModule": {"overallStatus": "TERMINATED", "startDateStruct": {"date": "2019-03"}},
            "descriptionModule": {"briefSummary": "Summary"}, "designModule": {"phases": ["PHASE2"]}}}]}})
    res = clinicaltrials.search("cond:asthma && intr:drug X", "QF05", 10)
    params = calls[0][1]
    assert params["query.cond"] == "asthma" and params["query.intr"] == "drug X"
    r = res.records[0]
    assert r.nct_id == "NCT01" and r.year == 2019 and "TERMINATED" in r.publication_type


def test_pubtator3_fetches_abstracts_from_pubmed(fake_get, monkeypatch):
    fake_get({"pubtator3-api": {"count": 2, "total_pages": 1, "results": [{"pmid": 1}, {"pmid": 2}]}})
    from litreview.tools.literature import pubmed
    monkeypatch.setattr(pubmed, "fetch_by_pmids",
                        lambda ids, fam: [Record(source="pubmed", title=f"T{i}", pmid=i, query_family_id=fam) for i in ids])
    res = pubtator3.search("@GENE_TP53", "QF03", 10)
    assert [r.pmid for r in res.records] == ["1", "2"] and all(r.source == "pubtator3" for r in res.records)


def test_failed_source_reports_error_not_empty_result(fake_get):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("down")
    import litreview.tools.literature.clinicaltrials as ct
    ct.requests.get = boom
    res = ct.search("asthma", "QF09", 5)
    assert res.error.startswith("SEARCH_FAILED")
