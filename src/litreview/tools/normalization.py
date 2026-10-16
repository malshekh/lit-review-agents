"""Entity normalization for A05-KE mentions (HGNC, MGI, UniProt, ChEBI, ChEMBL, Cellosaurus, ...).

The agent never writes identifiers; this module fills `normalized_id` and `normalization_state`.
Services are listed in config/sources.yaml (normalization_services).

TODO (week 2): implement lookups, starting with the highest-value ones:
  1. Cellosaurus  - cell line RRID, species of origin, misidentified/contaminated flag
  2. HGNC / MGI   - approved gene symbols (journal nomenclature requirement)
  3. ChEMBL       - max clinical phase (approved vs investigational drug)
"""
from __future__ import annotations


def normalize_entities(extraction: dict) -> dict:
    """Placeholder: marks every entity UNRESOLVED so downstream agents see an honest state."""
    for e in extraction.get("entities", []):
        e.setdefault("normalized_id", None)
        e["normalization_state"] = e.get("normalization_state") or "UNRESOLVED"
    return extraction
