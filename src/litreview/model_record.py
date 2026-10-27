"""Per-model refusal record, shared by all runs and machines (records/model_record.jsonl, tracked in git).

One line per agent call: model, agent, topic family, outcome (COMPLETED or REFUSED), refusal category,
run and step. The orchestrator reads it before each agent call: a model that has refused in a topic
family is not used again for that family. Qualification evidence accumulates as a by-product of running;
commit the file after a run so it survives a fresh clone. It is append-only and merges with git's
`union` driver (.gitattributes), so appends from two machines never conflict.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .paths import RECORDS_DIR, RUNS_DIR

RECORD = RECORDS_DIR / "model_record.jsonl"
DEFAULT_RECORD = RECORD
LEGACY = RUNS_DIR / "model_record.jsonl"   # before 2026-10-27; gitignored, so it existed on one machine only


def _migrate_legacy() -> None:
    """Move a clone's old runs/model_record.jsonl into the tracked record, once. Lines already present
    are not duplicated; the old file is renamed, not deleted. Skipped when RECORD is redirected (tests)."""
    if RECORD != DEFAULT_RECORD or not LEGACY.exists():
        return
    have = set(RECORD.read_text(encoding="utf-8").splitlines()) if RECORD.exists() else set()
    new = [ln for ln in LEGACY.read_text(encoding="utf-8").splitlines() if ln.strip() and ln not in have]
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    with open(RECORD, "a", encoding="utf-8") as fh:
        fh.writelines(ln + "\n" for ln in new)
    LEGACY.rename(LEGACY.with_name("model_record.jsonl.migrated"))


def entries(path: Path | None = None) -> list[dict]:
    if path is None:
        _migrate_legacy()
    path = path or RECORD
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as fh:
        # a union merge keeps both copies of a line two branches added at different positions; every line
        # carries time, run and step, so an exact repeat is a merge artifact, never a second call
        lines = dict.fromkeys(line.strip() for line in fh if line.strip())
    return [json.loads(line) for line in lines]


def add(model: str, agent: str, family: str, outcome: str, run_id: str, step: str,
        category: str | None = None, note: str | None = None, path: Path | None = None) -> None:
    if path is None:
        _migrate_legacy()
    path = path or RECORD
    entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": model, "agent": agent, "family": family,
             "outcome": outcome, "category": category, "run_id": run_id, "step": step}
    if note:
        entry["note"] = note
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def refused(family: str, path: Path | None = None) -> dict[str, str]:
    """{model: first refusal category} for models that have refused in this topic family."""
    out: dict[str, str] = {}
    for e in entries(path):
        if e["family"] == family and e["outcome"] == "REFUSED":
            out.setdefault(e["model"], e.get("category") or "unspecified")
    return out


def refusals(family: str, path: Path | None = None) -> dict[str, list[dict]]:
    """{model: [{agent, category, run_id, step}, ...]} — every refusal in this family, with the agent it
    happened at. Routing disqualifies a model for the whole family; the agent is kept so the rule can be
    narrowed to per-agent later if the evidence shows the classifier fires per task, not per topic."""
    out: dict[str, list[dict]] = {}
    for e in entries(path):
        if e["family"] == family and e["outcome"] == "REFUSED":
            out.setdefault(e["model"], []).append({k: e.get(k) for k in ("agent", "category", "run_id", "step")})
    return out


def no_qualified_model(agent: str, family: str, tried: list[str], run_id: str, step: str,
                       path: Path | None = None) -> None:
    """Record that every candidate for `agent` has refused this family: the pipeline cannot run this agent
    for it. Informational (routing derives the dead end from the refusals and the current candidates, so
    adding a qualified alternate later unblocks it); it makes the dead end visible in the record and in
    `litreview check`."""
    add("(none)", agent, family, "NO_QUALIFIED_MODEL", run_id, step,
        note=f"every candidate refused: {', '.join(tried)}", path=path)


def summary(path: Path | None = None) -> dict[str, dict[str, dict[str, int]]]:
    """{family: {model: {"COMPLETED": n, "REFUSED": n}}} for `litreview check`. Dead ends
    (NO_QUALIFIED_MODEL) are reported by `blocked`, not counted here."""
    out: dict = {}
    for e in entries(path):
        if e["outcome"] == "NO_QUALIFIED_MODEL":
            continue
        m = out.setdefault(e["family"], {}).setdefault(e["model"], {"COMPLETED": 0, "REFUSED": 0})
        m[e["outcome"]] = m.get(e["outcome"], 0) + 1
    return out


def blocked(path: Path | None = None) -> dict[str, list[str]]:
    """{family: [agents]} with a recorded dead end."""
    out: dict[str, list[str]] = {}
    for e in entries(path):
        if e["outcome"] == "NO_QUALIFIED_MODEL" and e["agent"] not in out.get(e["family"], []):
            out.setdefault(e["family"], []).append(e["agent"])
    return out
