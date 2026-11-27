"""Verified full-text retrieval with the identifiers a record actually has (PMID and/or DOI, plus the PMCID)."""
import pytest

from litreview.tools import fulltext

XML = """<article><front><article-meta>
<article-id pub-id-type="pmid">{pmid}</article-id><article-id pub-id-type="pmc">{pmc}</article-id>
<article-id pub-id-type="doi">{doi}</article-id>
<abstract><p>Surface-enhanced Raman spectra were classified by a convolutional network.</p></abstract>
</article-meta></front><body>
<sec><title>Introduction</title><p>Sensors for anticancer drugs.</p></sec>
<sec><title>Results</title><p>Doxorubicin in spiked plasma was classified into three ranges.</p>
<fig id="f1"><label>Figure 1</label><caption><p>Spectra of doxorubicin at three concentrations.</p></caption></fig></sec>
</body></article>"""


class Resp:
    def __init__(self, content, status=200):
        self.content, self.status_code = content, status


@pytest.fixture
def serve(monkeypatch):
    def install(pmid="12345678", pmc="9876543", doi="10.1000/sers.2025.1"):
        body = XML.format(pmid=pmid, pmc=pmc, doi=doi).encode()
        monkeypatch.setattr(fulltext.requests, "get", lambda url, timeout=None: Resp(body))
    return install


def test_a_doi_only_record_is_retrieved_and_verified(serve):
    serve()
    record = {"pmid": None, "pmcid": "PMC9876543", "doi": "10.1000/SERS.2025.1"}   # DOI case differs: still the same DOI
    sections, source = fulltext.fetch_verified_sections(record)
    assert "Doxorubicin in spiked plasma" in sections["Results"] and "Figure legend Figure 1" in sections
    assert source["verified"] and source["pmid"] is None and source["identifiers_confirmed"] == ["doi"]
    assert len(source["xml_sha256"]) == 64 and source["sections_sha256"]
    fulltext.verify_cached_source(record, sections, source)                 # the cached copy re-verifies offline


def test_a_mismatched_article_is_refused(serve):
    serve(doi="10.1000/another.article")
    with pytest.raises(fulltext.FullTextUnavailable, match="DOI mismatch"):
        fulltext.fetch_verified_sections({"pmid": None, "pmcid": "PMC9876543", "doi": "10.1000/sers.2025.1"})
    serve(pmid="99999999")
    with pytest.raises(fulltext.FullTextUnavailable, match="PMID mismatch"):
        fulltext.fetch_verified_sections({"pmid": "12345678", "pmcid": "PMC9876543", "doi": None})
    serve(pmc="1111111")
    with pytest.raises(fulltext.FullTextUnavailable, match="PMCID mismatch"):
        fulltext.fetch_verified_sections({"pmid": "12345678", "pmcid": "PMC9876543"})


def test_a_pmcid_alone_cannot_confirm_identity(serve):
    serve()
    with pytest.raises(fulltext.FullTextUnavailable, match="a PMID or DOI to confirm identity"):
        fulltext.fetch_verified_sections({"pmcid": "PMC9876543"})


def test_a_cached_copy_with_a_changed_identity_is_refused(serve):
    serve()
    record = {"pmid": None, "pmcid": "PMC9876543", "doi": "10.1000/sers.2025.1"}
    sections, source = fulltext.fetch_verified_sections(record)
    with pytest.raises(fulltext.FullTextUnavailable):
        fulltext.verify_cached_source({**record, "doi": "10.1000/other"}, sections, source)


def test_lookup_status_separates_not_listed_from_unavailable():
    assert fulltext.lookup_status("PMC1", "found (Europe PMC)") == "FOUND"
    assert fulltext.lookup_status(None, "Europe PMC lists no PMC copy; NCBI ID converter HTTP 403") == "NOT_LISTED"
    assert fulltext.lookup_status(None, "Europe PMC unavailable: ConnectTimeout; NCBI ID converter HTTP 403") == "UNAVAILABLE"
    assert "publisher website" in fulltext.ROUTES_NOT_ATTEMPTED


def test_valid_pmcid_for_wrong_publication_is_quarantined_before_handoff(tmp_path, monkeypatch, serve):
    from litreview.orchestrator import Run
    serve(pmid="34887451", pmc="9421940", doi="10.1038/s41572-021-00324-8")
    intended = {"record_id": "R0115", "title": "Multiplex chemotherapeutic sensing",
                "pmid": "41324706", "doi": "10.1007/s00216-025-06241-z", "pmcid": "9421940"}
    run = object.__new__(Run); run.dir = tmp_path
    run.save("fulltext/R0115.json", {"Abstract": "Wrong publication", "Results": "Unrelated science"})
    with pytest.raises(fulltext.FullTextUnavailable, match="PMID mismatch"):
        run._checked_fulltext(intended)
    assert run.load("identity_quarantine/R0115_cache.json")["sections"]["Results"] == "Unrelated science"
    assert run.load("fulltext_provenance/R0115.json") is None


def test_title_mismatch_blocks_fulltext_even_if_identifiers_match(serve):
    serve()
    with pytest.raises(fulltext.FullTextUnavailable, match="title missing or mismatch"):
        fulltext.fetch_verified_sections({"title": "Expected publication", "pmid": "12345678",
                                          "pmcid": "PMC9876543", "doi": "10.1000/sers.2025.1"})


def test_pubmed_own_identifiers_never_come_from_a_cited_reference(monkeypatch):
    from litreview.tools.literature import pubmed
    xml = b"""<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>41324706</PMID><Article>
      <ArticleTitle>Multiplex chemotherapeutic sensing</ArticleTitle><Abstract><AbstractText>Matched abstract.</AbstractText></Abstract>
      </Article></MedlineCitation><PubmedData><ArticleIdList>
      <ArticleId IdType="pubmed">41324706</ArticleId><ArticleId IdType="doi">10.1007/s00216-025-06241-z</ArticleId>
      </ArticleIdList><ReferenceList><Reference><ArticleIdList>
      <ArticleId IdType="doi">10.1038/s41572-021-00324-8</ArticleId><ArticleId IdType="pmc">9421940</ArticleId>
      </ArticleIdList></Reference></ReferenceList></PubmedData></PubmedArticle></PubmedArticleSet>"""
    class Response:
        content=xml
        def raise_for_status(self): pass
    monkeypatch.setattr(pubmed.requests, "post", lambda *a, **k: Response())
    rec=pubmed.fetch_by_pmids(["41324706"], "existing-query")[0]
    assert rec.pmid == "41324706" and rec.doi == "10.1007/s00216-025-06241-z"
    assert rec.pmcid is None and rec.abstract == "Matched abstract."


def test_lookup_rejects_an_unrelated_pmc_candidate(monkeypatch):
    class Response:
        status_code=200
        def json(self):
            return {"resultList":{"result":[{"id":"34887451","doi":"10.1038/s41572-021-00324-8","pmcid":"PMC9421940"}]},
                    "records":[{"pmid":"34887451","doi":"10.1038/s41572-021-00324-8","pmcid":"PMC9421940"}]}
    monkeypatch.setattr(fulltext.requests,"get",lambda *a,**k:Response())
    assert fulltext.find_pmcid("41324706","10.1007/s00216-025-06241-z")[0] is None


def test_projection_does_not_call_an_over_cap_retained_hold_free():
    from litreview.tools.cost_projection import _total
    class Budget:
        cap=50
        def spent(self): return 2.0849717
        def reserved(self): return .124671
    p=_total([{"usd":47.9}],Budget(),{})
    assert p["verdict"]=="OVER_CAP" and p["held_and_reserved_usd"]==.124671


def test_identity_verified_image_table_remains_an_extraction_blocker(monkeypatch):
    raw=XML.format(pmid="12345678",pmc="9876543",doi="10.1000/sers.2025.1").replace(
        "</body>",'<table-wrap id="tbl1"><label>1</label><graphic href="table.jpg"/></table-wrap></body>').encode()
    rec={"pmid":"12345678","pmcid":"PMC9876543","doi":"10.1000/sers.2025.1"}
    assert fulltext.verify_article_xml(rec,raw).find("./body") is not None
    monkeypatch.setattr(fulltext.requests,"get",lambda *a,**k:Resp(raw))
    with pytest.raises(fulltext.FullTextUnavailable,match="Image-only"):
        fulltext.fetch_verified_sections(rec)
