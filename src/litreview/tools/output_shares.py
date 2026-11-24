"""Measured output tokens per call, by agent and mode, from a run's cost log (item: replace assumed output shares).

    litreview output-shares RUN            print what the run measured, next to what the forecast assumes
    litreview output-shares RUN --write    replace the matching cells of records/output_shares.json (MEASURED)

A call's `output_tokens` is what the provider billed as output: visible text plus thinking or reasoning. Only
completed calls count: a truncated call's output is its cap, not a measurement, and a repair call is not the
agent's own output. A NON-REPRESENTATIVE sample run is refused: its sizes (1 paper, 3 of 11 packets, one section)
say nothing about a full run, and the researcher's rule keeps it out of every forecast.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..paths import RECORDS_DIR

MIN_CALLS = 3   # fewer completed calls than this is reported but never written as MEASURED


class NotRepresentative(ValueError):
    pass


def is_sample(run_dir: Path) -> bool:
    run_dir = Path(run_dir)
    if (run_dir / "input" / "a07_a09_sample.json").exists():
        return True
    try:
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return state.get("profile") == "sample" or str(state.get("status", "")).startswith("COMPLETE_SAMPLE")


def key_of(agent: str, step: str) -> str | None:
    """The records/output_shares.json key a step belongs to, or None when the step is not a forecast cell."""
    if agent == "A07-SYN":
        m = re.search(r"_(PLAN|GROUP|RECONCILE|FINAL)(?:_|$)", step)
        return f"A07-SYN.{m.group(1)}" if m else None
    if agent == "A10-RV":
        m = re.search(r"_(LOCAL|GLOBAL)(?:_|$)", step)
        return f"A10-RV.{m.group(1)}" if m else None
    if agent == "A09-WRI":
        return "A09-WRI.A09_FRONT_MATTER" if "front" in step.lower() else "A09-WRI.A09_SECTION"
    if agent == "A12-EDI":
        return "A12-EDI.A12_UNIT"
    return agent if agent in ("A08-OL", "A11-RC") else None


def _pct(values: list[int], q: float) -> int:
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else 0


def measure(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    if is_sample(run_dir):
        raise NotRepresentative(f"{run_dir.name} is a NON-REPRESENTATIVE sample run: its costs and output sizes are "
                                "never used to calibrate the forecast")
    out_dir = run_dir / "outputs"
    cells: dict[str, list[int]] = {}
    for line in (run_dir / "costs.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        key = key_of(e.get("agent", ""), e.get("step", ""))
        if key is None:
            continue
        step = e["step"]
        if list(out_dir.glob(f"{step}.truncated*.json")) or (out_dir / f"{step}.repair.audit.json").exists():
            continue   # truncated or repaired: not a clean measurement of the agent's output
        if not (out_dir / f"{step}.json").exists():
            continue   # no accepted output: failed, refused or still unresolved
        cells.setdefault(key, []).append(int(e.get("output_tokens") or 0))
    return {"run": run_dir.name, "measured_at": time.strftime("%Y-%m-%d"),
            "cells": {k: {"calls": len(v), "mean": round(sum(v) / len(v)), "p90": _pct(v, 0.9), "max": max(v)}
                      for k, v in sorted(cells.items())}}


def write(measured: dict, path: Path | None = None) -> list[str]:
    """Replace the cells this run measured (at least MIN_CALLS completed calls) in records/output_shares.json with
    their p90 (a planning figure should not be an average that half the calls exceed). Returns the keys written."""
    path = path or RECORDS_DIR / "output_shares.json"
    table = json.loads(path.read_text(encoding="utf-8"))
    written = []
    for key, cell in measured["cells"].items():
        if cell["calls"] < MIN_CALLS:
            continue
        table["expected_output_tokens"][key] = {
            "tokens": cell["p90"], "basis": "MEASURED",
            "source": f"run {measured['run']}: p90 of {cell['calls']} completed calls (mean {cell['mean']}, max {cell['max']})"}
        written.append(key)
    table["updated"] = measured["measured_at"]
    path.write_text(json.dumps(table, indent=2) + "\n", encoding="utf-8")
    return written
