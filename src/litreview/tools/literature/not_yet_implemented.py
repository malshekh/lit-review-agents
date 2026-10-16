"""Sources listed in config/sources.yaml that are not wired up yet.

Not yet implemented: arxiv, chemrxiv, ieee_xplore, scopus, web_of_science, embase.
Until implemented, enabling them returns an explicit SOURCE_UNAVAILABLE result — never an empty
"no literature" result, so A03-LM REPAIR mode can tell a technical gap from an absence.
"""
from .base import SearchResult


def make(source_id: str):
    def search(query: str, family_id: str, max_records: int = 200) -> SearchResult:
        return SearchResult(source_id, family_id, query, None, [],
                            f"SOURCE_UNAVAILABLE: {source_id} client not implemented yet")
    return search
