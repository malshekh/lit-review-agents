"""Literature search clients. Each exposes search(query, max_records, filters) -> list[Record]."""
from .base import Record, SearchResult
from .registry import enabled_sources, search

__all__ = ["Record", "SearchResult", "enabled_sources", "search"]
