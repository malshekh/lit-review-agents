from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Record:
    source: str
    title: str
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    publication_type: list[str] = field(default_factory=list)
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    s2_id: str | None = None        # Semantic Scholar paperId
    nct_id: str | None = None       # ClinicalTrials.gov registration
    is_preprint: bool = False
    open_access: bool | None = None
    query_family_id: str = ""
    expansion: dict | None = None   # citation expansion provenance: seed, direction, depth
    record_id: str = ""        # assigned after deduplication

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SearchResult:
    source: str
    family_id: str
    query: str
    hit_count: int | None
    records: list[Record]
    error: str | None = None   # SEARCH_FAILED / SOURCE_UNAVAILABLE / QUERY_INVALID text; never "no literature"
