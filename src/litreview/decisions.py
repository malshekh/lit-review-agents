"""Applied researcher decisions: corrections and constraints that reach the agents, not notes about them.

A checkpoint note explains a decision for the record. It changes nothing downstream. An APPLIED decision is a
structured, versioned instruction that names what it applies to, and it is

  - delivered: every agent request whose input contains a finding, record, section or theme the decision names
    receives it under `researcher_decisions` (prompts/shared/core_rules.md makes these binding);
  - part of the request's identity: the attached decisions are part of the payload, and the payload is what a
    receipt, a job turn and a reservation are keyed on. Changing a decision therefore invalidates exactly the
    outputs whose requests carried it, and leaves unrelated completed work reusable;
  - auditable: who decided it, when, at which checkpoint, and every earlier version.

A change to the theme framework is NOT an applied decision. Themes partition the evidence, so a relabel has to
change the framework itself (`litreview revise-framework`), which regenerates every identity built on it. A
decision of kind THEME_FRAMEWORK is refused here for that reason: a relabel is not applied because a note says so.

Storage: runs/<id>/data/decisions/applied.json, written atomically; one entry per version, never edited in place.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

KINDS = ("WORDING", "CONSTRAINT", "EXCLUSION", "INTERPRETATION_LIMIT")
TARGET_KEYS = ("finding_ids", "record_ids", "section_ids", "theme_ids")
DOWNSTREAM = ("A05-KE", "A06-SV", "A07-SYN", "A08-OL", "A09-WRI", "A10-RV", "A11-RC", "A12-EDI")


class DecisionError(ValueError):
    pass


def _path(run_dir: Path) -> Path:
    return Path(run_dir) / "data" / "decisions" / "applied.json"


def load(run_dir: Path) -> list[dict]:
    p = _path(run_dir)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _save(run_dir: Path, entries: list[dict]) -> None:
    p = _path(run_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _clean_targets(applies_to: dict) -> dict:
    unknown = set(applies_to) - set(TARGET_KEYS) - {"agents", "all"}
    if unknown:
        raise DecisionError(f"unknown target key(s): {', '.join(sorted(unknown))}")
    out = {k: sorted({str(x).strip() for x in applies_to.get(k) or [] if str(x).strip()}) for k in TARGET_KEYS}
    out = {k: v for k, v in out.items() if v}
    agents = sorted(set(applies_to.get("agents") or []))
    if set(agents) - set(DOWNSTREAM):
        raise DecisionError(f"agents must be among {', '.join(DOWNSTREAM)}")
    if agents:
        out["agents"] = agents
    if applies_to.get("all"):
        out["all"] = True
    if not any(k in out for k in TARGET_KEYS) and not out.get("all"):
        raise DecisionError("a decision must name what it applies to: finding_ids, record_ids, section_ids or "
                            "theme_ids, or all: true for every request of the listed agents")
    return out


def add(run_dir: Path, kind: str, instruction: str, applies_to: dict, author: str, checkpoint: str = "",
        reason: str = "", decision_id: str | None = None, withdraw: bool = False) -> dict:
    """Record a new decision, or a new version of an existing one (decision_id). Returns the stored entry."""
    if kind == "THEME_FRAMEWORK":
        raise DecisionError("a theme change is made by revising the approved framework (`litreview "
                            "revise-framework`), which regenerates the identities built on it; it cannot be "
                            "recorded as an applied decision")
    if kind not in KINDS:
        raise DecisionError(f"kind must be one of {', '.join(KINDS)}")
    if not (author or "").strip():
        raise DecisionError("a decision needs its author")
    instruction = " ".join((instruction or "").split())
    if not withdraw and len(instruction) < 8:
        raise DecisionError("a decision needs the exact instruction the agents must follow")
    entries = load(run_dir)
    if decision_id:
        previous = [e for e in entries if e["decision_id"] == decision_id]
        if not previous:
            raise DecisionError(f"no decision {decision_id}")
        version = max(e["version"] for e in previous) + 1
    else:
        if withdraw:
            raise DecisionError("withdrawing needs the decision_id")
        numbers = [int(m.group(1)) for e in entries if (m := re.fullmatch(r"D(\d+)", e["decision_id"]))]
        decision_id, version = f"D{max(numbers, default=0) + 1:03d}", 1
    entry = {"decision_id": decision_id, "version": version, "status": "WITHDRAWN" if withdraw else "ACTIVE",
             "kind": kind, "instruction": instruction, "applies_to": _clean_targets(applies_to),
             "author": author.strip(), "checkpoint": checkpoint, "reason": reason.strip(),
             "decided_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _save(run_dir, entries + [entry])
    return entry


def active(run_dir: Path) -> list[dict]:
    """The latest version of every decision that has not been withdrawn, in decision order."""
    latest: dict[str, dict] = {}
    for e in load(run_dir):
        if e["decision_id"] not in latest or e["version"] > latest[e["decision_id"]]["version"]:
            latest[e["decision_id"]] = e
    return [e for _, e in sorted(latest.items()) if e["status"] == "ACTIVE"]


def _strings(obj, out: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            _strings(v, out)
    elif isinstance(obj, (list, tuple)):
        for x in obj:
            _strings(x, out)
    elif isinstance(obj, str) and len(obj) <= 200:
        out.add(obj)


def applicable(decisions: list[dict], agent_id: str, payload: dict) -> list[dict]:
    """The decisions this request must carry: those naming an identifier present anywhere in its input (as a
    value or a key), and `all` decisions for this agent. Matching is by exact identifier, never by substring."""
    if not decisions:
        return []
    present: set[str] = set()
    _strings({k: v for k, v in payload.items() if k != "researcher_decisions"}, present)
    out = []
    for d in decisions:
        t = d["applies_to"]
        if t.get("agents") and agent_id not in t["agents"]:
            continue
        hit = bool(t.get("all")) or any(i in present for k in TARGET_KEYS for i in t.get(k, []))
        if hit:
            out.append({"decision_id": d["decision_id"], "version": d["version"], "kind": d["kind"],
                        "instruction": d["instruction"],
                        "applies_to": {k: t[k] for k in TARGET_KEYS if k in t} or {"all": True}})
    return out


def attach(run_dir: Path, agent_id: str, payload: dict) -> dict:
    """The payload with its applicable decisions under `researcher_decisions` (idempotent; absent when none)."""
    if agent_id not in DOWNSTREAM:
        return payload
    base = {k: v for k, v in payload.items() if k != "researcher_decisions"}
    found = applicable(active(run_dir), agent_id, base)
    return {**base, "researcher_decisions": found} if found else base


def fingerprint(run_dir: Path, agent_id: str | None = None) -> str:
    """Identity of the active decisions (for one agent, or all): enters job identities that cannot be keyed
    per request (A07's interdependent turns)."""
    from .synthesis_registry import fingerprint as fp
    ds = [d for d in active(run_dir) if not agent_id or not d["applies_to"].get("agents")
          or agent_id in d["applies_to"]["agents"]]
    return fp([[d["decision_id"], d["version"], d["kind"], d["instruction"], d["applies_to"]] for d in ds])
