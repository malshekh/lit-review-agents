"""A07-SYN as one logical synthesis job, executed through bounded, stateful calls.

Every call sends the same frozen corpus (the cached prefix) plus a small `turn` object. There is no
growing conversation: earlier proposition bodies are not resent; the model receives a compact index of
its own committed output instead (ID, one-line assertion, findings, group), so it does not restate a
claim. No conversation compaction: summarizing evidence would destroy the global visibility the design
exists to protect. If capacity runs out, the job stops cleanly and resumes from the last committed turn.

Turns: PLAN (groups, 5W1H) -> one GROUP turn per group (propositions) -> FINAL (gaps, interpretations,
thesis options, written against the complete proposition set).

The coverage ledger is kept by this runtime, not by the model: append-only JSONL, item states PENDING /
SATISFIED / FAILED_VALIDATION. A mandatory item is satisfied exactly once; reusing a finding in several
propositions is not duplicate coverage. SATISFIED means structural coverage only — never a warrant.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable

from .agents import AgentError, RefusalError

NARRATIVE_PROMINENCE = {"HEADLINE", "NARRATIVE_PRIMARY", "NARRATIVE_SUPPORTING"}
COVERAGE_NOTE = ("coverage_realization records structural coverage only: an item is SATISFIED when a committed "
                 "proposition or gap claims it and passes the runtime's structural checks. It is not evidence "
                 "that the claim is scientifically correct, and is never a warrant for A10-RV.")


class JobStopped(Exception):
    """The job stopped cleanly (context ceiling, truncated turn). Rerunning resumes from the last commit."""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


# ------------------------------------------------------------------ ledger
class Ledger:
    """Append-only event log. State is derived by replaying it; nothing is ever rewritten."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def events(self) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as fh:
            return [json.loads(x) for x in fh if x.strip()]

    def append(self, *events: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            for e in events:
                fh.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), **e}, ensure_ascii=False) + "\n")

    def state(self) -> dict:
        st = {"items": {}, "satisfied_by": {}, "committed": [], "propositions": [], "duplicates_rejected": 0,
              "propositions_rejected": [], "findings": {}, "turns_rejected": [], "models_by_turn": {}}
        pending: list[dict] = []
        for e in self.events():
            t = e["event"]
            if t == "JOB_STARTED":
                st["items"] = {i: "PENDING" for i in e["mandatory_item_ids"]}
            elif t == "TURN_STAGED":
                pending.append(e)
            elif t == "TURN_COMMITTED":   # a turn counts only once its commit marker is written
                for p in pending:
                    if p["turn"] == e["turn"]:
                        self._apply(st, p)
                pending = [p for p in pending if p["turn"] != e["turn"]]
                st["committed"].append(e["turn"])
                st["models_by_turn"][e["turn"]] = e.get("model")
            elif t == "TURN_REJECTED":
                st["turns_rejected"].append({"turn": e["turn"], "reason": e["reason"]})
        return st

    @staticmethod
    def _apply(st: dict, staged: dict) -> None:
        for pid in staged["accepted"]:
            st["propositions"].append(pid)
        st["propositions_rejected"] += staged["rejected"]
        for item, by in staged["satisfied"].items():
            st["items"][item] = "SATISFIED"
            st["satisfied_by"][item] = by
        for item in staged["failed"]:
            if st["items"].get(item) != "SATISFIED":
                st["items"][item] = "FAILED_VALIDATION"
        st["duplicates_rejected"] += staged["duplicates"]
        for fid, use in staged["finding_uses"]:
            st["findings"].setdefault(fid, [])
            if use not in st["findings"][fid]:
                st["findings"][fid].append(use)


# ------------------------------------------------------------------ the job
class SynthesisJob:
    def __init__(self, job_dir: Path, mandatory: dict[str, dict], finding_ids: list[str], record_of: dict[str, str],
                 call: Callable[[str, dict, str], dict], count: Callable[[dict], int], cfg: dict,
                 served_by: Callable[[], str | None] = lambda: None):
        """call(mode, turn, step) -> parsed output; raises AgentError (incl. truncation). count(turn) ->
        projected input tokens for that call. served_by() -> the model that served the last call (recorded
        on each turn's commit, so a job resumed on an alternate after a refusal names both models).
        cfg: max_tokens_per_turn, context_ceiling_tokens, max_findings_per_group."""
        self.dir = Path(job_dir)
        self.turns_dir = self.dir / "turns"
        self.turns_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(self.dir / "ledger.jsonl")
        self.mandatory, self.finding_ids, self.record_of = mandatory, set(finding_ids), record_of
        self.call, self.count, self.cfg, self.served_by = call, count, cfg, served_by
        self.peak_projected = 0
        if not self.ledger.events():
            self.ledger.append({"event": "JOB_STARTED", "mandatory_item_ids": sorted(mandatory)})

    # --- persistence ----------------------------------------------------
    def _turn_file(self, turn: str) -> Path:
        return self.turns_dir / f"{turn}.json"

    def _committed(self, turn: str) -> dict | None:
        return json.loads(self._turn_file(turn).read_text(encoding="utf-8")) \
            if turn in self.ledger.state()["committed"] else None

    def _commit(self, turn: str, output: dict, staged: dict) -> None:
        """Turn file first, then the staged effects, then the commit marker. A crash before the marker
        leaves the turn uncommitted: it is redone, and its staged effects are never applied."""
        self._turn_file(turn).write_text(json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8")
        self.ledger.append({"event": "TURN_STAGED", "turn": turn, **staged},
                           {"event": "TURN_COMMITTED", "turn": turn, "model": self.served_by()})

    def _run_turn(self, mode: str, turn: str, payload: dict) -> dict:
        projected = self.count(payload) + int(self.cfg["max_tokens_per_turn"])
        self.peak_projected = max(self.peak_projected, projected)
        if projected > int(self.cfg["context_ceiling_tokens"]):
            reason = (f"projected {projected:,} tokens (input + max output) exceeds the ceiling "
                      f"{int(self.cfg['context_ceiling_tokens']):,}")
            self.ledger.append({"event": "TURN_REJECTED", "turn": turn, "reason": reason})
            raise JobStopped(f"{turn}: {reason}")
        try:
            return self.call(mode, payload, turn)
        except RefusalError:
            raise
        except AgentError as e:   # truncation or invalid output: nothing from this turn is kept
            self.ledger.append({"event": "TURN_REJECTED", "turn": turn, "reason": str(e)[:300]})
            raise JobStopped(f"{turn}: {e}") from e

    # --- validation -----------------------------------------------------
    def _validate(self, turn: str, propositions: list[dict], gaps: list[dict], extra_uses: list) -> tuple[dict, list[dict]]:
        st = self.ledger.state()
        seen_ids = set(st["propositions"])
        seen_assertions = {_norm(p["assertion"]) for t in st["committed"]
                           for p in (json.loads(self._turn_file(t).read_text(encoding="utf-8")).get("propositions") or [])}
        items = dict(st["items"])
        staged = {"accepted": [], "rejected": [], "satisfied": {}, "failed": [], "duplicates": 0, "finding_uses": []}
        kept = []
        for p in propositions:
            pid = p.get("proposition_id")
            cited = list(p.get("supporting_finding_ids") or []) + list(p.get("conflicting_finding_ids") or [])
            unknown = [f for f in cited if f not in self.finding_ids]
            reason = ("missing proposition_id" if not pid else
                      "duplicate proposition_id" if pid in seen_ids else
                      "restates a committed proposition" if _norm(p.get("assertion")) in seen_assertions else
                      f"unknown finding IDs {unknown}" if unknown else
                      "cites no finding" if not cited and p.get("type") == "SOURCE_GROUNDED" else None)
            if reason:
                staged["rejected"].append({"turn": turn, "proposition_id": pid, "reason": reason})
                staged["duplicates"] += reason.startswith(("duplicate", "restates"))
                continue
            seen_ids.add(pid)
            seen_assertions.add(_norm(p.get("assertion")))
            staged["accepted"].append(pid)
            kept.append(p)
            staged["finding_uses"] += [(f, "SUPPORTING") for f in p.get("supporting_finding_ids") or []]
            staged["finding_uses"] += [(f, "CONFLICTING") for f in p.get("conflicting_finding_ids") or []]
            self._claims(p, pid, cited, items, staged, narrative=p.get("prominence") in NARRATIVE_PROMINENCE)
        for g in gaps:
            self._claims(g, g.get("gap_id"), list(g.get("established_by") or []), items, staged, narrative=True,
                         gap=True)
        staged["finding_uses"] += extra_uses
        return staged, kept

    def _claims(self, element: dict, eid: str, cited: list[str], items: dict, staged: dict, narrative: bool,
                gap: bool = False) -> None:
        for item_id in element.get("satisfies") or []:
            item = self.mandatory.get(item_id)
            if item is None:   # unknown or non-mandatory item: nothing to satisfy, claim ignored
                continue
            if items.get(item_id) == "SATISFIED":
                staged["duplicates"] += 1     # an item is satisfied exactly once
                continue
            problem = None
            if item.get("required_visibility") == "NARRATIVE" and not narrative:
                problem = "requires narrative visibility"
            if item["kind"] == "SELECTED_PAPER" and (gap or item["record_id"] not in
                                                     {self.record_of.get(f) for f in cited}
                                                     | set(element.get("citation_record_ids") or [])):
                problem = "does not cite the paper"
            if problem:
                staged["failed"].append(item_id)
                items[item_id] = "FAILED_VALIDATION"
            else:
                staged["satisfied"][item_id] = eid
                items[item_id] = "SATISFIED"

    # --- turns ----------------------------------------------------------
    def _index(self) -> list[dict]:
        out = []
        for t in self.ledger.state()["committed"]:
            body = json.loads(self._turn_file(t).read_text(encoding="utf-8"))
            for p in body.get("propositions") or []:
                out.append({"id": p["proposition_id"], "assertion": (p.get("assertion") or "")[:200],
                            "findings": (p.get("supporting_finding_ids") or []) + (p.get("conflicting_finding_ids") or []),
                            "group": body.get("_group_id")})
        return out

    def _pending(self, among: list[str] | None = None) -> list[str]:
        items = self.ledger.state()["items"]
        ids = among if among is not None else list(items)
        return [i for i in ids if items.get(i) in ("PENDING", "FAILED_VALIDATION")]

    def plan(self) -> dict:
        done = self._committed("PLAN")
        if done:
            return done
        out = self._run_turn("PLAN", "PLAN", {"mode": "PLAN", "limits": {
            "max_findings_per_group": int(self.cfg["max_findings_per_group"])},
            "mandatory_item_ids": sorted(self.mandatory)})
        groups, size = [], int(self.cfg["max_findings_per_group"])
        for g in out.get("groups") or []:
            fids = [f for f in g.get("finding_ids") or [] if f in self.finding_ids]
            parts = [fids[i:i + size] for i in range(0, len(fids), size)] or [[]]
            for n, part in enumerate(parts, 1):   # mechanical split of oversized groups; kind and basis kept
                gid = g["group_id"] if len(parts) == 1 else f"{g['group_id']}.{n}"
                groups.append({**g, "group_id": gid, "finding_ids": part, "split_from": g["group_id"] if len(parts) > 1 else None,
                               "manifest_item_ids": [i for i in g.get("manifest_item_ids") or [] if i in self.mandatory]
                               if n == 1 else []})
        out["groups"] = groups
        unused = [(x["finding_id"], "UNUSED") for x in out.get("findings_not_used") or [] if x.get("finding_id") in self.finding_ids]
        self._commit("PLAN", out, {"accepted": [], "rejected": [], "satisfied": {}, "failed": [], "duplicates": 0,
                                   "finding_uses": unused})
        return out

    def group(self, g: dict) -> None:
        turn = f"GROUP_{g['group_id']}"
        if self._committed(turn):
            return
        out = self._run_turn("GROUP", turn, {
            "mode": "GROUP", "group": {k: g.get(k) for k in ("group_id", "kind", "name", "basis", "primary_theme_id",
                                                              "finding_ids")},
            "assigned_item_ids": self._pending(g.get("manifest_item_ids") or []),
            "other_pending_item_ids": [i for i in self._pending() if i not in (g.get("manifest_item_ids") or [])],
            "prior_propositions": self._index()})
        extra = [(f, "CONTEXT") for f in out.get("findings_context") or [] if f in self.finding_ids]
        extra += [(x["finding_id"], "UNUSED") for x in out.get("findings_not_used") or [] if x.get("finding_id") in self.finding_ids]
        staged, kept = self._validate(turn, out.get("propositions") or [], [], extra)
        self._commit(turn, {**out, "propositions": kept, "_group_id": g["group_id"]}, staged)

    def final(self) -> dict:
        done = self._committed("FINAL")
        if done:
            return done
        bodies = [p for t in self.ledger.state()["committed"]
                  for p in json.loads(self._turn_file(t).read_text(encoding="utf-8")).get("propositions") or []]
        out = self._run_turn("FINAL", "FINAL", {"mode": "FINAL", "propositions": bodies,
                                                "pending_item_ids": self._pending()})
        staged, kept = self._validate("FINAL", out.get("propositions") or [], out.get("knowledge_gaps") or [], [])
        self._commit("FINAL", {**out, "propositions": kept}, staged)
        return out

    # --- the whole job --------------------------------------------------
    def run(self) -> dict:
        plan = self.plan()
        for g in plan["groups"]:
            self.group(g)
        self.final()
        return self.assemble()

    def assemble(self) -> dict:
        st = self.ledger.state()
        plan = self._committed("PLAN") or {}
        turns = [json.loads(self._turn_file(t).read_text(encoding="utf-8")) for t in st["committed"]]
        final = self._committed("FINAL") or {}
        props = [p for t in turns for p in t.get("propositions") or []]
        coverage = [{"manifest_item_id": i, "status": s, "satisfied_by": st["satisfied_by"].get(i),
                     "required_visibility": self.mandatory[i].get("required_visibility")}
                    for i, s in sorted(st["items"].items())]
        dispositions = {f: st["findings"].get(f, ["UNACCOUNTED"]) for f in sorted(self.finding_ids)}
        pending = [c["manifest_item_id"] for c in coverage if c["status"] != "SATISFIED"]
        unaccounted = [f for f, u in dispositions.items() if u == ["UNACCOUNTED"]]
        models = sorted({m for m in st["models_by_turn"].values() if m})
        mixed = ([f"MIXED_MODELS: this synthesis was produced by {len(models)} models ({', '.join(models)}); "
                  "see models_by_turn. Report both in the AI-use disclosure."] if len(models) > 1 else [])
        return {
            "agent_id": "A07-SYN", "prompt_version": plan.get("prompt_version", ""),
            "status": "COMPLETE" if not pending and not unaccounted else "INCOMPLETE",
            "warnings": mixed + [w for t in turns for w in t.get("warnings") or []],
            "models": models,
            "models_by_turn": dict(st["models_by_turn"]),
            "limitations": [x for t in turns for x in t.get("limitations") or []],
            "package_version": f"job-{len(st['committed'])}-turns",
            "fivew1h": plan.get("fivew1h") or [],
            "groups": plan.get("groups") or [],
            "propositions": props,
            "context_contrasts": [c for t in turns for c in t.get("context_contrasts") or []],
            "knowledge_gaps": final.get("knowledge_gaps") or [],
            "proposed_interpretations": final.get("proposed_interpretations") or [],
            "thesis_options": final.get("thesis_options") or [],
            "beyond_prose_bindings": final.get("beyond_prose_bindings") or [],
            "coverage_note": COVERAGE_NOTE,
            "coverage_realization": coverage,
            "coverage_incomplete_item_ids": pending,
            "finding_dispositions": dispositions,
            "findings_unaccounted": unaccounted,
            "job_stats": {"turns_committed": len(st["committed"]), "turns_rejected": st["turns_rejected"],
                          "propositions_valid": len(props), "propositions_rejected": st["propositions_rejected"],
                          "duplicates_rejected": st["duplicates_rejected"],
                          "items": {s: list(st["items"].values()).count(s)
                                    for s in ("SATISFIED", "PENDING", "FAILED_VALIDATION")},
                          "peak_projected_tokens": self.peak_projected},
            "researcher_decision": {"selected_thesis": None, "adopted_interpretations": [],
                                    "rejected_interpretations": [], "edits": None, "approved_at": None},
        }
