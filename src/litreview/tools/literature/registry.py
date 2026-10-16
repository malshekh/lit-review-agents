"""Map source IDs in config/sources.yaml to client functions."""
from __future__ import annotations

from ... import config
from . import europepmc, openalex, pubmed
from .base import SearchResult
from .not_yet_implemented import make

CLIENTS = {
    "pubmed": pubmed.search,
    "europepmc": europepmc.search,
    "openalex": openalex.search,
}


def enabled_sources() -> dict[str, dict]:
    """Enabled discovery sources with their purpose and syntax notes (passed to A03-LM)."""
    srcs = config.load("sources")["discovery_sources"]
    return {k: {"name": v.get("name"), "purpose": v.get("purpose"), "syntax": v.get("syntax")}
            for k, v in srcs.items() if v.get("enabled")}


def search(source_id: str, query: str, family_id: str, max_records: int) -> SearchResult:
    fn = CLIENTS.get(source_id) or make(source_id)
    return fn(query=query, family_id=family_id, max_records=max_records)
