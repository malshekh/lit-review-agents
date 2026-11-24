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
