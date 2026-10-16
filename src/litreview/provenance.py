"""Provenance log: an append-only record of every agent call and every human decision.

This is the source for the researcher's AI-use disclosure and author contribution
statement (journal AI policy). It records who decided what — the agent or the human.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


class ProvenanceLog:
    def __init__(self, run_dir: Path):
        self.path = Path(run_dir) / "provenance.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, event: dict) -> None:
        event = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), **event}
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")

    def agent_call(self, agent_id: str, step: str, model: str, prompt_version: str,
                   output_file: str, status: str) -> None:
        self._write({"type": "agent_call", "actor": "AI", "agent": agent_id, "step": step,
                     "model": model, "prompt_version": prompt_version,
                     "output_file": output_file, "status": status})

    def human_decision(self, checkpoint: str, decision: dict, note: str = "") -> None:
        self._write({"type": "human_decision", "actor": "HUMAN", "checkpoint": checkpoint,
                     "decision": decision, "note": note})

    def tool_run(self, tool: str, step: str, summary: dict) -> None:
        self._write({"type": "tool_run", "actor": "CODE", "tool": tool, "step": step,
                     "summary": summary})

    def events(self) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
