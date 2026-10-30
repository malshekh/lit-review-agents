"""Orchestrator: a deterministic state machine. It routes; it never makes scientific judgements.

Run state lives in runs/<run_id>/state.json, so a run can stop (checkpoint, budget, error)
and resume exactly where it left off with `litreview run <run_id>`.

Stage order
  scope -> cp1 -> search -> qualify -> expand -> cp2 -> extract -> validate -> synthesize -> cp3
  -> outline -> draft -> review_loop -> finish_edit -> finalize -> done
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path

from . import checkpoints, config, evidence, handoff, model_record, notify, publication
from .agents import AgentError, RefusalError, run_agent
from .agents.base import prompt_version
from .budget import BatchGateRefused, BudgetExceeded, BudgetTracker, UnpricedModel
from .paths import RUNS_DIR, SCHEMAS_DIR
from .provenance import ProvenanceLog
from . import synthesis_input, theme_framework
from .agents.base import build_system_prompt, user_parts
from .batch_stage import BatchStage
from .synthesis_job import JobStopped
from .tools import cost_projection
from .tools import (compliance, display_items, manuscript_export, references, span_check, tags, themes,
                    verification_scope)
from .tools.fulltext import fetch_sections
from .tools.literature import Record, enabled_sources, search
from .tools.literature.dedup import deduplicate
from .tools.literature.expansion import choose_next_seeds, choose_seeds, expand
from .tools import normalization
from .tools.normalization import normalize_entities

STAGES = ["scope", "cp1", "search", "qualify", "expand", "cp2", "extract", "validate", "synthesize", "cp3",
          "outline", "draft", "review_loop", "finish_edit", "finalize", "done"]
# The last stage that calls each agent (A05 re-extracts during validation; A10 verifies through finalize).
AGENT_LAST_STAGE = {"A02-SP": "scope", "A03-LM": "search", "A04-CQ": "expand", "A05-KE": "validate",
                    "A06-SV": "validate", "A07-SYN": "synthesize", "A08-OL": "outline", "A09-WRI": "draft",
                    "A10-RV": "finalize", "A11-RC": "review_loop", "A12-EDI": "finish_edit"}


class NoQualifiedModel(AgentError):
    """Every candidate model for an agent has refused the run's topic family."""


class Pause(Exception):
    """Stop the run and wait for the researcher."""


# ------------------------------------------------------------------ run setup
def new_run(topic: str, notes: str = "", seeds: list[str] | None = None, family: str = "unspecified") -> str:
    run_id = time.strftime("%Y%m%d-%H%M%S")
    d = RUNS_DIR / run_id / "input"
    d.mkdir(parents=True)
    (d / "topic.md").write_text(topic, encoding="utf-8")
    (d / "notes.md").write_text(notes, encoding="utf-8")
    (d / "seeds.txt").write_text("\n".join(seeds or []), encoding="utf-8")
    (d / "topic_family.txt").write_text(family, encoding="utf-8")
    (d / "code_version.json").write_text(json.dumps(code_version(), indent=2), encoding="utf-8")
    Run(run_id).save_state({"stage": "scope", "status": "READY", "counters": {}})
    return run_id


def code_version() -> dict:
    """The commit a run starts from and whether the working tree was clean: a run that tests a frozen
    system can show it ran on exactly that code."""
    import subprocess
    from .paths import REPO_ROOT

    def git(*args: str) -> str | None:
        try:
            return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=20,
                                  check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
    status = git("status", "--porcelain", "--untracked-files=no")
    return {"commit": git("rev-parse", "HEAD"), "clean": None if status is None else status == "",
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


class Run:
    def __init__(self, run_id: str):
        self.id = run_id
        self.dir = RUNS_DIR / run_id
        self.budget = BudgetTracker(self.dir)
        self.prov = ProvenanceLog(self.dir)
        self.cfg = config.load("pipeline")
        self.last_model: str | None = None   # model that served the most recent agent call

    # --- state and data helpers ---------------------------------------
    def state(self) -> dict:
        return json.loads((self.dir / "state.json").read_text(encoding="utf-8"))

    def save_state(self, st: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "state.json").write_text(json.dumps(st, indent=2), encoding="utf-8")

    def data(self, name: str) -> Path:
        p = self.dir / "data" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def save(self, name: str, obj) -> None:
        self.data(name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, name: str, default=None):
        p = self.data(name)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

    def family(self) -> str:
        p = self.dir / "input" / "topic_family.txt"
        return (p.read_text(encoding="utf-8").strip() if p.exists() else "") or "unspecified"

    def route(self, agent_id: str, exclude_providers: frozenset = frozenset()) -> config.AgentModel:
        """First of the agent's candidate models that has not refused in this run's topic family and is not
        on an excluded vendor. `exclude_providers`: the vendors that produced the work this call audits (an
        auditor never runs on the vendor it checks; A06 passes the vendor of each paper's actual extraction)."""
        refused = model_record.refused(self.family())
        candidates = config.agent_candidates(agent_id)
        for m in candidates:
            if m.model not in refused and m.provider not in exclude_providers:
                if m is not candidates[0]:
                    why = ("has refused this topic family" if candidates[0].model in refused else
                           f"is on {candidates[0].provider}, the vendor that produced the work it audits")
                    self._check_alternate_cost(agent_id, candidates[0].model, m.model, why)
                return m
        if exclude_providers and any(m.model not in refused for m in candidates):
            raise AgentError(
                f"{agent_id}: no candidate model outside {', '.join(sorted(exclude_providers))}, the vendor(s) "
                "that produced the work it audits. Vendor separation is a scientific property of the audit, "
                "not an optimization: add an alternate on another vendor in pipeline.yaml -> routing.")
        raise self._no_qualified_model(agent_id, [m.model for m in candidates], "route")

    def _no_qualified_model(self, agent_id: str, tried: list[str], step: str) -> NoQualifiedModel:
        """Every candidate has refused this family. Deliberately a dead end, not a reason to add a model
        chosen for availability rather than fitness. The message names every model tried, where and why it
        refused, so the researcher can judge whether the topic needs rewording or the family is blocked.
        Recorded once per agent and family in the model record."""
        family, all_refusals = self.family(), model_record.refusals(self.family())
        lines = []
        for model in tried:
            seen: dict[tuple, list[dict]] = {}
            for r in all_refusals.get(model, []):
                seen.setdefault((r["agent"], r["category"] or "category not returned"), []).append(r)
            lines.append(f"  - {model}: " + "; ".join(
                f"refused at {a} ({c}), {len(rs)}x, first in run {rs[0]['run_id']} step {rs[0]['step']}"
                for (a, c), rs in seen.items()))
        if agent_id not in model_record.blocked().get(family, []):
            model_record.no_qualified_model(agent_id, family, tried, self.id, step)
        return NoQualifiedModel(
            f"No qualified model for {agent_id} in topic family '{family}'. Every candidate, in routing order, "
            "has refused this family:\n" + "\n".join(lines) + "\nThe pipeline cannot run this agent for this "
            "family. If the refusals look like classifier false positives on the wording, reword the topic and "
            "start a run under a new family; otherwise the family is blocked for this agent.")

    def preflight_routing(self) -> None:
        """At run start: stop before any spending if some agent has no unrefused model in this family,
        rather than paying for search and extraction and stopping at synthesis."""
        refused = model_record.refused(self.family())
        done = STAGES[:STAGES.index(self.state()["stage"])]
        for agent_id in self.cfg["agents"]:
            if AGENT_LAST_STAGE.get(agent_id) in done:   # this run no longer needs the agent
                continue
            tried = [m.model for m in config.agent_candidates(agent_id)]
            if all(t in refused for t in tried):
                raise self._no_qualified_model(agent_id, tried, "preflight")

    def _check_alternate_cost(self, agent_id: str, primary: str, alternate: str,
                              why: str = "has refused this topic family") -> None:
        """Routing to an alternate that would raise the agent's cost by more than routing.max_cost_multiple
        stops the run and asks, before any call. `litreview approve-alternate` records the researcher's
        consent for this run, agent and model (a logged human decision)."""
        limit = float((self.cfg.get("routing") or {}).get("max_cost_multiple", 1.5))
        approved = self.load("approved_alternates.json", {}).get(agent_id) or {}
        if approved.get("model") == alternate:
            return
        est = self.budget.alternate_cost_multiple(agent_id, primary, alternate)
        if est is not None and est["multiple"] <= limit:
            return
        per_call = (f" (about ${est['per_call_primary_usd']:.2f} -> ${est['per_call_alternate_usd']:.2f} per call)"
                    if est and est["per_call_primary_usd"] is not None else "")
        msg = (f"{agent_id}: {primary} {why}, and its alternate {alternate} would cost "
               + (f"{est['multiple']}x as much{per_call}, above routing.max_cost_multiple {limit}x; basis: {est['basis']}"
                  if est else "an unknown amount (unpriced)")
               + f". To accept, run:  litreview approve-alternate {self.id} {agent_id}")
        self.save("alternate_pending.json", {"agent": agent_id, "primary": primary, "alternate": alternate,
                                             "estimate": est, "limit": limit})
        notify.send("budget_warning", f"Run {self.id}: alternate for {agent_id} needs your approval", msg)
        raise Pause(msg)

    def approve_alternate(self, agent_id: str) -> dict:
        pending = self.load("alternate_pending.json")
        if not pending or pending["agent"] != agent_id:
            raise ValueError(f"no alternate for {agent_id} is waiting for approval in run {self.id}")
        approved = self.load("approved_alternates.json", {})
        approved[agent_id] = {"model": pending["alternate"], "estimate": pending["estimate"],
                              "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.save("approved_alternates.json", approved)
        self.data("alternate_pending.json").unlink()
        self.prov.human_decision("ALTERNATE_COST", {"agent": agent_id, "primary": pending["primary"],
                                                    "alternate": pending["alternate"], **(pending["estimate"] or {})},
                                 "approved routing to a costlier alternate after a refusal")
        return pending

    def _require_projection(self) -> None:
        """No agent call after CP2 without a cost projection within the cap (cost_projection.py). Spend is
        decided at CP2, where changing the selection is cheap; `litreview project RUN` re-projects."""
        stage = self.state().get("stage")
        if stage not in STAGES or STAGES.index(stage) <= STAGES.index("cp2"):
            return
        proj = self.load("cost_projection.json")
        if proj is None:
            raise Pause(f"no cost projection for this run: run `litreview project {self.id}` before any further spend")
        if proj.get("verdict") == "SUPERSEDED":
            raise Pause(f"the cost projection is superseded ({proj.get('superseded_reason')}): re-project with "
                        f"`litreview project {self.id}` before any further spend")
        if proj.get("verdict") != "WITHIN_CAP":
            raise Pause(f"cost projection ${proj.get('projected_total_usd')} exceeds the ${proj.get('cap_usd')} cap "
                        "(data/cost_projection.json): deselect papers or raise the cap, then re-project")

    def _check_worst_case_line(self, agent_id: str) -> None:
        """A WORST_CASE line of the projection is a bound, not an estimate: once an agent's spend since the
        projection exceeds its line, or the next call would exceed the line's number of calls, the projection is
        superseded and nothing more is called until the run is re-projected from actual spend."""
        stage = self.state().get("stage")
        if stage not in STAGES or STAGES.index(stage) <= STAGES.index("cp2"):
            return
        proj = self.load("cost_projection.json")
        if not proj or proj.get("verdict") != "WITHIN_CAP":
            return   # _require_projection has already stopped the call
        line = next((x for x in proj.get("lines", []) if x.get("basis") == "WORST_CASE" and x["stage"] == agent_id), None)
        if line is None:
            return
        since = [e for e in self.budget.entries() if e["agent"] == agent_id and e["time"] >= proj["created"]]
        usd = sum(e["cost_usd"] or 0 for e in since)
        reason = (f"{agent_id} has spent ${usd:.2f} since the projection, over its worst-case line "
                  f"(${line['usd']:.2f})" if usd > line["usd"] else
                  f"{agent_id} has made {len(since)} calls since the projection, all its worst-case line "
                  f"({line['calls']}) allows" if len(since) >= int(line["calls"]) else None)
        if reason:
            self._supersede_projection(f"worst-case line overrun: {reason}")
            raise Pause(f"worst-case line overrun: {reason}. Re-project with `litreview project {self.id}` "
                        "before the next call.")

    def _batch_gate(self, agent_id: str, steps: list[str], reserve_usd: float) -> dict:
        """The runtime gate before any batch (pipeline.yaml -> batch.gate_usd), recorded in provenance whatever
        the verdict. Steps held by unsettled batches are committed spend, not projected spend."""
        limit = (self.cfg.get("batch") or {}).get("gate_usd")
        if limit is None:
            raise BatchGateRefused(f"{agent_id}: batch.gate_usd is not set; no batch is submitted without the gate")
        in_flight = {s for f in self.dir.glob("data/batches/*.json")
                     for rec in json.loads(f.read_text(encoding="utf-8"))
                     if rec["status"] in ("INTENT", "SUBMITTED", "UNRESOLVED") for s in rec["steps"]}
        try:
            g = cost_projection.batch_gate(self, agent_id, steps, reserve_usd, float(limit), frozenset(in_flight))
        except FileNotFoundError as e:   # no measured rates: the rest of the run cannot be projected
            raise BatchGateRefused(f"{agent_id}: batch not submitted: the runtime gate cannot project the rest "
                                   f"of the run ({e})") from e
        self.prov.tool_run("batch_gate", agent_id, {k: v for k, v in g.items() if k != "projection_lines"})
        if g["verdict"] != "PASS":
            raise BatchGateRefused(
                f"{agent_id}: batch of {len(steps)} not submitted: spent ${g['spent_usd']:.2f} + committed "
                f"${g['committed_usd']:.2f} + projected ${g['projected_usd']:.2f} + this batch's worst case "
                f"${g['reserve_usd']:.2f} = ${g['total_usd']:.2f}, over the ${g['limit_usd']:.2f} gate. Revise "
                f"the scope and re-project (`litreview project {self.id}`); scientific checks are not cut to fit.")
        return g

    def _supersede_projection(self, reason: str) -> None:
        """Spend the projection did not plan for (a paid turn that produced nothing) makes it stale: the next
        agent call requires a new one, priced from what has actually been spent."""
        proj = self.load("cost_projection.json")
        if proj is not None:
            proj.update(verdict="SUPERSEDED", superseded_reason=reason[:300],
                        superseded_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
            self.save("cost_projection.json", proj)

    def agent(self, agent_id: str, payload: dict, step: str, overrides: dict | None = None,
              schema_file: str | None = None, exclude_providers: frozenset = frozenset(),
              reservation_key: str | None = None) -> dict:
        self._require_projection()
        self._check_worst_case_line(agent_id)
        m = self.route(agent_id, exclude_providers)
        if overrides:
            m = dataclasses.replace(m, **overrides)
        try:
            extra = {"reservation_key": reservation_key, "repair_limit": 0} if reservation_key else {}
            out = run_agent(agent_id, payload, self.dir, step, self.budget, self.prov, model=m,
                            schema_file=schema_file, **extra)
        except RefusalError as e:
            model_record.add(e.model, agent_id, self.family(), "REFUSED", self.id, step, e.category)
            raise
        model_record.add(m.model, agent_id, self.family(), "COMPLETED", self.id, step)
        self.last_model = m.model
        if self.budget.should_warn():
            notify.send("budget_warning", f"Run {self.id}: 80% of budget used", self.budget.summary_text())
        return out

    def counter(self, st: dict, key: str) -> int:
        st["counters"][key] = st["counters"].get(key, 0) + 1
        self.save_state(st)
        return st["counters"][key]

    # --- main loop -----------------------------------------------------
    def verify_source_inconsistency(self, record_id: str, statement: str, matches: str | None = None) -> None:
        """Record a researcher's verification of an inconsistency inside one paper. It reaches A07 through
        the coverage manifest and is logged as a human decision (for the AI-use disclosure)."""
        if record_id not in {r["record_id"] for r in self.load("selected_corpus.json", [])}:
            raise ValueError(f"{record_id} is not in the selected corpus")
        entry = {"record_id": record_id, "statement": statement, "matches": matches,
                 "verified_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.save("researcher_verifications.json", self.load("researcher_verifications.json", []) + [entry])
        self.prov.human_decision("SOURCE_VERIFICATION", {"record_id": record_id, "matches": matches,
                                                         "verified": True}, statement)

    def run(self, until: str | None = None) -> str:
        st = self.state()
        st["status"] = "RUNNING"
        self.save_state(st)
        try:
            self.preflight_routing()
            while st["stage"] != "done":
                if until and st["stage"] == until:
                    raise Pause(f"stopped before {until} (--until)")
                handler = getattr(self, f"stage_{st['stage']}")
                nxt = handler(st)
                st = self.state() | {"stage": nxt}
                self.save_state(st)
            st["status"] = "COMPLETE"
        except Pause as p:
            st = self.state()
            st["status"] = f"PAUSED: {p}"
        except (BudgetExceeded, UnpricedModel) as e:
            st = self.state()
            st["status"] = f"STOPPED_BUDGET: {e}"
            notify.send("failure", f"Run {self.id} stopped (budget)", f"{e}\n\n{self.budget.summary_text()}")
        except AgentError as e:
            st = self.state()
            st["status"] = f"FAILED: {e}"
            notify.send("failure", f"Run {self.id} failed", str(e))
        except publication.EvaluationOnly as e:
            st = self.state()
            st["status"] = f"REFUSED_EVALUATION_ONLY: {e}"
        self.save_state(st)
        return st["status"]

    def mark_evaluation_only(self, reason: str) -> dict:
        """Mark the run evaluation-only: every synthesis it produces is stamped in its data, and no
        publication stage accepts a stamped synthesis (publication.py). Logged as the researcher's decision."""
        st = self.state()
        st["evaluation_only"] = {"reason": reason, "marked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.save_state(st)
        for name in ("synthesis_package.json", "synthesis_approved.json"):
            doc = self.load(name)
            if doc is not None and not doc.get(publication.MARK):
                self.save(name, publication.stamp(doc, reason, self.id))
        self.prov.human_decision("evaluation_only", {"reason": reason})
        return st["evaluation_only"]

    def _publishable(self, name: str):
        """A synthesis artifact for a publication stage; refused if stamped evaluation-only."""
        return publication.refuse(self.load(name), f"{name} of run {self.id}")

    def pause_for_checkpoint(self, cp: str) -> None:
        notify.send("checkpoint", f"Run {self.id}: {cp} ready for your review",
                    f"Open runs/{self.id}/checkpoints/{cp}_review.md, record your decision, "
                    f"then run:  litreview approve {self.id} {cp}\n\n{self.budget.summary_text()}")
        raise Pause(f"waiting for {cp}")

    # ================================================================ stages
    def stage_scope(self, st: dict) -> str:
        inp = self.dir / "input"
        feedback = self.load("cp1_feedback.json")
        spec = self.agent("A02-SP", {
            "topic_statement": (inp / "topic.md").read_text(encoding="utf-8"),
            "researcher_notes": (inp / "notes.md").read_text(encoding="utf-8"),
            "seed_papers": [s for s in (inp / "seeds.txt").read_text(encoding="utf-8").splitlines() if s.strip()],
            "journal_profile": config.load("journal_scirev"),
            "theme_guidance": self.cfg.get("themes", {"primary_min": 5, "primary_max": 8}),
            "revision_feedback": feedback,
        }, step=f"A02-SP_scope_v{self.counter(st, 'scope')}")
        self.save("spec.json", spec)
        return "cp1"

    def stage_cp1(self, st: dict) -> str:
        decision = checkpoints.approved(self.dir, "CP1")
        if not decision:
            checkpoints.write_cp1(self.dir, self.load("spec.json"))
            self.pause_for_checkpoint("CP1")
        spec = self.load("spec.json")
        spec["researcher_decision"] = decision
        if decision.get("edited_selection_criteria"):
            spec["selection_criteria"] = decision["edited_selection_criteria"]
        proposed = decision.get("edited_theme_framework") or spec.get("theme_framework")
        if proposed and proposed.get("primary_themes") and not self.load("theme_framework.json"):
            fw = theme_framework.create(proposed["primary_themes"], proposed.get("count_justification", ""), "CP1")
            self.save("theme_framework.json", fw)
            self.prov.human_decision("THEME_FRAMEWORK", {"version": 1, "primary_theme_ids": sorted(theme_framework.ids(fw)),
                                                         "edited": bool(decision.get("edited_theme_framework"))},
                                     "theme framework approved at CP1")
        self.save("spec_approved.json", spec)
        return "search"

    def _framework_update(self, decision: dict, checkpoint: str) -> None:
        """A framework change approved at CP2 or CP3: a new version, logged as the researcher's decision."""
        upd = decision.get("theme_framework_update")
        fw = self.load("theme_framework.json")
        if not upd or not fw:
            return
        new = theme_framework.revise(fw, upd["primary_themes"], checkpoint, upd.get("note", ""))
        self.save("theme_framework.json", new)
        self.prov.human_decision("THEME_FRAMEWORK", {"version": new["version"], **{k: new["history"][-1][k]
                                 for k in ("added", "removed")}}, upd.get("note", ""))

    def stage_search(self, st: dict) -> str:
        spec = self.load("spec_approved.json")
        sources = enabled_sources()
        rcfg = self.cfg["retrieval"]
        budget = {"max_records_total": rcfg["max_records_total"], "max_records_per_family": rcfg["max_records_per_family"]}
        plan = self.agent("A03-LM", {"mode": "PLAN", "review_spec": spec, "sources_enabled": sources,
                                     "budget": budget}, step="A03-LM_plan")
        results = self._execute_plan(plan, sources)
        seeds = spec.get("search_seeds", {}).get("seed_papers", [])
        for i in range(int(self.cfg["loops"]["max_search_repairs"])):
            report = self._execution_report(plan, results, seeds)
            if not report["problems"]:
                break
            plan = self.agent("A03-LM", {"mode": "REPAIR", "review_spec": spec, "sources_enabled": sources,
                                         "budget": budget, "previous_plan": plan,
                                         "execution_report": report["families"],
                                         "seed_recall": report["seed_recall"]}, step=f"A03-LM_repair{i + 1}")
            results = self._execute_plan(plan, sources)
        self.save("search_plan.json", plan)
        all_records = [Record(**{k: v for k, v in r.items() if k in Record.__dataclass_fields__})
                       for res in results for r in res["records"]]
        records, stats = deduplicate(all_records)
        self.save("records.json", records)
        self.save("search_log.json", [{k: v for k, v in r.items() if k != "records"} for r in results])
        self.prov.tool_run("search+dedup", "search", stats)
        return "qualify"

    def _execute_plan(self, plan: dict, sources: dict) -> list[dict]:
        out = []
        for fam in plan.get("query_families", []):
            for src in fam.get("sources", []):
                if src not in sources or src not in fam.get("compiled", {}):
                    continue
                res = search(src, fam["compiled"][src], fam["family_id"],
                             min(int(fam.get("max_records") or 200), self.cfg["retrieval"]["max_records_per_family"]))
                out.append({"source": res.source, "family_id": res.family_id, "purpose": fam.get("purpose"),
                            "query": res.query, "hit_count": res.hit_count, "returned": len(res.records),
                            "error": res.error, "records": [r.to_dict() for r in res.records]})
        return out

    @staticmethod
    def _execution_report(plan: dict, results: list[dict], seeds: list[str]) -> dict:
        fams = []
        for r in results:
            fams.append({"family_id": r["family_id"], "source": r["source"], "query": r["query"],
                         "hit_count": r["hit_count"], "returned": r["returned"], "error": r["error"],
                         "sample_titles": [x["title"] for x in r["records"][:20]]})
        found = [x for r in results for x in r["records"]]
        recall = []
        for s in seeds:
            key = s.lower().strip()
            hit = any(key and (key == (x.get("doi") or "").lower() or key == str(x.get("pmid") or "")
                               or key[:60] in (x.get("title") or "").lower()) for x in found)
            recall.append({"seed": s, "retrieved": hit})
        problems = [f for f in fams if f["error"] or not f["returned"]] + [s for s in recall if not s["retrieved"]]
        return {"families": fams, "seed_recall": recall, "problems": problems}

    def stage_qualify(self, st: dict) -> str:
        self._qualify_pending()
        return "expand"

    def stage_expand(self, st: dict) -> str:
        """Citation expansion, one depth at a time: expand, deduplicate, qualify the new records.
        Depth 2 seeds only from depth-1 records A04-CQ qualified, so it follows relevant papers,
        not the whole citation neighbourhood."""
        ecfg = self.cfg["retrieval"].get("citation_expansion", {})
        if not ecfg.get("enabled"):
            return "cp2"
        max_depth = min(int(ecfg.get("depth", 1)), 2)
        done = st.get("expansion_depth_done", 1 if st.get("expansion_done") else 0)
        for depth in range(done + 1, max_depth + 1):
            self._qualify_pending()   # no-op unless a previous depth was interrupted mid-qualification
            records, quals = self.load("records.json"), self.load("qualifications.json", [])
            if depth == 1:
                seeds = choose_seeds(quals, records, self.load("search_plan.json", {})
                                     .get("citation_expansion_seed_families", []))
            else:
                seeds = choose_next_seeds(quals, records, depth - 1)
            already = sum(1 for r in records if r.get("expansion"))
            per_seed = int(ecfg.get("max_per_seed_depth2", ecfg.get("max_per_seed", 30)) if depth == 2
                           else ecfg.get("max_per_seed", 30))
            found, log = expand(seeds, ecfg.get("directions", ["references", "citations"]), per_seed,
                                max(int(ecfg.get("max_total", 600)) - already, 0), depth=depth)
            merged, stats = deduplicate(found, existing=records)
            self.save("records.json", merged)
            self.save("expansion_log.json", self.load("expansion_log.json", []) + log)
            self.prov.tool_run("citation_expansion", "expand", {"depth": depth, "seeds": len(seeds), **stats})
            st = self.state()
            st["expansion_depth_done"] = depth
            self.save_state(st)
            self._qualify_pending()
        return "cp2"

    def _qualify_pending(self) -> None:
        spec = self.load("spec_approved.json")
        records = self.load("records.json")
        quals: dict[str, dict] = {q["record_id"]: q for q in self.load("qualifications.json", [])}
        fw = self.load("theme_framework.json")
        todo = [r for r in records if r["record_id"] not in quals]
        size = int(self.cfg["loops"]["cq_batch_size"])
        fields = ("record_id", "title", "abstract", "authors", "year", "venue", "publication_type", "doi",
                  "pmid", "nct_id", "is_preprint", "query_family_ids", "expansion")
        for i in range(0, len(todo), size):
            batch = [{**{k: r.get(k) for k in fields},
                      "content_level": "ABSTRACT" if r.get("abstract") else "METADATA_ONLY"} for r in todo[i:i + size]]
            # numbered across resumes, so a rerun batch never overwrites an earlier batch's outputs
            bid = f"B{self.counter(self.state(), 'cq_batch'):03d}"
            out = self.agent("A04-CQ", {"review_spec": spec, "theme_framework": fw, "batch_id": bid,
                                        "records": batch}, step=f"A04-CQ_{bid}")
            got = {q["record_id"]: q for q in out.get("qualifications", [])}
            for r in batch:  # nothing may disappear: any record without a disposition is flagged
                quals[r["record_id"]] = {**(got.get(r["record_id"]) or {
                    "record_id": r["record_id"], "disposition": "UNRESOLVED_HUMAN_REVIEW",
                    "reason": "Agent returned no disposition for this record.", "themes": [], "flags": []}),
                    **self._screener()}
                quals[r["record_id"]] = theme_framework.normalize(quals[r["record_id"]], fw) \
                    if quals[r["record_id"]].get("disposition") == "QUALIFIED" else quals[r["record_id"]]
            self.save("qualifications.json", list(quals.values()))
        # Level 2: full text for records the agent could not decide from the abstract
        by_id = {r["record_id"]: r for r in records}
        need_ft = [q["record_id"] for q in quals.values() if q["disposition"] == "UNRESOLVED_FULL_TEXT_REQUIRED"
                   and not q.get("_fulltext_checked")]
        for rid in need_ft:
            sections = fetch_sections(by_id[rid].get("pmcid"))
            quals[rid]["_fulltext_checked"] = True
            if not sections:
                continue
            out = self.agent("A04-CQ", {"review_spec": spec, "batch_id": f"FT-{rid}", "records": [
                {**{k: by_id[rid].get(k) for k in fields}, "content_level": "FULL_TEXT", "sections": sections}]},
                step=f"A04-CQ_FT_{rid}")
            for q in out.get("qualifications", []):
                quals[rid] = {**q, "_fulltext_checked": True, **self._screener()}
        self.save("qualifications.json", list(quals.values()))
        self.save("bias_report.json", self._bias_report(records, list(quals.values())))

    def _screener(self) -> dict:
        return {"screened_by": self.last_model, "screening_prompt": f"A04-CQ v{prompt_version('A04-CQ')}"}

    def _bias_report(self, records: list[dict], quals: list[dict]) -> dict:
        plan = self.load("search_plan.json", {})
        purpose = {f["family_id"]: f.get("purpose") for f in plan.get("query_families", [])}
        purpose.update({"CITEXP:FWD": "CITATION_EXPANSION", "CITEXP:BWD": "CITATION_EXPANSION"})
        by_id = {r["record_id"]: r for r in records}
        tally: dict[str, dict] = defaultdict(lambda: {"received": 0, "excluded": 0})
        themes: dict[str, int] = defaultdict(int)
        for q in quals:
            for fid in by_id.get(q["record_id"], {}).get("query_family_ids", []):
                t = tally[purpose.get(fid, "UNKNOWN")]
                t["received"] += 1
                t["excluded"] += q["disposition"] == "EXCLUDED"
            if q["disposition"] == "QUALIFIED":
                for th in q.get("themes", []):
                    themes[th] += 1
        seeds = self.load("spec_approved.json", {}).get("search_seeds", {}).get("seed_papers", [])
        excluded_seeds = [q["record_id"] for q in quals if q["disposition"] == "EXCLUDED"
                          and any(s.lower() in json.dumps(by_id.get(q["record_id"], {})).lower() for s in seeds if s)]
        rates = {k: {**v, "exclusion_rate": round(v["excluded"] / v["received"], 3) if v["received"] else None}
                 for k, v in tally.items()}
        by_model: dict[str, dict] = defaultdict(lambda: {"received": 0, "excluded": 0})
        for q in quals:
            m = by_model[q.get("screened_by") or "not recorded"]
            m["received"] += 1
            m["excluded"] += q["disposition"] == "EXCLUDED"
        split = {k: {**v, "exclusion_rate": round(v["excluded"] / v["received"], 3)} for k, v in by_model.items()}
        extra = ({"exclusion_rate_by_screening_model": split,
                  "exclusion_rate_by_screening_model_caveat": checkpoints.SCREENING_SPLIT_CAVEAT}
                 if len(split) > 1 else {})
        return {"exclusion_rate_by_query_purpose": rates, **extra, "excluded_seed_records": excluded_seeds,
                "qualified_per_theme": dict(themes),
                "note": "A markedly higher exclusion rate for CONTRARY_EVIDENCE, or any excluded seed, "
                        "suggests a screening or criteria problem."}

    def stage_cp2(self, st: dict) -> str:
        decision = checkpoints.approved(self.dir, "CP2")
        if not decision:
            quals = self.load("qualifications.json")
            checkpoints.write_cp2(self.dir, self.load("records.json"), quals, self.load("bias_report.json"),
                                  emerging=theme_framework.emerging(quals, "record_id"),
                                  framework=self.load("theme_framework.json"))
            self._cp2_costs(quals)
            self.pause_for_checkpoint("CP2")
        self._framework_update(decision, "CP2")
        by_id = {r["record_id"]: r for r in self.load("records.json")}
        quals = {q["record_id"]: q for q in self.load("qualifications.json")}
        corpus = []
        for rid in decision["selected_record_ids"]:
            q = quals.get(rid, {})
            corpus.append({**by_id[rid], "role": q.get("role") or "PRIMARY", "themes": q.get("themes", []),
                           "subthemes": q.get("subthemes", []),
                           "tier": decision["tier_overrides"].get(rid) or q.get("proposed_tier"),
                           "flags": q.get("flags", []), "is_contrary_evidence": q.get("is_contrary_evidence")})
        # the projection decides here, where changing the selection is still cheap
        proj = cost_projection.for_selection(cost_projection.load_rates(), corpus, self.dir, self.budget, self.route,
                                             self.cfg)
        self.save("cost_projection.json", proj)
        self.prov.tool_run("cost_projection", "cp2", {k: proj[k] for k in ("projected_total_usd", "cap_usd", "verdict", "papers")})
        if proj["verdict"] != "WITHIN_CAP":
            raise Pause(f"CP2 selection of {len(corpus)} papers is projected at ${proj['projected_total_usd']:.2f}, over "
                        f"the ${proj['cap_usd']:.2f} cap (data/cost_projection.json). Deselect papers or raise the cap, "
                        "then approve CP2 again.")
        self.save("selected_corpus.json", corpus)
        return "extract"

    def _cp2_costs(self, quals: list[dict]) -> None:
        """Cost lines in CP2_review.md: the projection for every qualified paper, and per paper by level."""
        try:
            rates = cost_projection.load_rates()
        except FileNotFoundError as e:
            note = f"\n\n## Cost projection\n\nNot available: {e}. CP2 approval will refuse without it.\n"
        else:
            by_id = {r["record_id"]: r for r in self.load("records.json")}
            qualified = [by_id[q["record_id"]] for q in quals if q.get("disposition") == "QUALIFIED" and q["record_id"] in by_id]
            proj = cost_projection.for_selection(rates, qualified, self.dir, self.budget, self.route, self.cfg)
            per = rates["per_paper"]
            note = ("\n\n## Cost projection\n\nEach selected paper adds about "
                    f"${per['ABSTRACT']['p90_usd']:.2f} (abstract only) or ${per['FULL_TEXT']['p90_usd']:.2f} (full text) "
                    f"for extraction and validation (90th percentile, {rates['reference_run']}), plus its share of "
                    "theme validation and of the worst-case synthesis and writing stages. If every qualified paper "
                    f"were selected:\n\n```\n{cost_projection.text(proj)}\n```\n\nApproval refuses a selection "
                    "projected over the cap.\n")
        p = checkpoints.cp_dir(self.dir) / "CP2_review.md"
        p.write_text(p.read_text(encoding="utf-8") + note, encoding="utf-8")

    def run_many(self, agent_id: str, items: list[tuple[str, dict]], on_output, exclude=None) -> None:
        """Independent calls of one agent (step, payload), each output passed to on_output(step, output) as
        it arrives. An output already saved for a step is reused, never paid for twice. Agents listed under
        pipeline.yaml -> batch go through a vendor batch (batch_stage.py); the rest run one by one.
        exclude(step): vendors that item may not run on (the vendors of the work it audits)."""
        exclude = exclude or (lambda step: frozenset())
        pending = []
        for step, payload in items:
            done = self.dir / "outputs" / f"{step}.json"
            if done.exists():
                on_output(step, json.loads(done.read_text(encoding="utf-8")))
            else:
                pending.append((step, payload))
        bcfg = self.cfg.get("batch") or {}
        if pending and bcfg.get("enabled") and agent_id in (bcfg.get("agents") or []):
            BatchStage(self, agent_id, pending, on_output, exclude).run_all()
            return
        for step, payload in pending:
            on_output(step, self.agent(agent_id, payload, step, exclude_providers=frozenset(exclude(step))))

    def stage_extract(self, st: dict) -> str:
        spec = self.load("spec_approved.json")
        items, rid_of = [], {}
        for rec in self.load("selected_corpus.json"):
            rid = rec["record_id"]
            if self.data(f"extractions/{rid}.json").exists():
                continue
            sections = self.load(f"fulltext/{rid}.json") or fetch_sections(rec.get("pmcid")) \
                or {"Abstract": rec.get("abstract") or ""}
            level = "FULL_TEXT" if len(sections) > 1 else "ABSTRACT"
            self.save(f"fulltext/{rid}.json", sections)
            rid_of[f"A05-KE_{rid}"] = rid
            items.append((f"A05-KE_{rid}", {"review_spec": spec, "theme_framework": self.load("theme_framework.json"),
                                            "content_level": level, "record": {**rec, "content": sections}}))
        self.run_many("A05-KE", items, lambda step, out: self.save(
            f"extractions/{rid_of[step]}.json", self._normalize(rid_of[step], out)))
        return "validate"

    def _normalize(self, rid: str, ext: dict) -> dict:
        """Normalize a paper's entities against its own text (abbreviation expansions) and the run's conflict
        registry; conflicts found are kept in data/normalization_audit.json, never on the entity."""
        normalize_entities(ext, self.data("normalization_cache.json"), sections=self.load(f"fulltext/{rid}.json"),
                           conflicts_path=self.data("normalization_conflicts.json"), record_id=rid)
        self._audit_normalization(ext.pop("_normalization_audit", []))
        return ext

    def _audit_normalization(self, audits: list[dict]) -> None:
        if audits:
            self.save("normalization_audit.json", self.load("normalization_audit.json", []) + audits)

    def _review_items(self, rid: str) -> dict[str, dict]:
        return {i["local_id"]: i for i in self.load("validation_review.json", []) if i["record_id"] == rid}

    def _record_review(self, rid: str, items: list[dict]) -> None:
        """Replace pending reviews; retain human decisions only for the same evidence/validation version."""
        from .synthesis_registry import fingerprint
        ext = self.load(f'extractions/{rid}.json', {})
        fps = evidence.finding_fingerprints(ext)
        source = self.load(f'fulltext/{rid}.json', {})
        items = [{**i, 'validation_version':fingerprint([i.get('old_validation'),i.get('new_validation'),
                   fps.get(i['local_id']),source])} for i in items]
        versions = {i['finding_id']:i['validation_version'] for i in items}
        keep = [i for i in self.load("validation_review.json", []) if i["record_id"] != rid or
                (i.get('decision') and (i['finding_id'] not in versions or
                                       i.get('validation_version') == versions[i['finding_id']]))]
        decided = {i["finding_id"] for i in keep}
        self._write_validation("validation_review.json", keep + [i for i in items if i["finding_id"] not in decided])

    def review_revalidations(self, notes: dict[str, str] | None = None) -> list[dict]:
        """Apply the revalidation review rule to every paper revalidated in this run, against the validations
        and extractions archived before it (data/renormalization/). `notes`: reviewer notes by finding ID."""
        items = []
        for p in sorted((self.dir / "outputs").glob("A06-SV_*_reval*.json")):
            rid = p.stem.split("_")[1]
            if ".raw" in p.name or any(i["record_id"] == rid for i in items):
                continue
            old_val = self.load(f"renormalization/validations_before/{rid}.json")
            old_ext = self.load(f"renormalization/extractions_before/{rid}.json")
            if old_val is None or old_ext is None:
                continue
            new = evidence.review_changes(rid, old_val, old_ext, self.load(f"validations/{rid}.json"),
                                          self.load(f"extractions/{rid}.json"))
            for i in new:
                if (notes or {}).get(i["finding_id"]):
                    i["reviewer_note"] = notes[i["finding_id"]]
            self._record_review(rid, new)
            items += new
        findings = self._validated_findings(self.load("selected_corpus.json"))
        self.save("validated_findings.json", findings)
        self._save_held(findings)
        self.prov.tool_run("validation_review", "revalidate",
                           {"changes": len(items), "quarantined": sum(i["action"] == "QUARANTINED" for i in items)})
        return items

    def classify_review(self, finding_id: str, cause: str, note: str, by: str = "human") -> dict:
        """A classification of why two readings of a finding disagree (evidence.CAUSES). `by` says who made
        it: the researcher ("human"), or a reviewer proposing it for the researcher to confirm."""
        if cause not in evidence.CAUSES:
            raise ValueError(f"cause must be one of {', '.join(evidence.CAUSES)}")
        items = self.load("validation_review.json", [])
        item = next((i for i in items if i["finding_id"] == finding_id), None)
        if item is None:
            raise ValueError(f"{finding_id} has no recorded disagreement")
        item.update(cause=cause, cause_by=by, cause_note=note)
        self.save("validation_review.json", items)
        self.prov.human_decision("validation_review_cause", {"finding_id": finding_id, "cause": cause, "by": by,
                                                             "note": note})
        return item

    def decide_review(self, finding_id: str, decision: str, note: str, cause: str | None = None) -> dict:
        """A human's decision on a quarantined change, made against the source, the extraction and both A06
        readings: KEEP_OLD, ACCEPT_NEW, or KEEP_QUARANTINED (neither confirmed). Every decision carries the
        disagreement's cause (evidence.CAUSES). Logged as a human decision."""
        if decision not in evidence.DECISIONS:
            raise ValueError(f"decision must be one of {', '.join(evidence.DECISIONS)}")
        items = self.load("validation_review.json", [])
        item = next((i for i in items if i["finding_id"] == finding_id and i["action"] == "QUARANTINED"), None)
        if item is None:
            raise ValueError(f"{finding_id} has no quarantined change")
        if cause is None and str(item.get("cause_by") or "code").startswith("code"):
            raise ValueError(f"classify why the readings of {finding_id} disagree (cause) before deciding")
        if cause is not None:
            if cause not in evidence.CAUSES:
                raise ValueError(f"cause must be one of {', '.join(evidence.CAUSES)}")
            item.update(cause=cause, cause_by="human")
        item.update(decision=decision, decision_note=note, decided_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        self.save("validation_review.json", items)
        self.prov.human_decision("validation_review", {"finding_id": finding_id, "decision": decision,
                                                       "cause": item["cause"], "note": note})
        findings = self._validated_findings(self.load("selected_corpus.json"))
        self.save("validated_findings.json", findings)
        return item

    def _save_validation(self, rid: str, val: dict) -> None:
        """Save an A06 PER_PAPER validation. A conflict A06 reports between a code-attached identity and the
        source mention is applied here: the identity is stripped from the entity (CONFLICT), recorded in the
        audit and the run's registry, and so cannot reach any consumer. The validation then records the
        identities it was made against, so a later identity change sends the finding back for revalidation
        instead of silently keeping (or gaining) its disposition."""
        # Provider output cannot supply trusted replay/review/identity metadata.
        if isinstance(val, dict):val = {k:v for k,v in val.items() if not k.startswith('_')}
        ext = self.load(f"extractions/{rid}.json", {})
        self._require_complete_validation(rid, val, ext)
        previous = self.load(f'validations/{rid}.json')
        if previous and previous.get('_review_pending'):
            self._recover_validation_review(rid, previous)
        saved = self.load(f'a06_inputs/{rid}.json', {}).get('payload', {})
        if 'extraction' in saved and 'paper_text' in saved:
            if (evidence.finding_fingerprints(saved['extraction']) != evidence.finding_fingerprints(ext)
                    or saved['paper_text'] != self.load(f'fulltext/{rid}.json', {})):
                raise Pause(f'{rid}: A06 source input changed during validation; result not accepted')
        ents = {e.get("entity_id"): e for e in ext.get("entities", [])}
        audits = []
        for c in val.get("normalization_conflicts") or []:
            e = ents.get(c.get("entity_id"))
            if e is not None and e.get("normalization_state") == "RESOLVED":
                audits.append(normalization.conflict_entity(
                    e, "A06-SV", c.get("reason") or c.get("source_says") or "A06: identity contradicts the source mention",
                    rid, normalization._spans_for(ext, e.get("entity_id"))))
        if audits:
            normalization.register_conflicts(self.data("normalization_conflicts.json"), audits)
            self._audit_normalization(audits)
            self.save(f"extractions/{rid}.json", ext)
        val["_entity_identities"] = evidence.identity_snapshot(ext)
        val["_finding_fingerprints"] = evidence.finding_fingerprints(ext)
        from .scientific_validation import source_fingerprint
        val['_source_fingerprint'] = source_fingerprint(self.load(f'fulltext/{rid}.json', {}))
        previous = self.load(f"validations/{rid}.json")
        if previous is not None:
            # a revalidation: a changed disposition with nothing in the input to explain it is not applied
            # (evidence.review_changes); the previous extraction is the archived one if identities moved since
            prev_ext = self.load(f"renormalization/extractions_before/{rid}.json") or ext
            val['_pending_review_items'] = evidence.review_changes(rid, previous, prev_ext, val, ext)
            val['_review_pending'] = bool(val['_pending_review_items'])
        self._write_validation(f'validations/{rid}.json', val)
        self._recover_validation_review(rid, val)

    def _recover_validation_review(self, rid, val):
        if val.get('_review_pending'):
            self._record_review(rid, val['_pending_review_items'])
            val = {**val, '_review_pending':False}
            self._write_validation(f'validations/{rid}.json', val)
        return val

    def _write_validation(self, name, val):
        """Atomically install a validation or its associated source/review artifact."""
        target = self.data(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.pending')
        temporary.write_text(json.dumps(val, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, target)

    def _require_complete_validation(self, rid, val, ext):
        from .scientific_validation import require_complete
        try:require_complete(val or {}, ext, rid)
        except ValueError as exc:
            self.save(f'validation_rejections/{rid}.json', {'error':str(exc), 'response':val})
            raise Pause(f'{rid}: {exc}; validation not accepted') from exc

    def _prepare_validation(self, rid):
        ext = self.load(f'extractions/{rid}.json', {})
        sections = self.load(f'fulltext/{rid}.json', {})
        repaired = span_check.repair_findings(ext, sections)
        if repaired != ext:
            self._write_validation(f'extractions/{rid}.json', repaired)
            self.prov.tool_run('deterministic_span_repair', rid,
                {'corrections':[{'finding_id':f['finding_id'], 'history':f['span_corrections']}
                                for f in repaired.get('findings', []) if f.get('span_corrections')]})
        return repaired, sections

    def _extraction_vendor(self, rid: str, entries: list[dict] | None = None) -> str:
        """The vendor that actually produced this paper's current extraction: the provider of the last call
        logged for its extraction step (the re-extraction when one was kept). A refused call is logged before
        the alternate's, so the last call is the producer. Unknown -> stop: the vendor rule cannot be checked."""
        step = (f"A05-KE_{rid}_reextract" if (self.dir / "outputs" / f"A05-KE_{rid}_reextract.json").exists()
                else f"A05-KE_{rid}")
        calls = [e for e in (entries if entries is not None else self.budget.entries()) if e["step"] == step]
        if not calls:
            raise AgentError(f"A06-SV: cannot tell which vendor produced the extraction of {rid} (no call logged "
                             f"for {step}), so vendor separation cannot be enforced; not validating it.")
        return calls[-1]["provider"]

    def stage_validate(self, st: dict) -> str:
        spec = self.load("spec_approved.json")
        corpus = self.load("selected_corpus.json")
        max_re = int(self.cfg["loops"]["max_reextractions"])
        if max_re == 0:
            # no extract-validate loop: every paper's validation is independent (and can be batched)
            items, rid_of = [], {}
            for rec in corpus:
                rid = rec["record_id"]
                if self.data(f"validations/{rid}.json").exists():
                    continue
                ext, sections = self._prepare_validation(rid)
                # a paper re-extracted before re-extraction was turned off keeps its label (v2)
                n = 2 if (self.dir / "outputs" / f"A05-KE_{rid}_reextract.json").exists() else 1
                rid_of[f"A06-SV_{rid}_v{n}"] = rid
                payload = {"mode": "PER_PAPER", "review_spec": spec, "extraction": ext,
                           "gate1_results": span_check.check_findings(ext, sections), "paper_text": sections}
                self._save_a06_input(rid, f"A06-SV_{rid}_v{n}", payload)
                items.append((f"A06-SV_{rid}_v{n}", payload))
            entries = self.budget.entries()
            vendor = {step: frozenset({self._extraction_vendor(rid, entries)}) for step, rid in rid_of.items()}
            self.run_many("A06-SV", items, lambda step, out: self._save_validation(rid_of[step], out),
                          exclude=vendor.__getitem__)
        for rec in corpus:
            rid = rec["record_id"]
            if self.data(f"validations/{rid}.json").exists():
                continue
            sections = self.load(f"fulltext/{rid}.json")
            # resume after an interruption: a paper already re-extracted continues at its next validation
            start = 1 if (self.dir / "outputs" / f"A05-KE_{rid}_reextract.json").exists() else 0
            label_offset = start - min(start, max_re)   # keeps v2 as v2 if re-extraction was later turned off
            for attempt in range(min(start, max_re), max_re + 1):
                ext, sections = self._prepare_validation(rid)
                gate1 = span_check.check_findings(ext, sections)
                payload = {"mode": "PER_PAPER", "review_spec": spec, "extraction": ext, "gate1_results": gate1,
                           "paper_text": sections}
                step = f"A06-SV_{rid}_v{attempt + 1 + label_offset}"
                self._save_a06_input(rid, step, payload)
                val = self.agent("A06-SV", payload, step=step,
                                 exclude_providers=frozenset({self._extraction_vendor(rid)}))
                serious = [d for d in val.get("defect_reports", []) if d.get("severity") in ("CRITICAL", "MAJOR")]
                if not serious or attempt == max_re:
                    break
                try:
                    ext = self.agent("A05-KE", {"review_spec": spec,
                                                "theme_framework": self.load("theme_framework.json"),
                                                "content_level": ext.get("content_level"),
                                                "record": {**rec, "content": sections},
                                                "defects_from_previous_extraction": serious},
                                     step=f"A05-KE_{rid}_reextract")
                except AgentError as e:
                    # Re-extraction is a best-effort repair. If it fails (e.g. a very dense paper exceeds
                    # max_tokens), keep the first extraction and the A06 dispositions that already mark
                    # its defective findings, rather than stopping the run.
                    self.prov.tool_run("reextraction_failed", f"validate_{rid}",
                                       {"record_id": rid, "error": str(e)[:300],
                                        "kept": "first extraction with its A06 validation"})
                    break
                self.save(f"extractions/{rid}.json", self._normalize(rid, ext))
            self._save_validation(rid, val)
        for rec in corpus:
            rid = rec['record_id']
            self._require_complete_validation(rid, self.load(f'validations/{rid}.json'),
                                               self.load(f'extractions/{rid}.json', {}))
        self._instability_test(corpus)
        findings = self._validated_findings(corpus)
        theme_records = self._theme_pass(corpus, findings)
        self.save("validated_findings.json", findings)
        self._save_held(findings)
        self.save("theme_records.json", theme_records)
        return "synthesize"

    # --- the A06 instability test ---------------------------------------
    def _a06_conditions(self, rid: str) -> dict:
        """What an A06 PER_PAPER call of this paper runs under: prompt and model settings."""
        m = self.route("A06-SV", frozenset({self._extraction_vendor(rid)}))
        return {"system_prompt_sha256": hashlib.sha256(build_system_prompt("A06-SV").encode()).hexdigest(),
                "prompt_version": prompt_version("A06-SV"), "model": m.model, "provider": m.provider,
                "max_tokens": m.max_tokens, "temperature": m.temperature, "effort": m.effort}

    def _save_a06_input(self, rid: str, step: str, payload: dict) -> None:
        """The exact A06 PER_PAPER input, saved as the call is made. The instability test replays it as is:
        a conflict stripped or an identity corrected afterwards changes the extraction file, not this."""
        self.save(f"a06_inputs/{rid}.json", {"step": step, "payload_sha256": self._payload_sha256(payload),
                                             **self._a06_conditions(rid), "payload": payload})

    @staticmethod
    def _payload_sha256(payload: dict) -> str:
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def _replay_mismatch(self, rid: str) -> str | None:
        """The saved replay input, re-hashed now against the hash taken at the original call. A mismatch means
        the replay would not be the input the original reading saw, so that comparison is invalid."""
        saved = self.load(f"a06_inputs/{rid}.json") or {}
        now = self._payload_sha256(saved.get("payload"))
        return None if now == saved.get("payload_sha256") else (
            f"replay input hash {now[:12]} does not match the hash at the original call "
            f"{str(saved.get('payload_sha256'))[:12]}: comparison invalid")

    def _instability_test(self, corpus: list[dict]) -> None:
        """pipeline.yaml -> validation.instability_test. Every paper with a blocked finding is validated once
        more, whole paper against whole paper: the input saved at its original call is replayed unchanged
        (prompt, paper text, extraction, entity identities, Gate 1 results) under the same model settings, and
        a paper whose conditions changed since is skipped, never compared. The replay input is re-hashed against
        the hash taken at the original call, before the repeat and again before the comparison; a mismatch
        invalidates that paper's comparison (reported under `invalid`, never counted). Agreement goes to
        data/instability_test.json. A finding whose two readings give it different roles is QUARANTINED for
        human review; where the roles agree, the more cautious reading stands (evidence.compare_repeat)."""
        if not (self.cfg.get("validation") or {}).get("instability_test"):
            return
        steps, skipped, invalid = {}, {}, {}
        for rec in corpus:
            rid = rec["record_id"]
            val = self.load(f"validations/{rid}.json") or {}
            if not any(str(v.get("disposition") or "").startswith("BLOCKED") for v in val.get("validations", [])):
                continue
            saved = self.load(f"a06_inputs/{rid}.json")
            if saved is None:
                skipped[rid] = "no saved input for the original call"
                continue
            now = self._a06_conditions(rid)
            changed = [k for k, v in now.items() if saved.get(k) != v]
            if changed:
                skipped[rid] = "conditions changed since the original call: " + ", ".join(changed)
                continue
            bad = self._replay_mismatch(rid)
            if bad:
                invalid[rid] = bad
                continue
            steps[f"A06-SV_{rid}_repeat"] = (rid, saved)
        todo = [(s, saved["payload"]) for s, (rid, saved) in steps.items()
                if not self.data(f"validation_repeats/{rid}.json").exists()]   # each paper repeated once
        def accept_repeat(step, out):
            rid, saved = steps[step]
            self._require_complete_validation(rid, out, saved['payload']['extraction'])
            self._write_validation(f'validation_repeats/{rid}.json', out)
        self.run_many("A06-SV", todo, accept_repeat,
                      exclude=lambda step: frozenset({self._extraction_vendor(steps[step][0])}))
        entries = self.budget.entries()

        def how(step: str) -> dict:
            calls = [e for e in entries if e["step"] == step]
            return {"step": step, "channel": ("batch" if calls and calls[-1].get("batch_id") else
                                              "interactive" if calls else "unknown"),
                    "model": calls[-1]["model"] if calls else None,
                    "json_repair": (self.dir / "outputs" / f"{step}.raw1.txt").exists()}

        papers, rows = {}, []
        for step, (rid, saved) in steps.items():
            rep = self.load(f"validation_repeats/{rid}.json")
            if rep is None:
                continue
            bad = self._replay_mismatch(rid)   # the saved input may have changed since the repeat ran
            if bad:
                invalid[rid] = bad
                continue
            orig = self.load(f"validations/{rid}.json")
            self._require_complete_validation(rid, orig, saved['payload']['extraction'])
            self._require_complete_validation(rid, rep, saved['payload']['extraction'])
            r, review = evidence.compare_repeat(rid, orig, rep)
            self._record_review(rid, review)
            rows += r
            papers[rid] = {"original": how(saved["step"]), "repeat": how(step), "payload_sha256": saved["payload_sha256"],
                           "normalization_conflicts": [len(orig.get("normalization_conflicts") or []),
                                                       len(rep.get("normalization_conflicts") or [])],
                           "rows": r}
        report = {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "granularity": "whole paper vs whole paper",
                  "agreement": evidence.repeat_agreement(rows), "papers": papers, "skipped": skipped,
                  "invalid": invalid,
                  "by_cause": evidence.review_by_cause([i for i in self.load("validation_review.json", [])
                                                        if i.get("kind") == "REPEAT"])}
        self.save("instability_test.json", report)
        self.prov.tool_run("instability_test", "validate", {"papers": len(papers), "skipped": len(skipped),
                                                            "invalid": len(invalid), **report["agreement"]})

    def _theme_pass(self, corpus: list[dict], findings: list[dict], only: set[str] | None = None,
                    label: str = "") -> dict:
        """A06 PER_THEME over the validated findings, for every theme or only those in `only`."""
        by_theme: dict[str, list] = defaultdict(list)
        for f in findings:
            for th in f["themes"] or ["(unthemed)"]:
                by_theme[th].append(f)
        if only is not None:
            by_theme = {th: fs for th, fs in by_theme.items() if th in only}
        same_study = {r["record_id"]: [x for x in r.get("flags", []) if "SAME_STUDY" in x] for r in corpus}
        theme_records = {}
        # a theme pass audits findings from many papers: it stays off every vendor that produced any of them
        entries = self.budget.entries()
        theme_exclude = frozenset(self._extraction_vendor(r["record_id"], entries) for r in corpus) if by_theme else frozenset()
        for th, fs in by_theme.items():
            definition = next((t for t in (self.load("theme_framework.json") or {}).get("primary_themes", [])
                               if t["theme_id"] == th), None)
            theme_records[th] = self.agent("A06-SV", {"mode": "PER_THEME", "theme": th, "theme_definition": definition,
                                                      "validated_findings": fs,
                                                      "same_study_flags": same_study,
                                                      "records": [{k: r.get(k) for k in ("record_id", "authors", "year", "title")}
                                                                  for r in corpus]},
                                           step=f"A06-SV_theme_{re.sub(r'[^A-Za-z0-9]+', '_', th)[:40]}{label}",
                                           exclude_providers=theme_exclude)
            from .scientific_validation import require_theme
            try:require_theme(theme_records[th], th, fs)
            except ValueError as exc:raise Pause(str(exc)) from exc
        return theme_records

    def _validated_findings(self, corpus: list[dict]) -> list[dict]:
        """Join A05 findings with A06 dispositions into one compact list with global IDs (R0001:F3). Each
        carries its evidence `eligibility` (evidence.py): decided by the disposition alone; the status only
        says why a non-citable finding is not citable (held for correction vs rejected)."""
        out = []
        for rec in corpus:
            rid = rec["record_id"]
            ext = self.load(f"extractions/{rid}.json", {})
            val_doc = self.load(f"validations/{rid}.json", {})
            self._require_complete_validation(rid, val_doc, ext)
            val_doc = self._recover_validation_review(rid, val_doc)
            from .scientific_validation import source_fingerprint
            sections = self.load(f'fulltext/{rid}.json', {})
            gates = {g['finding_id']:g for g in span_check.check_findings(ext, sections)}
            review = self._review_items(rid)
            # the disposition, constraints and limit come from the same reading as the eligibility
            val = evidence.effective_validations(val_doc, review)
            elig = evidence.annotate_paper(ext, val_doc, review)
            stale_source = val_doc.get('_source_fingerprint') != source_fingerprint(sections)
            old_fingerprints = val_doc.get('_finding_fingerprints')
            current_fingerprints = evidence.finding_fingerprints(ext)
            for f in ext.get('findings', []):
                fid = f['finding_id']
                if not span_check.passed(gates[fid]) and elig[fid]['status'] not in ('QUARANTINED','REJECTED','REVALIDATION_REQUIRED'):
                    elig[fid] = {**elig[fid], 'status':'HELD_FOR_CORRECTION',
                                 'reason':'deterministic Gate 1 failed; source correction and revalidation required'}
                elif (((old_fingerprints or {}).get(fid) != current_fingerprints[fid] or stale_source)
                      and elig[fid]['status'] not in ('QUARANTINED','REJECTED','HELD_FOR_CORRECTION')):
                    elig[fid] = {'status':'REVALIDATION_REQUIRED', 'disposition':val.get(fid, {}).get('disposition'),
                                 'reason':'source or extracted finding changed after validation'}
            ctx = {c["context_id"]: c for c in ext.get("contexts", [])}
            for f in ext.get("findings", []):
                v = val.get(f["finding_id"], {})
                out.append({"finding_id": f"{rid}:{f['finding_id']}", "record_id": rid,
                            **self._finding_themes(f, rec),
                            # the handoff contract (handoff.py): relation, direction, hedging, attribution
                            **handoff.project(f, v, ext.get("prompt_version")),
                            "span": f.get("span"), "quantities": f.get("quantities", []),
                            "context_id": f"{rid}:{f['context_id']}" if f.get("context_id") else None,
                            "context": ctx.get(f.get("context_id"), {}).get("fields"),
                            "disposition": v.get("disposition"), "eligibility": elig.get(f["finding_id"]),
                            'provenance_gate1':{'passed':span_check.passed(gates[f['finding_id']]),
                                'checks':gates[f['finding_id']], 'source_fingerprint':source_fingerprint(sections),
                                'finding_fingerprint':current_fingerprints[f['finding_id']]},
                            'span_corrections':f.get('span_corrections', []),
                            "constraints": v.get("constraints", []),
                            "plain_language_limit": v.get("plain_language_limit"),
                            # only this finding's own subject and object, not the paper's whole entity list;
                            # identity fields only for a RESOLVED entity (a CONFLICT, AMBIGUOUS or UNRESOLVED
                            # entity is known by its source mention alone)
                            "entities": {e["entity_id"]: {**{k: e.get(k) for k in ("mention", "type",
                                                                                    "normalization_state")
                                                             if e.get(k) is not None},
                                                          **normalization.usable_identity(e)}
                                         for e in ext.get("entities", [])
                                         if e["entity_id"] in (f.get("subject_entity_id"), f.get("object_entity_id"))}})
        return out

    # --- normalization correction and revalidation -----------------------
    def renormalize(self) -> dict:
        """Re-run entity normalization over every paper with the current rules. No agent call.

        Before anything changes, each validation records the identities its A06 call saw (a validation from
        before identities were recorded is taken to have seen the extraction as it stands now) and the
        extraction and validation are archived under data/renormalization/. A finding whose identity then
        changes is REVALIDATION_REQUIRED: it is not used, and its old disposition is not kept, until A06
        revalidates it. Returns which papers need revalidation and the measured cost of their last A06 call."""
        corpus = self.load("selected_corpus.json")
        changes = {}
        for rec in corpus:
            rid = rec["record_id"]
            ext, val = self.load(f"extractions/{rid}.json"), self.load(f"validations/{rid}.json")
            if ext is None:
                continue
            if val is not None and "_entity_identities" not in val:
                val["_entity_identities"] = evidence.identity_snapshot(ext)
                self.save(f"validations/{rid}.json", val)
            for sub, doc in (("extractions_before", ext), ("validations_before", val)):
                if doc is not None and not self.data(f"renormalization/{sub}/{rid}.json").exists():
                    self.save(f"renormalization/{sub}/{rid}.json", doc)
            # changes are reported against the run as originally validated, however often this is re-run
            before = evidence.identity_snapshot(self.load(f"renormalization/extractions_before/{rid}.json") or ext)
            ext = self._normalize(rid, ext)
            self.save(f"extractions/{rid}.json", ext)
            after = evidence.identity_snapshot(ext)
            moved = {eid: {"mention": next((e.get("mention") for e in ext["entities"] if e["entity_id"] == eid), None),
                           "before": before[eid], "after": after[eid]}
                     for eid in after if before.get(eid, {}).get("normalized_id") != after[eid]["normalized_id"]
                     or before.get(eid, {}).get("normalization_state") != after[eid]["normalization_state"]}
            if moved:
                changes[rid] = moved
        findings = self._validated_findings(corpus)
        self.save("validated_findings.json", findings)
        self._save_held(findings)
        need = sorted({f["record_id"] for f in findings
                       if evidence.status_of(f) in ("REVALIDATION_REQUIRED", "HELD_FOR_CORRECTION")})
        entries = self.budget.entries()
        cost = {rid: round(next((e["cost_usd"] or 0 for e in reversed(entries)
                                 if e["step"].startswith(f"A06-SV_{rid}_")), 0.0), 4) for rid in need}
        report = {"identity_changes": changes, "eligibility": evidence.summary(findings),
                  "papers_needing_revalidation": need,
                  "revalidation_cost_estimate_usd": {"per_paper_last_a06_call": cost, "total": round(sum(cost.values()), 2)}}
        self.save("renormalization/report.json", report)
        self.prov.tool_run("renormalize", "validate", {"papers_changed": len(changes), "need": need,
                                                       "estimate_usd": report["revalidation_cost_estimate_usd"]["total"]})
        return report

    def revalidate(self, record_ids: list[str]) -> dict:
        """A fresh A06 PER_PAPER validation of each paper, against the identities now attached. Its previous
        validation stays archived for the regression report. Theme records built from the old dispositions
        are marked stale; synthesis does not start until they are rebuilt (`revalidate --themes`)."""
        corpus = {r["record_id"]: r for r in self.load("selected_corpus.json")}
        spec = self.load("spec_approved.json")
        for rid in record_ids:
            if rid not in corpus:
                raise ValueError(f"{rid} is not in the selected corpus")
            if not self.data(f"renormalization/validations_before/{rid}.json").exists():
                self.save(f"renormalization/validations_before/{rid}.json", self.load(f"validations/{rid}.json"))
            ext, sections = self._prepare_validation(rid)
            n = 1 + sum(1 for p in (self.dir / "outputs").glob(f"A06-SV_{rid}_reval*.json") if ".raw" not in p.name)
            payload = {"mode":"PER_PAPER", "review_spec":spec, "extraction":ext,
                       "gate1_results":span_check.check_findings(ext, sections), "paper_text":sections}
            step = f'A06-SV_{rid}_reval{n}'
            self._save_a06_input(rid, step, payload)
            val = self.agent('A06-SV', payload, step=step,
                             exclude_providers=frozenset({self._extraction_vendor(rid)}))
            self._save_validation(rid, val)
        findings = self._validated_findings(list(corpus.values()))
        self.save("validated_findings.json", findings)
        self._save_held(findings)
        stale = set(self.load("theme_records_stale.json", [])) | {th for f in findings if f["record_id"] in record_ids
                                                                   for th in f.get("themes") or ["(unthemed)"]}
        self.save("theme_records_stale.json", sorted(stale))
        return {"revalidated": record_ids, "eligibility": evidence.summary(findings), "themes_stale": sorted(stale)}

    def rebuild_stale_themes(self) -> list[str]:
        stale = set(self.load("theme_records_stale.json", []))
        if not stale:
            return []
        corpus = self.load("selected_corpus.json")
        records = self.load("theme_records.json", {})
        n = 1 + sum(1 for p in (self.dir / "outputs").glob("A06-SV_theme_*_reval*.json") if ".raw" not in p.name)
        records.update(self._theme_pass(corpus, self._findings(), only=stale, label=f"_reval{n}"))
        self.save("theme_records.json", records)
        self.save("theme_records_stale.json", [])
        return sorted(stale)

    def _findings(self) -> list[dict]:
        """Rebuild the evidence projection from current sources and complete A06 inputs."""
        findings = self.load("validated_findings.json")
        corpus = self.load('selected_corpus.json', [])
        if not corpus:
            if findings:raise Pause('cannot authorize cached evidence without selected source extractions')
            return findings
        if any(self.load(f"extractions/{r['record_id']}.json") is None for r in corpus):
            raise Pause('cannot authorize cached evidence without selected source extractions')
        fresh = self._validated_findings(corpus)
        if fresh != findings:
            self.save('validated_findings.json', fresh)
            self._save_held(fresh)
        return fresh

    def _save_held(self, findings: list[dict]) -> None:
        """Findings held for correction (a code-attached identity contradicts the source), kept recoverable:
        they are not cited until the identity is corrected and the paper revalidated."""
        held = [{"finding_id": f["finding_id"], **(f.get("eligibility") or {})}
                for f in findings if (f.get("eligibility") or {}).get("status") == "HELD_FOR_CORRECTION"]
        self.save("held_for_correction.json", held)

    def _consolidate_themes(self, findings: list[dict], theme_records: dict) -> tuple[list[dict], dict]:
        """String-level merge of theme labels (tools/themes.py). Findings keep their original labels in
        `themes_original`, merged theme records list what they were merged from, and the mapping is logged."""
        counts: dict[str, int] = defaultdict(int)
        for f in findings:
            for th in f.get("themes") or []:
                counts[th] += 1
        for th in theme_records:
            counts.setdefault(th, 0)
        mapping, summary = themes.consolidate(dict(counts), int(self.cfg.get("synthesis", {}).get("theme_merge_max", 40)))
        self.save("theme_consolidation.json", {**summary, "mapping": mapping})
        self.prov.tool_run("theme_consolidation", "synthesize", summary)
        if not summary["applied"]:
            return findings, theme_records
        findings = [{**f, "themes_original": f.get("themes"),
                     "themes": sorted({mapping.get(t, t) for t in f.get("themes") or []})} for f in findings]
        merged: dict[str, dict] = {}
        for th, rec in theme_records.items():
            m = merged.setdefault(mapping.get(th, th), {"merged_from": [], "records": {}})
            m["merged_from"].append(th)
            m["records"][th] = rec
        return findings, merged

    def _finding_themes(self, f: dict, rec: dict) -> dict:
        """A finding's primary theme and subthemes. A finding that fits no primary theme is attached to its
        record's primary theme and flagged as emerging, for the researcher at Checkpoint 3."""
        base = {"themes": f.get("themes") or rec.get("themes", []), "primary_theme_id": f.get("primary_theme_id"),
                "subthemes": f.get("subthemes") or [], "emerging": bool(f.get("emerging")),
                "emerging_note": f.get("emerging_note")}
        fw = self.load("theme_framework.json")
        if not fw:
            return base
        out = theme_framework.normalize(base, fw)
        if not out["themes"]:
            out["themes"] = rec.get("themes", [])
            out["primary_theme_id"] = (rec.get("themes") or [None])[0]
        return out

    def stage_synthesize(self, st: dict) -> str:
        """Bounded registry-backed A07 with a human alignment stop before detailed synthesis."""
        from .synthesis_registry import EvidenceRegistry, fingerprint, offline_tokens
        from .synthesis_bounded import RegistrySynthesisJob, AlignmentRequired
        from .paths import SCHEMAS_DIR
        corpus = self.load("selected_corpus.json")
        if self.load("theme_records_stale.json", []):
            raise Pause("theme records are stale; rebuild them before synthesis")
        findings = self._findings()
        if not (self.load("theme_framework.json") or {}).get("primary_themes"):
            raise Pause("A07 requires a researcher-approved primary theme framework before planning")
        problems = handoff.contract_problems(findings)
        if problems:
            raise Pause("A07 handoff contract: " + "; ".join(problems[:5]))
        manifest = synthesis_input.build_manifest(corpus, self.load("theme_records.json"), self._inconsistency_items(corpus))
        self.save("coverage_manifest.json", manifest)
        frozen = synthesis_input.build_corpus(self.load("spec_approved.json"), corpus, findings,
                                              self.load("theme_records.json"), manifest, self.load("theme_framework.json"))
        # Registry retains full evidence and source identifiers. No A05/A06 scientific rule changes.
        frozen["selected_corpus"] = corpus
        frozen["source_entities"] = {}
        for rec in corpus:
            ext = self.load(f"extractions/{rec['record_id']}.json", {})
            registration = (ext.get("study_profile") or {}).get("registration_id")
            if registration and not rec.get("nct_id"):
                rec["registration_id"] = registration
            for ent in ext.get("entities", []):
                frozen["source_entities"][f"{rec['record_id']}:{ent['entity_id']}"] = {
                    k: ent.get(k) for k in ("mention", "type", "subtype", "molecule_species", "measured_at", "identity_relation", "construct")}
        frozen["validated_findings"] = [{k: v for k, v in f.items() if k != "context"} for f in findings]
        frozen["revision_feedback"] = self.load("cp3_feedback.json")
        registry = EvidenceRegistry(frozen)
        scfg = self.cfg["synthesis"]
        identity = {"prompt": build_system_prompt("A07-SYN"),
                    "schemas": {p.name: p.read_text(encoding="utf-8") for p in sorted(SCHEMAS_DIR.glob("A07-SYN*.json"))},
                    "model": dataclasses.asdict(self.route("A07-SYN")), "pricing": self.budget.prices}
        tag = fingerprint({"corpus": registry.digest, "execution": identity, "settings": scfg})[:16]
        system = build_system_prompt("A07-SYN")

        def count(payload):
            return offline_tokens(system) + offline_tokens(user_parts(payload))

        def call(mode, payload, name):
            limit = int(scfg["output_limits"][mode])
            tokens = count(payload)
            if tokens + limit > scfg["context_ceiling_tokens"]:
                raise JobStopped("A07 context admission refused before dispatch")
            m = self.route("A07-SYN")
            # No cache hit assumed. Charge the entire prefix as a 1h write for a conservative bound.
            usd = self.budget.cost(m.model, 0, limit, 0, 0, tokens)
            if usd is None:
                raise UnpricedModel(m.model)
            key = f"a07-{tag}-{name}"
            if key in self.budget.reservations():
                raise Pause("unsettled A07 call reservation: reconcile provider usage before retrying " + key)
            ok, available = self.budget.reserve(key, usd, "A07-SYN", "bounded synthesis pre-call reservation")
            if not ok:
                raise BudgetExceeded(f"A07 call reserves ${usd:.2f}; only ${available:.2f} remains")
            try:
                out = self.agent("A07-SYN", payload, step=f"A07-SYN_job{tag}_{name}",
                                 overrides={"cache_system": True, "cache_payload": (), "cache_ttl": scfg.get("cache_ttl", "1h"),
                                            "max_tokens": limit},
                                 schema_file=f"A07-SYN.bounded-{mode.lower()}.schema.json", reservation_key=key)
            except AgentError as exc:
                # Known responses are logged, including refusal/truncation; unknown API billing stays held.
                if any(e["step"] == f"A07-SYN_job{tag}_{name}" for e in self.budget.entries()):
                    self.budget.release(key)
                raise
            except (Pause, BudgetExceeded, UnpricedModel):
                self.budget.release(key)
                raise
            self.budget.release(key)
            return out

        def approve(digest, alignment):
            decision = checkpoints.approved(self.dir, "CP_SYN")
            if decision and decision.get("fingerprint") == digest and decision.get("approve_alignment") is True:
                return True
            checkpoints.write_synthesis_alignment(self.dir, digest, alignment)
            return False

        job = RegistrySynthesisJob(self.dir / "data" / f"synthesis_job_{tag}", registry, call, count, scfg,
                                   identity, approve, served_by=lambda: self.last_model)
        try:
            pkg = job.run()
        except AlignmentRequired as exc:
            self.save(f"synthesis_job_{tag}/report.json", self._job_report(tag, job.assemble()))
            raise Pause(str(exc)) from exc
        except JobStopped as exc:
            self.save(f"synthesis_job_{tag}/report.json", self._job_report(tag, job.assemble()))
            self._supersede_projection(f"A07 stopped: {exc}")
            raise Pause(f"A07 stopped: {exc}; inspect the report and re-project before resuming") from exc
        if pkg["status"] != "COMPLETE":
            raise Pause("incomplete synthesis cannot proceed to CP3")
        report = self._job_report(tag, pkg)
        ev = self.state().get("evaluation_only")
        if ev:
            pkg = publication.stamp(pkg, ev["reason"], self.id)
            report = publication.stamp(report, ev["reason"], self.id)
        self.save(f"synthesis_job_{tag}/report.json", report)
        self.save("synthesis_package.json", pkg)
        self.prov.tool_run("synthesis_job", f"A07-SYN_job{tag}",
                           {"models": pkg["models"], "models_by_turn": pkg["models_by_turn"], "identity": tag})
        return "cp3"

    def _provenance_summary(self) -> dict:
        """The source for the AI-use disclosure. Names every model that produced output, per agent, and
        flags agents whose output came from more than one model (an alternate after a refusal): a review
        whose synthesis came from two models is a different artifact and must say so."""
        ev = self.prov.events()
        by_agent: dict[str, dict[str, int]] = {}
        for e in ev:
            if e["type"] == "agent_call" and e["status"] not in ("FAILED", "REFUSED"):
                m = by_agent.setdefault(e["agent"], {})
                m[e["model"]] = m.get(e["model"], 0) + 1
        jobs = [e["summary"] for e in ev if e["type"] == "tool_run" and e["tool"] == "synthesis_job"]
        return {"agent_calls": sum(e["type"] == "agent_call" for e in ev),
                "models_by_agent": by_agent,
                "mixed_model_agents": sorted(a for a, m in by_agent.items() if len(m) > 1),
                "synthesis_models_by_turn": jobs[-1]["models_by_turn"] if jobs else None,
                "refusals": [{"agent": e["agent"], "model": e["model"], "step": e["step"]}
                             for e in ev if e["type"] == "agent_call" and e["status"] == "REFUSED"],
                "human_decisions": [e for e in ev if e["type"] == "human_decision"],
                "a10_detail_rounds": self._a10_detail_report(),
                "verification_statement": self.load("rv_final.json", {}).get("verification_statement")}

    def _job_report(self, tag: str, pkg: dict) -> dict:
        """Totals across the job's calls, from the cost log, plus the ledger's counts."""
        calls = [e for e in self.budget.entries() if e["step"].startswith(f"A07-SYN_job{tag}_")]
        cached = [e for e in calls if e.get("cache")]
        return {
            "calls": len(calls),
            "output_tokens_total": sum(e["output_tokens"] for e in calls),
            "input_tokens_uncached": sum(e["input_tokens"] for e in calls),
            "cache_read_tokens": sum(e.get("cached_input_tokens", 0) for e in calls),
            "cache_write_tokens": sum(e.get("cache_write_tokens", 0) + e.get("cache_write_1h_tokens", 0) for e in calls),
            "cache_hit_rate": round(sum(e["cache"]["hit"] for e in cached) / len(cached), 3) if cached else None,
            "start_to_start_seconds": [e["cache"].get("seconds_since_previous_start") for e in cached],
            "cost_usd": round(sum(e["cost_usd"] or 0 for e in calls), 4),
            "models": pkg.get("models"),
            "models_by_turn": pkg.get("models_by_turn"),
            "status": pkg.get("status"),
            **pkg.get("job_stats", {}),
            "coverage_incomplete_item_ids": pkg.get("coverage_incomplete_item_ids"),
            "findings_unaccounted": len(pkg.get("findings_unaccounted") or []),
        }

    # Free-text A06 warnings that describe a contradiction inside the paper (validations written
    # before A06-SV v0.2 added the structured `source_inconsistencies` field).
    _INCONSISTENCY_RE = re.compile(r"inconsisten|discrepan|contradict|whereas|conflicts? with|does not match",
                                   re.IGNORECASE)

    # Findings with these A06 dispositions can feed synthesis; the others (DOES_NOT_ESTABLISH, BLOCKED_*,
    # HUMAN_REVIEW_REQUIRED, UNRESOLVED_SOURCE_ACCESS) cannot, so the review does not build on them.
    _USABLE = evidence.USABLE

    @classmethod
    def _inconsistency_visibility(cls, item: dict, rec: dict, usable: set[str]) -> tuple[str, str]:
        """NARRATIVE: researcher-verified, or it names a usable finding of a CORE or contrary-evidence paper.
        An item with no finding IDs cannot be placed beside the finding it qualifies, which is what NARRATIVE
        visibility is for, so it is at most DISPLAY (a note under the evidence table), as is a named
        usable finding the review cites but does not build on. SUPPLEMENTARY: everything else.
        The full list is kept in data/inconsistencies.json."""
        if item.get("researcher_verified"):
            return "NARRATIVE", "researcher-verified"
        ids = item.get("finding_ids") or []
        if not ids:
            return (("DISPLAY", "paper-level (no finding IDs): cannot be placed beside a finding") if usable
                    else ("SUPPLEMENTARY", "paper-level (no finding IDs); paper has no usable findings"))
        if not [f for f in ids if f in usable]:
            return "SUPPLEMENTARY", "affected findings are not used (not supported by A06)"
        if rec.get("tier") == "CORE" or rec.get("is_contrary_evidence"):
            kind = "contrary-evidence" if rec.get("is_contrary_evidence") else "CORE"
            return "NARRATIVE", f"names a usable finding of a {kind} paper"
        return "DISPLAY", f"names a usable finding of a {rec.get('tier') or 'non-CORE'} paper"

    def _inconsistency_items(self, corpus: list[dict]) -> list[dict]:
        """Coverage items for contradictions inside individual papers: A05 `in_paper_conflicts` and A06
        source inconsistencies, each with a required visibility from `_inconsistency_visibility`.
        A researcher verification (`litreview verify`) marks the matching item as verified."""
        verified = self.load("researcher_verifications.json", [])
        items = []
        for rec in corpus:
            rid = rec["record_id"]
            ext = self.load(f"extractions/{rid}.json", {})
            val = self.load(f"validations/{rid}.json", {})
            usable = {v["finding_id"] for v in val.get("validations", []) if v.get("disposition") in self._USABLE}
            found = [{"kind": "IN_PAPER_CONFLICT", "source": "A05-KE in_paper_conflicts",
                      "description": c.get("description"), "finding_ids": c.get("finding_ids", [])}
                     for c in ext.get("in_paper_conflicts") or []]
            if "source_inconsistencies" in val:
                found += [{"kind": "SOURCE_INCONSISTENCY", "source": "A06-SV source_inconsistencies", **s}
                          for s in val.get("source_inconsistencies") or []]
            else:
                found += [{"kind": "SOURCE_INCONSISTENCY", "source": "A06-SV warning (free text)", "description": w}
                          for w in val.get("warnings") or [] if self._INCONSISTENCY_RE.search(w)]
            mine = [v for v in verified if v["record_id"] == rid]
            for v in mine:
                hit = next((f for f in found if v.get("matches") and v["matches"].lower()
                            in (f.get("description") or "").lower()), None)
                if hit is None:   # the researcher found something no agent recorded
                    hit = {"kind": "SOURCE_INCONSISTENCY", "source": "RESEARCHER", "description": v["statement"]}
                    found.append(hit)
                hit.update(researcher_verified=True, researcher_statement=v["statement"])
            for i, f in enumerate(found, 1):
                visibility, reason = self._inconsistency_visibility(f, rec, usable)
                items.append({"item_id": f"INCONSISTENCY:{rid}:{i}", "record_id": rid, **f,
                              "researcher_verified": f.get("researcher_verified", False),
                              "required_visibility": visibility, "visibility_reason": reason})
        self.save("inconsistencies.json", items)   # the full record, whatever reaches the text
        return items

    def stage_cp3(self, st: dict) -> str:
        decision = checkpoints.approved(self.dir, "CP3")
        if not decision:
            pkg = self._publishable("synthesis_package.json")
            checkpoints.write_cp3(self.dir, pkg,
                                  emerging=theme_framework.emerging(self.load("validated_findings.json", []), "finding_id"),
                                  framework=self.load("theme_framework.json"))
            self.pause_for_checkpoint("CP3")
        self._framework_update(decision, "CP3")
        pkg = self._publishable("synthesis_package.json")
        if pkg.get("status") != "COMPLETE" or pkg.get("coverage_incomplete_item_ids") or pkg.get("findings_unaccounted"):
            raise Pause("incomplete synthesis cannot proceed to A08")
        from .scientific_validation import require_package
        try:require_package(pkg, self._findings() or [])
        except ValueError as exc:raise Pause(str(exc)) from exc
        from .synthesis_registry import fingerprint
        if decision.get('synthesis_fingerprint') != fingerprint(pkg):
            raise Pause('CP3 approval is stale; review current synthesis package')
        pkg["researcher_decision"] = decision
        adopted = set(decision.get("adopted_interpretations", []))
        pkg["author_interpretations"] = [{**p, "type": "AUTHOR_INTERPRETATION", "id": p["pi_id"].replace("PI", "AI")}
                                         for p in pkg.get("proposed_interpretations", []) if p.get("pi_id") in adopted]
        pkg["proposed_interpretations"] = []  # unadopted proposals do not exist downstream
        self.save("synthesis_approved.json", pkg)
        return "outline"

    def stage_outline(self, st: dict) -> str:
        """A08 plans from the bridge's compact inputs (argument map, element index, table coverage), never the full
        package. The single comparative table is built by code first, so A08 knows what it already shows. The plan
        and its allocation ledger are checked by code (bridge.validate_plan; no repair loop), then held for the
        researcher's approval of the ledger (CP_LEDGER) when bridge.ledger_approval is on."""
        from . import bridge
        from .admission import AdmissionRefused
        from .synthesis_registry import fingerprint
        self._reproject("outline")
        pkg, findings, corpus = self._bridge_inputs()
        bcfg, journal = self._bridge_cfg(), config.load("journal_scirev")
        try:
            table = bridge.comparative_table(pkg, findings, corpus, int(bcfg.get("table_max_rows", 25)))
        except bridge.BridgeError as exc:
            raise Pause(f"comparative table: {exc}") from exc
        table["inconsistency_notes"] = display_items.inconsistency_notes(table, self.load("inconsistencies.json", []), corpus)
        basis = {"package": fingerprint(pkg), "evidence": bridge.evidence_version(pkg, findings), "table": fingerprint(table)}
        check = self.load("bridge/plan_check.json") or {}
        plan, ledger = self.load("manuscript_plan.json"), self.load("allocation_ledger.json")
        reuse = (plan is not None and ledger is not None and check.get("basis") == basis and not check.get("problems")
                 and check.get("plan_version") == bridge.plan_version(plan, ledger))
        if not reuse:
            payload = bridge.outline_payload(pkg, corpus, journal, table, bcfg)
            try:
                out = self._admitted("A08-OL", payload, step=f"A08-OL_v{self.counter(st, 'outline')}")
            except AdmissionRefused as exc:
                raise Pause(f"A08 request not admitted: {exc}. The outline is one request (it is not subdivided); "
                            "nothing is dropped to make it fit") from exc
            ledger = out.pop("allocation_ledger", None) or []
            plan = out
            self.save("manuscript_plan.json", plan)
            self.save("allocation_ledger.json", ledger)
            if plan.get("status") == "NEEDS_HUMAN_INPUT":
                raise Pause("A08-OL needs input (see data/manuscript_plan.json warnings); "
                            "adjust the selection or plan, then run again")
            problems, report = bridge.validate_plan(plan, ledger, pkg, corpus, table, journal, bcfg)
            check = {"basis": basis, "plan_version": bridge.plan_version(plan, ledger), "problems": problems,
                     "report": report}
            self.save("bridge/plan_check.json", check)
            self.prov.tool_run("plan_check", "outline", {"problems": len(problems), "counts": report["counts"],
                                                         "theme_to_sections": report["theme_to_sections"]})
            if problems:
                raise Pause(f"A08 plan rejected by the bridge ({len(problems)} problems; first: {problems[0]}). "
                            "See data/bridge/plan_check.json; rerun the outline stage")
        self._save_comparative_table(table)
        self.save("bridge/argument_map.json", bridge.argument_map(pkg, corpus))
        if bcfg.get("ledger_approval", True):
            self._ledger_approved(plan, ledger, check["report"], pkg, corpus, table)
        return "draft"

    def _save_comparative_table(self, table: dict) -> None:
        out_dir = self.dir / "data" / "display_items"
        if out_dir.exists():
            shutil.rmtree(out_dir)   # one display item: the comparative table replaces anything built before
        out_dir.mkdir(parents=True)
        display_items._write_csv(out_dir / "T1.csv", table["columns"], table["rows"])
        (out_dir / "T1.json").write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
        self.save("display_items.json", [table])
        self.prov.tool_run("display_items", "outline", {"T1": table["status"], "rows": len(table["rows"]),
                                                        "contrary_findings": len(table["contrary_finding_ids"]),
                                                        "contrary_findings_not_shown": table["contrary_findings_not_shown"],
                                                        "eligible_findings_not_shown": table["eligible_findings_not_shown"]})

    def _build_display_items(self, plan: dict) -> list[dict]:
        """Tables and the evidence map from validated findings (code only; A08-OL supplies no values)."""
        out_dir = self.dir / "data" / "display_items"
        if out_dir.exists():
            shutil.rmtree(out_dir)   # a new plan replaces every item
        incons = self.load("inconsistencies.json", [])
        built = display_items.build_all(plan, self._publishable("synthesis_approved.json"),
                                        self._findings() or [],
                                        self.load("selected_corpus.json", []), out_dir, incons)
        self.save("display_items.json", built)
        placed = {n["item_id"] for d in built for n in d.get("inconsistency_notes", [])}
        unplaced = [i["item_id"] for i in incons if i.get("required_visibility") == "DISPLAY" and i["item_id"] not in placed]
        self.prov.tool_run("display_items", "outline",
                           {**{d["display_id"]: d["status"] for d in built},
                            "display_inconsistencies_unplaced": unplaced})
        return built

    def _built_tables(self) -> list[dict]:
        built = self.load("display_items.json")
        if built is None:   # runs outlined before the builder existed
            built = self._build_display_items(self.load("manuscript_plan.json", {}))
        return sorted((d for d in built if d.get("kind") == "TABLE"), key=lambda d: int(d["display_id"][1:]))

    # --- writing and review ------------------------------------------
    def _verify(self, manuscript: dict, pass_: str, step: str, changed: list | None = None) -> dict:
        """Bounded occurrence verification; A07 registry remains the evidence authority."""
        from .verification_job import VerificationJob
        from .synthesis_registry import fingerprint, offline_tokens
        from .synthesis_job import JobStopped
        plan, pkg = self.load("manuscript_plan.json", {}), self._publishable("synthesis_approved.json")
        registry = self._verification_registry(pkg)
        prose = self._prose_vendors("A10-RV")
        cfg = self.cfg['scientific_verification']
        system = build_system_prompt('A10-RV')
        count = lambda p: offline_tokens(system)+offline_tokens(user_parts(p))
        execution = {'model':dataclasses.asdict(self.route('A10-RV',prose)), 'prices':self.budget.prices,
                     'prompt':system,'schema':(SCHEMAS_DIR/'A10-RV.bounded.schema.json').read_text()}
        def call(mode, payload, name):
            cap = cfg['output_limits'][mode]
            model = self.route('A10-RV',prose)
            # No hit assumed; reserve all input at the configured cache-write rate.
            usd = self.budget.cost(model.model,0,cap,0,count(payload))
            if usd is None:raise UnpricedModel(model.model)
            key = 'a10-'+fingerprint([execution,mode,payload])[:32]
            if key in self.budget.reservations():raise Pause('unsettled A10 reservation: reconcile provider billing before retry '+key)
            if not self.budget.reserve(key,usd,'A10-RV','bounded verification pre-call reservation')[0]:
                raise BudgetExceeded('A10 request exceeds remaining budget')
            dispatch = step+'_'+key+'_'+name
            try:
                out = self.agent('A10-RV',payload,step=dispatch,exclude_providers=prose,
                    overrides={'max_tokens':cap,'cache_payload':()},schema_file='A10-RV.bounded.schema.json',reservation_key=key)
            except AgentError:
                if any(e['step']==dispatch for e in self.budget.entries()):self.budget.release(key)
                raise
            except (Pause,BudgetExceeded,UnpricedModel):
                self.budget.release(key);raise
            self.budget.release(key)
            return out
        tables = self.load('display_items.json', [])
        from .verification_job import version
        digest = fingerprint([version(manuscript,plan,pkg,registry,tables),execution,cfg])[:24]
        job = VerificationJob(self.data('verification_jobs')/digest,manuscript,plan,pkg,registry,tables,
            cfg,call,count,execution,cache_directory=self.data('verification_cache'),prior_report=self.load('rv_latest.json',{}))
        try:rv = job.run(pass_)
        except (JobStopped,AgentError) as exc:
            self.save('verification_jobs/'+digest+'/report.json',{
                'verification_execution':'INCOMPLETE','verification_fingerprint':job.digest,
                'error':str(exc),'occurrence_inventory':job.occurrences,'request_metrics':job.metrics})
            self._supersede_projection('A10 stopped: '+str(exc))
            raise Pause('A10 verification incomplete: '+str(exc)) from exc
        self.prov.tool_run('bounded_verification',step,{'fingerprint':rv['verification_fingerprint'],
            'coverage':rv['coverage'],'calls_this_execution':len(job.metrics),'execution':job.identity})
        self.save('verification_jobs/'+digest+'/report.json',rv)
        return rv

    def _verification_registry(self, pkg):
        from .synthesis_registry import EvidenceRegistry
        from .synthesis_input import build_corpus
        if not pkg:raise Pause('approved synthesis missing for A10 verification')
        if (pkg.get('status', 'COMPLETE') != 'COMPLETE' or pkg.get('coverage_incomplete_item_ids')
                or pkg.get('findings_unaccounted')):
            raise Pause('incomplete synthesis cannot proceed to A10 verification')
        findings = self._findings()
        if pkg.get('registry_fingerprint'):
            from .scientific_validation import require_package
            try:require_package(pkg, findings or [])
            except ValueError as exc:raise Pause(str(exc)) from exc
            for path in (self.dir/'data').glob('synthesis_job_*/registry.json'):
                registry = EvidenceRegistry(json.loads(path.read_text(encoding='utf-8')))
                if registry.digest == pkg['registry_fingerprint']:
                    if registry.findings != {f['finding_id']:{k:v for k,v in f.items() if k!='context'} for f in findings}:
                        raise Pause('approved A07 registry is stale relative to current A06 findings')
                    if any(f.get('context') != registry.contexts.get(f.get('context_id')) for f in findings if f.get('context_id')):
                        raise Pause('approved A07 contexts changed; upstream synthesis review required')
                    for rec in self.load('selected_corpus.json',[]):
                        source=registry.records.get(rec['record_id'],{})
                        if any(rec.get(k)!=source.get(k) for k in ('title','authors','year','venue','doi','pmid') if k in rec):
                            raise Pause('approved A07 source citation metadata changed')
                    extractions={}
                    for key,attrs in registry.corpus.get('source_entities',{}).items():
                        rid,eid=key.split(':',1)
                        if rid not in extractions:extractions[rid]=self.load('extractions/'+rid+'.json')
                        ext=extractions[rid]
                        if ext:
                            ent=next((e for e in ext.get('entities',[]) if e['entity_id']==eid),{})
                            if any(ent.get(k)!=v for k,v in attrs.items()):
                                raise Pause('approved A07 molecular source identity changed')
                    return registry
            raise Pause('approved A07 registry snapshot is missing; cannot verify from an unproven replacement')
        # Legacy artifacts: an in-memory view of the same validated records, never a new evidence DB.
        records = self.load('selected_corpus.json', []) or [{'record_id':r} for r in sorted({f['record_id'] for f in findings})]
        frozen = build_corpus({},records,findings,self.load('theme_records.json',{}),[],pkg.get('theme_framework'))
        frozen['selected_corpus'] = records
        frozen['validated_findings'] = [{k:v for k,v in f.items() if k!='context'} for f in findings]
        frozen['source_entities'] = {}
        for r in records:
            for ent in self.load('extractions/'+r['record_id']+'.json',{}).get('entities',[]):
                frozen['source_entities'][r['record_id']+':'+ent['entity_id']] = ent
        return EvidenceRegistry(frozen)

    def _verification_current(self, report, manuscript):
        from .verification_job import current, version, policy_hash
        pkg = self._publishable('synthesis_approved.json')
        registry = self._verification_registry(pkg)
        digest = version(manuscript,self.load('manuscript_plan.json',{}),pkg,registry,self.load('display_items.json',[]))
        expected = set(registry.findings) | {p['proposition_id'] for p in pkg.get('propositions', [])}
        expected |= {g['gap_id'] for g in pkg.get('knowledge_gaps', [])}
        expected |= {'RECONCILIATION:'+str(n) for n,_ in enumerate(pkg.get('reconciliation', []))}
        return (current(report,digest,policy_hash(self.cfg['scientific_verification']))
                and set(report.get('global_index_ids_reviewed', [])) == expected)

    def _a10_detail_report(self) -> dict | None:
        return verification_scope.detail_report(self.prov.events(), self.budget.entries())

    def _prose_vendors(self, reader: str) -> frozenset:
        """Vendors that actually produced the manuscript `reader` (A10-RV verifies it, A11-RC critiques it) is
        about to read: the producer (last call logged) of every A09-WRI and A12-EDI step of this run that
        produced output. Every draft and edit is in the manuscript's lineage, so all count. Checked before
        each call, not only in the configuration. Unknown -> stop: the vendor rule cannot be checked."""
        last: dict[str, str] = {}
        for e in self.budget.entries():
            if e["agent"] in ("A09-WRI", "A12-EDI"):
                last[e["step"]] = e["provider"]
        produced = {p for s, p in last.items() if (self.dir / "outputs" / f"{s}.json").exists()}
        if not produced:
            raise AgentError(f"{reader}: cannot tell which vendor produced the manuscript (no A09-WRI or A12-EDI "
                             "output with a logged call), so vendor separation cannot be enforced; not running.")
        return frozenset(produced)

    def _maybe_verify(self, manuscript: dict, pass_: str, step: str, previous: dict,
                      changed: list | None = None) -> dict:
        """Reuse an exact current report; otherwise selectively reverify through the local cache."""
        if self._verification_current(previous,manuscript):return previous
        return self._verify(manuscript, pass_, step, changed)

    def _deterministic_report(self, m: dict) -> dict:
        plan = self.load("manuscript_plan.json", {})
        known = {i["item_id"] for s in plan.get("sections", []) for i in s.get("ordered_items", [])} | {"ORG"}
        selected = {r["record_id"] for r in self.load("selected_corpus.json", [])}
        text = "\n".join(s.get("text_markdown", "") for s in m.get("sections", []))
        binds = tags.bindings(text)
        built = self.load("display_items.json", [])
        placed = {n["item_id"] for d in built for n in d.get("inconsistency_notes", [])}
        cited = tags.cited_records(text) + tags.cited_records(
            " ".join(c for d in built if d.get("kind") == "TABLE" for row in d.get("rows", []) for c in row))
        return {
            "display_item_warnings": {d["display_id"]: d.get("warnings") for d in built if d.get("warnings")},
            "display_inconsistencies_not_in_any_table": [
                i["item_id"] for i in self.load("inconsistencies.json", [])
                if i.get("required_visibility") == "DISPLAY" and i["item_id"] not in placed],
            "untagged_sentences": [s for s, ids in binds if not ids and len(s.split()) > 3][:50],
            "unknown_tags": sorted({i for _, ids in binds for i in ids if i not in known}),
            "plan_items_not_rendered": sorted(known - {i for _, ids in binds for i in ids} - {"ORG"}),
            "citations_not_in_corpus": sorted(set(cited) - selected),
            "selected_papers_not_cited": sorted(selected - set(cited)),
            "compliance": compliance.check({**m, "references": cited,
                                            "display_items": plan.get("display_items", [])}),
        }

    def _save_manuscript(self, m: dict, label: str) -> None:
        self.save(f"manuscripts/{label}.json", m)
        st = self.state()
        st["current_manuscript"] = label
        self.save_state(st)

    def _current(self) -> dict:
        return self.load(f"manuscripts/{self.state()['current_manuscript']}.json")

    # --- the bridge: admission, gates and fingerprints for A08, A09, A11 and A12 -----------------------------
    def _bridge_cfg(self) -> dict:
        return self.cfg.get("bridge") or {}

    def _bridge_inputs(self) -> tuple[dict, list[dict], list[dict]]:
        pkg = self._publishable("synthesis_approved.json")
        if not pkg:
            raise Pause("approved synthesis missing: the bridge has nothing to hand to the writing agents")
        return pkg, self._findings() or [], self.load("selected_corpus.json", [])

    def _reproject(self, stage: str) -> None:
        """Re-project the rest of the run from what has been spent, before the stage makes its first call. A
        projection over the cap stops the next call (_require_projection)."""
        proj = cost_projection.remaining_for_run(self)
        self.save("cost_projection.json", proj)
        self.prov.tool_run("reprojection", stage, {"projected_remaining_usd": proj["projected_remaining_usd"],
                                                   "projected_total_usd": proj["projected_total_usd"],
                                                   "verdict": proj["verdict"]})

    def _admitted(self, agent_id: str, payload: dict, step: str, schema_file: str | None = None,
                  exclude: frozenset = frozenset(), limit: str | None = None) -> dict:
        """One downstream request: bounded and checked against the model's window (admission.py), the pricing
        threshold, the projection line, the runtime gate and the cap (an existing reservation, held for the call).
        Raises AdmissionRefused when the request does not fit; the caller subdivides by its fixed rule or stops."""
        from . import admission
        from .synthesis_registry import fingerprint
        m = self.route(agent_id, exclude)
        overrides = {}
        if limit:   # an output cap sized to the unit requested (pipeline.yaml -> bridge.output_limits)
            overrides = {"max_tokens": int(self._bridge_cfg()["output_limits"][limit])}
            m = dataclasses.replace(m, **overrides)
        a = admission.assess(agent_id, payload, m, self.cfg.get("admission") or {}, self.budget.prices)
        usd = self.budget.cost(m.model, a["input_bound"], a["output_reserve"])
        if usd is None:
            raise UnpricedModel(m.model)
        self.prov.tool_run("admission", step, {**a, "reserve_usd": round(usd, 4)})
        if not a["fits"]:
            raise admission.AdmissionRefused(
                f"{agent_id} {step}: input bound {a['input_bound']:,} + output reserve {a['output_reserve']:,} "
                f"exceeds the {a['window']:,}-token window of {m.model}")
        self._require_projection()
        if a["crosses_threshold"]:
            self._check_long_context(agent_id, a)
        self._check_request_line(agent_id)
        self._downstream_gate(agent_id, usd)
        key = f"{agent_id.lower()}-" + fingerprint([step, m.model, payload])[:24]
        if key in self.budget.reservations():
            raise Pause(f"unsettled {agent_id} reservation {key}: reconcile provider usage before retrying")
        ok, available = self.budget.reserve(key, usd, agent_id, "downstream pre-call reservation")
        if not ok:
            raise BudgetExceeded(f"{agent_id} request reserves ${usd:.2f}; only ${available:.2f} remains under the cap")
        try:
            out = self.agent(agent_id, payload, step=step, overrides=overrides or None, schema_file=schema_file,
                             exclude_providers=exclude, reservation_key=key)
        except AgentError:
            if any(e["step"] == step for e in self.budget.entries()):
                self.budget.release(key)   # the call was logged; an unlogged failure stays held until reconciled
            raise
        except (Pause, BudgetExceeded, UnpricedModel):
            self.budget.release(key)
            raise
        self.budget.release(key)
        return out

    def _check_long_context(self, agent_id: str, a: dict) -> None:
        """A request over the model's long-context threshold is repriced in full: it needs a projection that
        priced that many such calls for the agent, or the projection is superseded and the run re-projected."""
        proj = self.load("cost_projection.json") or {}
        line = next((x for x in proj.get("lines", []) if x.get("stage") == agent_id), {})
        planned = int(line.get("long_context_calls") or 0)
        made = sum(1 for e in self.prov.events() if e["type"] == "tool_run" and e["tool"] == "admission"
                   and e["summary"].get("agent") == agent_id and e["summary"].get("crosses_threshold")
                   and e["time"] >= proj.get("created", ""))
        if made > planned:
            reason = (f"{agent_id}: input bound {a['input_bound']:,} crosses the {a['long_context_threshold']:,}-token "
                      f"pricing threshold of {a['model']} (call {made}; the projection priced {planned})")
            self._supersede_projection(reason)
            raise Pause(f"{reason}. The whole request is repriced above the threshold: re-project with "
                        f"`litreview project {self.id}` before the call")

    def _check_request_line(self, agent_id: str) -> None:
        """The projection line for this agent is the authorized spend: past its calls or its dollars, the projection
        is superseded before the next call."""
        proj = self.load("cost_projection.json") or {}
        if proj.get("verdict") != "WITHIN_CAP":
            return
        line = next((x for x in proj.get("lines", []) if x.get("stage") == agent_id
                     and x.get("basis") in ("REQUEST_BOUND", "ESTIMATED_ENVELOPE")), None)
        if line is None:
            return
        since = [e for e in self.budget.entries() if e["agent"] == agent_id and e["time"] >= proj["created"]]
        usd = sum(e["cost_usd"] or 0 for e in since)
        reason = (f"{agent_id} has spent ${usd:.2f} since the projection, over its line (${line['usd']:.2f})"
                  if usd > line["usd"] else f"{agent_id} has made {len(since)} calls since the projection, all its "
                  f"line ({line['calls']}) allows" if len(since) >= int(line["calls"]) else None)
        if reason:
            self._supersede_projection(f"projection line overrun: {reason}")
            raise Pause(f"projection line overrun: {reason}. Re-project with `litreview project {self.id}`.")

    def _downstream_gate(self, agent_id: str, usd: float) -> None:
        """The runtime gate (batch.gate_usd, $150) before every downstream call, as before every batch: spent +
        committed (reservations held) + the rest of the run as projected + this request's reserve. Recorded
        whatever the verdict. The run's spend cap stays absolute on its own (the reservation enforces it)."""
        limit = (self.cfg.get("batch") or {}).get("gate_usd")
        if limit is None:
            raise BudgetExceeded(f"{agent_id}: batch.gate_usd is not set; no downstream call without the runtime gate")
        p = cost_projection.remaining_for_run(self)
        spent, committed = self.budget.spent(), self.budget.reserved()
        total = spent + committed + p["projected_remaining_usd"] + usd
        verdict = "PASS" if total <= float(limit) else "STOP"
        self.prov.tool_run("downstream_gate", agent_id, {"spent_usd": round(spent, 4), "committed_usd": round(committed, 4),
                                                         "projected_usd": p["projected_remaining_usd"],
                                                         "reserve_usd": round(usd, 4), "total_usd": round(total, 2),
                                                         "limit_usd": float(limit), "verdict": verdict})
        if verdict != "PASS":
            raise BudgetExceeded(f"{agent_id}: spent ${spent:.2f} + committed ${committed:.2f} + projected "
                                 f"${p['projected_remaining_usd']:.2f} + this request ${usd:.2f} = ${total:.2f}, over the "
                                 f"${float(limit):.2f} gate. Revise the scope and re-project; any increase is a separate "
                                 "priced decision")

    def _ledger_approved(self, plan, ledger, report, pkg, corpus, table) -> None:
        from . import bridge
        digest = bridge.plan_version(plan, ledger)
        decision = checkpoints.approved(self.dir, "CP_LEDGER")
        if decision and decision.get("fingerprint") == digest and decision.get("approve_ledger") is True:
            return
        index = {e["id"]: e for e in bridge.element_index(pkg, corpus, set(table.get("propositions_fully_shown") or []))}
        checkpoints.write_ledger_review(self.dir, digest, ledger, report, index)
        self.pause_for_checkpoint("CP_LEDGER")

    def _plan_state(self):
        """Everything the writing stages work from, checked: approved ledger, packets, map and versions."""
        from . import bridge
        pkg, findings, corpus = self._bridge_inputs()
        plan, ledger = self.load("manuscript_plan.json"), self.load("allocation_ledger.json")
        if plan is None or ledger is None:
            raise Pause("no manuscript plan and allocation ledger: run the outline stage")
        pv = bridge.plan_version(plan, ledger)
        if (self.load("bridge/plan_check.json") or {}).get("plan_version") != pv:
            raise Pause("the plan or ledger changed after the bridge checked it: rerun the outline stage")
        if self._bridge_cfg().get("ledger_approval", True):
            d = checkpoints.approved(self.dir, "CP_LEDGER")
            if not d or d.get("fingerprint") != pv or d.get("approve_ledger") is not True:
                raise Pause("the allocation ledger is not approved for this plan (CP_LEDGER)")
        try:
            packets = bridge.section_packets(plan, ledger, pkg, findings, corpus)
        except bridge.BridgeError as exc:
            raise Pause(f"section packets: {exc}") from exc
        ev = bridge.evidence_version(pkg, findings)
        for sid, packet in packets.items():   # evidence A09 retrieved for a section stays in its packet
            saved = self.load(f"sections/{pv[:16]}/{sid}.json")
            if saved and saved.get("evidence_version") == ev:
                packet["retrieved"] = saved.get("retrieved") or {}
        return {"pkg": pkg, "findings": findings, "corpus": corpus, "plan": plan, "ledger": ledger, "packets": packets,
                "amap": bridge.argument_map(pkg, corpus), "pv": pv, "ev": ev, "journal": config.load("journal_scirev"),
                "table": (self.load("display_items.json") or [None])[0]}

    def _bridge_fingerprint(self, m: dict, ps: dict | None = None) -> str:
        from . import bridge
        if ps is None:
            pkg, findings, _ = self._bridge_inputs()
            plan, ledger = self.load("manuscript_plan.json", {}), self.load("allocation_ledger.json", [])
            return bridge.content_fingerprint(m, bridge.plan_version(plan, ledger), bridge.evidence_version(pkg, findings))
        return bridge.content_fingerprint(m, ps["pv"], ps["ev"])

    def _stamp(self, rv: dict, m: dict, ps: dict) -> dict:
        """Record what an A10 report approved: the manuscript's content fingerprint (text, plan version and
        evidence-registry version) under the report's verification fingerprint."""
        stamps = self.load("bridge/verification_stamps.json", {})
        stamps[rv.get("verification_fingerprint")] = self._bridge_fingerprint(m, ps)
        self.save("bridge/verification_stamps.json", stamps)
        self.save("bridge/fingerprints.json", {**self.load("bridge/fingerprints.json", {}),
                                               self.state().get("current_manuscript") or "?": stamps[rv.get("verification_fingerprint")]})
        return rv

    def _require_current(self, rv: dict, m: dict, ps: dict, who: str) -> None:
        """A11 and A12 refuse stale verification: A10's report must be current for this exact manuscript, and its
        stamp must match the manuscript's fingerprint now (a plan or evidence-registry change invalidates it)."""
        if not rv or not self._verification_current(rv, m):
            raise Pause(f"{who}: A10 verification is not current for this manuscript; verify before continuing")
        stamp = self.load("bridge/verification_stamps.json", {}).get(rv.get("verification_fingerprint"))
        if stamp != self._bridge_fingerprint(m, ps):
            raise Pause(f"{who}: A10 approval is stale: the text, plan or evidence registry changed since it was given")

    def _binding_gate(self, m: dict, ps: dict, where: str) -> None:
        """After any writer or editor output: every section's tags stay inside its packet, every number in the
        records it is tagged with, every citation bound; the front matter against all packets."""
        from . import bridge
        problems = []
        for s in m.get("sections") or []:
            packet = ps["packets"].get(s.get("section_id"))
            if packet is None:
                problems.append(f"SECTION_UNKNOWN: {s.get('section_id')}")
                continue
            if s.get("heading") != packet.get("heading"):
                problems.append(f"HEADING: {s.get('section_id')} heading differs from the approved plan")
            problems += bridge.check_text(s.get("text_markdown") or "", packet, s.get("section_id"))
        problems += self._front_problems(m, ps)
        if [s.get("section_id") for s in m.get("sections") or []] != [s["section_id"] for s in ps["plan"]["sections"]]:
            problems.append("SECTIONS: the manuscript's sections differ from the approved plan")
        self.save(f"bridge/gate_{where}.json", {"problems": problems})
        self.prov.tool_run("binding_gate", where, {"problems": len(problems)})
        if problems:
            raise Pause(f"{where}: evidence binding gate failed ({len(problems)}; first: {problems[0]}); see "
                        f"data/bridge/gate_{where}.json")

    def _front_problems(self, m: dict, ps: dict) -> list[str]:
        from . import bridge
        gp = bridge.global_packet(ps["packets"])
        gp["retrieved"] = {k: v for p in ps["packets"].values() for k, v in (p.get("retrieved") or {}).items()}
        title_ids = (ps["plan"].get("title") or {}).get("proposition_ids") or []
        problems = bridge.check_text(f"{m.get('title') or ''} ⟦{','.join(title_ids) or 'ORG'}⟧", gp, "title")
        problems += bridge.check_text(m.get("abstract") or "", gp, "abstract")
        for c in m.get("table_captions") or []:
            problems += bridge.check_text(c.get("caption") or "", gp, f"caption {c.get('display_id')}")
        return problems

    def _write_sections(self, ps: dict, label: str, redo: dict | None = None) -> list[dict]:
        """A09, one section at a time in the plan's writing order. Each call gets the approved outline, its own
        packet and the full prose of the sections written before it (narrative context only, never evidence). A
        structured evidence request is fulfilled from the registry, at most bridge.max_retrieval_rounds times.
        The deterministic section gate runs before the next section starts. Sections already written for the same
        plan, evidence and earlier prose are kept on resume. redo: {section_id: revision request}."""
        from . import bridge
        from .admission import AdmissionRefused
        from .synthesis_registry import fingerprint
        bcfg = self._bridge_cfg()
        rounds, limit = int(bcfg.get("max_retrieval_rounds", 2)), int(bcfg.get("retrieval_limit", 12))
        store, done = f"sections/{ps['pv'][:16]}", []
        for sid in ps["plan"]["writing_order"]:
            previous = list(done)
            saved = self.load(f"{store}/{sid}.json")
            keep = saved and saved.get("evidence_version") == ps["ev"] and (
                sid not in redo if redo is not None else saved.get("previous_fingerprint") == fingerprint(previous))
            if keep:
                done.append(saved["section"])
                continue
            packet = ps["packets"][sid]
            packet["retrieved"] = dict(packet.get("retrieved") or {})
            request = (redo or {}).get(sid)
            for n in range(rounds + 1):
                payload = bridge.writer_payload(ps["plan"], packet, previous, ps["amap"], ps["journal"], request)
                step = f"A09-WRI_{label}_{sid}_r{n}"
                try:
                    out = self._admitted("A09-WRI", payload, step, schema_file="A09-WRI.section.schema.json",
                                         limit="A09_SECTION")
                except AdmissionRefused as exc:
                    raise Pause(f"{sid}: writer request not admitted ({exc}). A section is the subdivision unit: split "
                                "it in the plan (rerun A08); no evidence is dropped to make it fit") from exc
                if out.get("status") != "NEEDS_EVIDENCE":
                    break
                if n == rounds:
                    raise Pause(f"{sid}: A09 still needs evidence after {rounds} retrieval rounds; nothing is inferred "
                                "in its place (see outputs/" + step + ".json)")
                try:
                    found, log = bridge.fulfil_retrieval(out.get("retrieval_requests") or [], ps["pkg"], ps["findings"], limit)
                except bridge.BridgeError as exc:
                    raise Pause(f"{sid}: evidence request refused: {exc}") from exc
                packet["retrieved"].update(found)
                self.prov.tool_run("writer_retrieval", step, {"section_id": sid, "round": n + 1, "items": log})
            if out.get("status") in ("NEEDS_HUMAN_INPUT", "ABSTAINED", "FAILED") or not out.get("section"):
                raise Pause(f"{sid}: A09 returned {out.get('status')} (see outputs/{step}.json)")
            section = out["section"]
            problems = bridge.check_section(section, packet, ps["plan"], previous)
            self.save(f"{store}/{sid}.gate.json", {"problems": problems, "step": step})
            self.prov.tool_run("section_gate", step, {"section_id": sid, "problems": len(problems)})
            if problems:
                raise Pause(f"{sid}: section gate failed ({len(problems)}; first: {problems[0]}); the next section is "
                            f"not started (data/{store}/{sid}.gate.json)")
            self.save(f"{store}/{sid}.json", {
                "section": section, "retrieved": packet["retrieved"], "evidence_version": ps["ev"],
                "previous_fingerprint": fingerprint(previous), "plan_gaps": out.get("plan_gaps") or [],
                "ceiling_unclear": out.get("ceiling_unclear") or [], "step": step,
                "fingerprint": bridge.content_fingerprint(section, ps["pv"], ps["ev"])})
            done.append(section)
        return done

    def _assemble(self, ps: dict, sections: list[dict], label: str) -> dict:
        """Front matter (A09, from the written sections and the plan), then the draft in the plan's section order."""
        from . import bridge
        from .admission import AdmissionRefused
        payload = bridge.front_matter_payload(ps["plan"], sections, ps["amap"], ps["journal"], ps["table"])
        try:
            front = self._admitted("A09-WRI", payload, f"A09-WRI_{label}_front", schema_file="A09-WRI.front.schema.json",
                                   limit="A09_FRONT_MATTER")
        except AdmissionRefused as exc:
            raise Pause(f"front matter request not admitted ({exc})") from exc
        by_id = {s["section_id"]: s for s in sections}
        ordered = [by_id[s["section_id"]] for s in ps["plan"]["sections"]]
        m = {"draft_version": label, "plan_version": ps["pv"], "title": front.get("title"), "abstract": front.get("abstract"),
             "keywords": front.get("keywords") or [], "sections": ordered, "figure_legends": [],
             "table_captions": front.get("table_captions") or [],
             "main_text_word_count": sum(len(tags.strip_tags(s.get("text_markdown") or "").split()) for s in ordered),
             "plan_gaps": [g for s in ps["plan"]["writing_order"]
                           for g in (self.load(f"sections/{ps['pv'][:16]}/{s}.json") or {}).get("plan_gaps", [])]}
        problems = self._front_problems(m, ps)
        if problems:
            self.save(f"bridge/gate_{label}_front.json", {"problems": problems})
            raise Pause(f"front matter gate failed ({len(problems)}; first: {problems[0]})")
        return m

    def _edit(self, mode: str, m: dict, ps: dict, step: str, **extra) -> dict:
        """A12 on the whole manuscript if the request is admitted; otherwise one unit at a time (front matter, then
        each section), each unit's output replacing only that unit. Each unit request carries the same map, ledger,
        outline and findings; a unit that alone does not fit stops the stage."""
        from . import bridge
        from .admission import AdmissionRefused
        try:
            out = self._admitted("A12-EDI", bridge.editor_payload(mode, m, ps["amap"], ps["ledger"], ps["plan"], **extra), step)
            edited = {**m, **{k: out[k] for k in ("title", "abstract", "sections") if k in out}}
            for k in ("keywords", "table_captions", "figure_legends"):
                if k in out:
                    edited[k] = out[k]
            edited.update(change_log=out.get("change_log") or [], queries=out.get("queries") or [],
                          escalations=out.get("escalations") or [], edit_mode=mode)
            return edited
        except AdmissionRefused:
            pass
        outputs, log, queries, escalations = {}, [], [], []
        for uid, part in bridge.manuscript_units(m):
            try:
                o = self._admitted("A12-EDI", bridge.editor_payload(mode, part, ps["amap"], ps["ledger"], ps["plan"],
                                                                  unit=uid, **extra),
                                   f"{step}_{uid}", schema_file="A12-EDI.unit.schema.json", limit="A12_UNIT")
            except AdmissionRefused as exc:
                raise Pause(f"{step}: unit {uid} not admitted ({exc}); nothing is dropped to make it fit") from exc
            outputs[uid] = o
            log += o.get("change_log") or []
            queries += o.get("queries") or []
            escalations += o.get("escalations") or []
        edited = bridge.merge_units(m, outputs)
        edited.update(change_log=log, queries=queries, escalations=escalations, edit_mode=mode, edited_by_unit=True)
        return edited

    def _integrate(self, draft: dict, ps: dict, label: str) -> dict:
        """One A12 pass over the assembled draft for transitions, repetition, terminology and argument progression.
        Every change to an element-tagged sentence is recorded as substantive; A10 verifies the integrated draft in
        any case. The binding gate runs on the result."""
        from . import bridge
        integrated = self._edit("INTEGRATION", draft, ps, f"A12-EDI_integration_{label}")
        report = bridge.classify_integration(draft, integrated)
        self.save(f"bridge/integration_{label}.json", report)
        self.prov.tool_run("integration_pass", label, {"substantive": report["substantive"],
                                                       "changed_sections": sorted(report["changed_sections"])})
        self._binding_gate(integrated, ps, f"integration_{label}")
        return {k: v for k, v in integrated.items() if k not in ("change_log", "queries", "escalations", "edit_mode",
                                                                 "edited_by_unit")}

    def stage_draft(self, st: dict) -> str:
        """Sequential section writing, front matter, one integration pass, then A10 on the integrated draft.
        A09 redrafts only the sections A10's blocking findings point at."""
        self._reproject("draft")
        ps = self._plan_state()
        sections = self._write_sections(ps, "draft1")
        draft = self._integrate(self._assemble(ps, sections, "draft1"), ps, "draft1")
        self._save_manuscript(draft, "m01_draft")
        rv = self._stamp(self._verify(draft, "DRAFT", "A10-RV_draft1"), draft, ps)
        for i in range(int(self.cfg["loops"]["max_redrafts"])):
            blocking = [f for f in rv.get("findings", []) if f.get("severity") == "BLOCKING"
                        and str(f.get("responsible_stage") or "").startswith("A09")]
            if not blocking and not rv.get("systemic_failure"):
                break
            redo = self._sections_named(rv, draft, blocking or rv.get("findings", []))
            sections = self._write_sections(ps, f"draft{i + 2}", redo=redo)
            draft = self._integrate(self._assemble(ps, sections, f"draft{i + 2}"), ps, f"draft{i + 2}")
            self._save_manuscript(draft, f"m01_draft{i + 2}")
            rv = self._stamp(self._maybe_verify(draft, "DRAFT", f"A10-RV_draft{i + 2}", rv), draft, ps)
        self.save("rv_latest.json", rv)
        return "review_loop"

    @staticmethod
    def _sections_named(rv: dict, m: dict, findings: list[dict]) -> dict:
        """{section_id: [findings]} for the sections A10's findings point at (front matter is rewritten anyway)."""
        where = {o["occurrence_id"]: o["path"] for o in rv.get("occurrence_inventory", [])}
        out: dict[str, list] = {}
        for f in findings:
            for oid in f.get("occurrence_ids") or []:
                path = where.get(oid) or []
                if path[:2] == ["manuscript", "sections"] and len(path) > 2:
                    out.setdefault(m["sections"][path[2]]["section_id"], []).append(f)
        return out or {s["section_id"]: findings for s in m.get("sections") or []}

    def stage_review_loop(self, st: dict) -> str:
        """A11 critiques the manuscript with the compact map, the ledger and A10's findings (never the full plan or
        package); A12 revises. Both refuse stale verification."""
        from . import bridge
        from .admission import AdmissionRefused
        self._reproject("review_loop")
        ps = self._plan_state()
        for cycle in range(1, int(self.cfg["loops"]["max_critique_cycles"]) + 1):
            m, rv = self._current(), self.load("rv_latest.json")
            if not self._verification_current(rv or {}, m):
                rv = self._stamp(self._verify(m, 'REVISION', f'A10-RV_precritique{cycle}'), m, ps)
                self.save('rv_latest.json', rv)
            self._require_current(rv, m, ps, "A11-RC")
            summary = {k: v for k, v in rv.items() if k not in ('occurrence_inventory', 'verdicts',
                       'global_index_ids_reviewed', 'request_metrics', 'correction_trace')}
            payload = bridge.critique_payload(m, ps["amap"], ps["ledger"], summary, ps["journal"], self.load("rc_latest.json"))
            try:
                rc = self._admitted("A11-RC", payload, f"A11-RC_cycle{cycle}", exclude=self._prose_vendors("A11-RC"))
            except AdmissionRefused as exc:
                raise Pause(f"A11 request not admitted ({exc}); the critique reads the whole manuscript and is not "
                            "subdivided") from exc
            rc["bridge_fingerprint"] = self._bridge_fingerprint(m, ps)
            self.save("rc_latest.json", rc)
            if rc["decision"] == "ACCEPT":
                if any(f.get('severity') == 'BLOCKING' for f in rv.get('findings', [])):
                    raise Pause('A11 ACCEPT cannot override unresolved A10 BLOCKING defects')
                return "finish_edit"
            if rc["decision"] == "HOLD_FOR_UPSTREAM_REVIEW":
                raise Pause("A11-RC requests upstream review (see data/rc_latest.json)")
            self._require_current(rv, m, ps, "A12-EDI REVISION")
            if rc["bridge_fingerprint"] != self._bridge_fingerprint(m, ps):
                raise Pause("A12-EDI REVISION: the critique is stale (text, plan or evidence changed after it)")
            ed = self._edit("REVISION", m, ps, f"A12-EDI_revision{cycle}", critique=rc,
                            verification_findings=rv.get("findings"))
            self._binding_gate(ed, ps, f"revision{cycle}")
            self._save_manuscript(ed, f"m02_revision{cycle}")
            rv = self._stamp(self._maybe_verify(ed, "REVISION", f"A10-RV_revision{cycle}", rv, ed.get("change_log")), ed, ps)
            self.save("rv_latest.json", rv)
        raise Pause("critique cycles exhausted without ACCEPT — review data/rc_latest.json "
                    "(the draft is never accepted just because cycles ran out)")

    def stage_finish_edit(self, st: dict) -> str:
        self._reproject("finish_edit")
        ps = self._plan_state()
        m = self._current()
        self._require_current(self.load("rv_latest.json") or {}, m, ps, "A12-EDI LINE")
        line = self._edit("LINE", m, ps, "A12-EDI_line")
        self._binding_gate(line, ps, "line")
        self._save_manuscript(line, "m03_line")
        rv = self._stamp(self._maybe_verify(line, "REVISION", "A10-RV_line", {}, line.get("change_log")), line, ps)
        self.save("rv_latest.json", rv)
        if rv.get("finding_severity") in ("MAJOR", "BLOCKING"):
            raise Pause("scientific findings after line edit require correction (see data/rv_latest.json)")
        self._require_current(rv, line, ps, "A12-EDI PROOF")
        proof = self._edit("PROOF", line, ps, "A12-EDI_proof", verification_findings=rv.get('findings', []))
        self._binding_gate(proof, ps, "proof")
        self._save_manuscript(proof, "m04_proof")
        final = self._stamp(self._verify(proof, "FINAL", "A10-RV_final"), proof, ps)
        self.save("rv_final.json", final)
        if final.get("release_disposition") not in ("APPROVED", "APPROVED_WITH_MINOR_FINDINGS"):
            raise Pause(f"final verification: {final.get('release_disposition')} (see data/rv_final.json)")
        return "finalize"

    def stage_finalize(self, st: dict) -> str:
        m = self._current()
        report = self.load('rv_final.json',{})
        defects = any(f.get('severity') in ('MAJOR','BLOCKING') for f in report.get('findings',[]))
        if defects or not self._verification_current(report,m) or report.get('release_disposition') not in ('APPROVED','APPROVED_WITH_MINOR_FINDINGS'):
            raise Pause('final release requires current complete A10 approval with no unresolved major/blocking findings')
        plan = self.load("manuscript_plan.json")
        corpus = {r["record_id"]: r for r in self.load("selected_corpus.json")}
        tables = self._built_tables()
        # tables come after the text, so a paper cited only in a table is numbered after every text citation
        texts = [s["text_markdown"] for s in m["sections"]] + [" ".join(c for row in t["rows"] for c in row)
                                                                for t in tables]
        numbers = references.number_citations(texts)

        def cite(match):
            ids = [p.strip().lstrip("@") for p in match.group(1).split(";")]
            return "[" + ",".join(str(numbers[i]) for i in ids if i in numbers) + "]"

        levels = {s.get("section_id"): s.get("level", 1) for s in plan.get("sections", [])}
        body = []
        for s in m["sections"]:
            t = tags.strip_tags(s["text_markdown"])
            t = tags.CITE_RE.sub(cite, t)
            t = tags.DISPLAY_RE.sub(lambda x: ("Fig. " if x.group(1)[0] == "F" else "Table ") + x.group(1)[1:], t)
            body.append({"heading": s["heading"], "level": levels.get(s.get("section_id"), 1), "text": t})
        refs = []
        for rid, n in sorted(numbers.items(), key=lambda x: x[1]):
            r = corpus.get(rid, {})
            meta = references.crossref_lookup(r["doi"], os.environ.get("CROSSREF_MAILTO")) if r.get("doi") else None
            refs.append(f"{n}. " + (references.format_nature(meta) if meta else
                                    f"{', '.join(r.get('authors', [])[:1])} et al. {r.get('title')}. {r.get('venue')} ({r.get('year')}). [CHECK FORMAT]"))
        final_dir = self.dir / "final"
        final_dir.mkdir(exist_ok=True)
        src_items, out_items = self.dir / "data" / "display_items", final_dir / "display_items"
        if src_items.exists():
            shutil.copytree(src_items, out_items, dirs_exist_ok=True)
        built = {d["display_id"]: d for d in self.load("display_items.json", [])}
        figures = []
        for leg in m.get("figure_legends", []):
            b = built.get(leg["display_id"], {})
            figures.append({"display_id": leg["display_id"], "legend": tags.strip_tags(leg["legend"]),
                            "image": out_items / b["image"] if b.get("image") else None, "brief": b.get("brief")})
        captions = {c["display_id"]: tags.strip_tags(c["caption"]) for c in m.get("table_captions", [])}
        doc = {"title": m["title"], "abstract": m["abstract"], "keywords": m.get("keywords", []),
               "sections": body, "references": refs,
               "back_matter": [("Author contributions and biographies", "[TO BE WRITTEN BY THE AUTHORS]"),
                               ("AI use disclosure", "[TO BE WRITTEN BY THE AUTHORS — see provenance_summary.json]"),
                               ("Competing interests", "[TO BE WRITTEN BY THE AUTHORS]")],
               "figures": figures,
               "tables": [{"display_id": t["display_id"], "columns": t["columns"],
                           "caption": captions.get(t["display_id"], "[CAPTION TO BE WRITTEN]"),
                           "rows": [[tags.CITE_RE.sub(cite, c) for c in row] for row in t["rows"]],
                           "notes": ["NR, not reported. Values are taken from validated findings; "
                                     "check against the source papers before submission."]
                                    + [tags.CITE_RE.sub(cite, n["text"]) for n in t.get("inconsistency_notes", [])]
                                    + ([f"Left blank for the authors: {', '.join(t['unmapped_columns'])}."]
                                       if t.get("unmapped_columns") else [])}
                          for t in tables]}
        (final_dir / "manuscript.md").write_text(manuscript_export.render_markdown(doc), encoding="utf-8")
        manuscript_export.render_docx(doc, final_dir / "manuscript.docx")
        comp = compliance.check({**m, "references": list(numbers),
                                 "display_items": self.load("manuscript_plan.json").get("display_items", [])})
        (final_dir / "compliance.json").write_text(json.dumps(comp, indent=2), encoding="utf-8")
        (final_dir / "costs.txt").write_text(self.budget.summary_text(), encoding="utf-8")
        (final_dir / "provenance_summary.json").write_text(json.dumps(self._provenance_summary(), indent=2),
                                                           encoding="utf-8")
        notify.send("complete", f"Run {self.id}: review draft complete",
                    f"Compliance: {'PASS' if comp['all_pass'] else 'see compliance.json'}\n"
                    f"Main text: {comp['main_text_words']} words, {comp['references']} references\n\n"
                    f"{self.budget.summary_text()}\n\n"
                    f"{verification_scope.detail_report_text(self._a10_detail_report())}",
                    attachments=[final_dir / "manuscript.docx", final_dir / "manuscript.md", final_dir / "compliance.json",
                                 final_dir / "provenance_summary.json"])
        return "done"
