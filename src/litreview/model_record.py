"""Per-model refusal record, shared by all runs (runs/model_record.jsonl).

One line per agent call: model, agent, topic family, outcome (COMPLETED or REFUSED), refusal category,
run and step. The orchestrator reads it before each agent call: a model that has refused in a topic
family is not used again for that family. Qualification evidence accumulates as a by-product of running.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .paths import RUNS_DIR

RECORD = RUNS_DIR / "model_record.jsonl"


def entries(path: Path | None = None) -> list[dict]:
    path = path or RECORD
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def add(model: str, agent: str, family: str, outcome: str, run_id: str, step: str,
        category: str | None = None, note: str | None = None, path: Path | None = None) -> None:
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


def summary(path: Path | None = None) -> dict[str, dict[str, dict[str, int]]]:
    """{family: {model: {"COMPLETED": n, "REFUSED": n}}} for `litreview check`."""
    out: dict = {}
    for e in entries(path):
        m = out.setdefault(e["family"], {}).setdefault(e["model"], {"COMPLETED": 0, "REFUSED": 0})
        m[e["outcome"]] = m.get(e["outcome"], 0) + 1
    return out
