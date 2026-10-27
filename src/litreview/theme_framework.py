"""The review's theme framework: researcher-approved primary themes, plus free subthemes.

A02-SP proposes 5-8 primary themes (configurable; the count is justified against the evidence) and the
researcher approves or edits them at Checkpoint 1. They organize the review and A07's grouping. A04 and
A05 assign a primary theme and any subthemes they need; subthemes travel with records and findings as
attributes. Evidence that fits no primary theme goes to an emerging-evidence queue shown at Checkpoint 2
(records) and Checkpoint 3 (findings). No agent creates a primary theme: only the researcher changes the
framework, and every change is a new version logged in provenance.
"""
from __future__ import annotations

import time


def create(primary_themes: list[dict], count_justification: str, checkpoint: str) -> dict:
    return {"version": 1, "primary_themes": primary_themes, "count_justification": count_justification,
            "history": [{"version": 1, "checkpoint": checkpoint, "change": "approved",
                         "at": time.strftime("%Y-%m-%dT%H:%M:%S")}]}


def revise(framework: dict, primary_themes: list[dict], checkpoint: str, note: str = "") -> dict:
    """A researcher-approved change: a new version, with the previous one kept in history."""
    v = int(framework["version"]) + 1
    old = {t["theme_id"] for t in framework["primary_themes"]}
    new = {t["theme_id"] for t in primary_themes}
    return {**framework, "version": v, "primary_themes": primary_themes,
            "history": framework.get("history", []) + [{
                "version": v, "checkpoint": checkpoint, "added": sorted(new - old), "removed": sorted(old - new),
                "note": note, "previous_primary_themes": framework["primary_themes"],
                "at": time.strftime("%Y-%m-%dT%H:%M:%S")}]}


def ids(framework: dict | None) -> set[str]:
    return {t["theme_id"] for t in (framework or {}).get("primary_themes", [])}


def normalize(obj: dict, framework: dict | None) -> dict:
    """Fill `themes` from `primary_theme_id`. A primary theme ID the framework does not have is never
    accepted: the item is marked emerging instead, so no agent can add a primary theme."""
    if not framework:
        return obj
    pid = obj.get("primary_theme_id")
    if pid in ids(framework):
        return {**obj, "themes": [pid], "subthemes": obj.get("subthemes") or []}
    note = f"assigned unknown primary theme {pid!r}" if pid else "no primary theme assigned"
    return {**obj, "themes": [], "subthemes": obj.get("subthemes") or [], "primary_theme_id": None,
            "emerging": True, "emerging_note": "; ".join(x for x in (obj.get("emerging_note"), note) if x)}


def emerging(items: list[dict], id_key: str) -> list[dict]:
    """The emerging-evidence queue: items that fit no primary theme, for the researcher to review."""
    return [{"id": i.get(id_key), "primary_theme_id": i.get("primary_theme_id"), "subthemes": i.get("subthemes") or [],
             "note": i.get("emerging_note")} for i in items if i.get("emerging")]
