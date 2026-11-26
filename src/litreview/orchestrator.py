"""Orchestrator: a deterministic state machine. It routes; it never makes scientific judgements.

Run state lives in runs/<run_id>/state.json, so a run can stop (checkpoint, budget, error)
and resume exactly where it left off with `litreview run <run_id>`.

Stage order
  scope -> cp1 -> search -> qualify -> expand -> cp2 -> extract -> validate -> synthesize -> cp3
  -> outline -> draft -> review_loop -> finish_edit -> finalize -> done
"""
from __future__ import annotations
from decimal import Decimal

import dataclasses
import hashlib
import json
import os
import tempfile
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path

from . import checkpoints, config, evidence, handoff, model_record, notify, publication, corpus_policy
from .agents import AgentError, RefusalError, run_agent
from .agents.base import prompt_version
from .budget import BatchGateRefused, BudgetExceeded, BudgetTracker, UnpricedModel
from .paths import RUNS_DIR, SCHEMAS_DIR
from .provenance import ProvenanceLog
from . import synthesis_input, theme_framework, pilot_authorization as pilot
from .agents.base import build_system_prompt, user_parts
from .batch_stage import BatchStage
from .synthesis_job import JobStopped
from .tools import cost_projection
from .tools import (compliance, display_items, manuscript_export, references, span_check, submission, tags,
                    themes, verification_scope)
from .tools.fulltext import fetch_sections, fetch_verified_sections, verify_cached_source, FullTextUnavailable
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
def new_run(topic: str, notes: str = "", seeds: list[str] | None = None, family: str = "unspecified",
            budget_authority=None, corpus_mode="FIXED_CORPUS", scope_configuration=None,
            profile: str | None = None, outline: dict | None = None, corpus_manifest: dict | None = None,
            spec_base_dir: Path | None = None) -> str:
    from .evaluation_budget import prepare
    from . import run_spec
    if corpus_manifest is not None and outline is None:
        raise ValueError("a corpus manifest needs an outline")
    spec_limits = config.effective(profile).get("run_spec") or {}
    if outline is not None and corpus_manifest is None:
        if corpus_mode != "OPEN_CORPUS":
            raise ValueError("a discovery run (an outline without a corpus manifest) uses --corpus-mode OPEN_CORPUS")
        run_spec.check_outline(outline, spec_limits)
    elif outline is not None:
        if corpus_mode == "FIXED_CORPUS":
            raise ValueError("a run with an outline and a corpus manifest uses --corpus-mode OPEN_CORPUS (the manifest "
                             "fixes the corpus; FIXED_CORPUS is the closed staged pilot)")
        run_spec.check(outline, corpus_manifest, spec_limits, spec_base_dir)
    profile = config.run_settings(profile).get("profile")   # an unknown profile is refused here, before any file
    if profile == "manuscript" and corpus_mode == "FIXED_CORPUS":
        raise ValueError("The manuscript profile is for the full run: use --corpus-mode OPEN_CORPUS. FIXED_CORPUS "
                         "is the staged pilot, which keeps its own $35 authorization.")
    if budget_authority is None and corpus_mode == "OPEN_CORPUS":
        # A standard run starts from zero under its spend profile. The $35 evaluation authority belongs to the
        # staged pilot: no earlier spend, approval or financial authorization is carried into a fresh run.
        authority = None
    else:
        authority = prepare(budget_authority)
        if authority["authority"].get("corpus_mode", "FIXED_CORPUS") != corpus_mode:
            raise ValueError("Requested corpus mode differs from reviewed budget authority")
    if scope_configuration is not None and (not isinstance(scope_configuration, dict) or set(scope_configuration) - {
            "parent_run_id", "parent_cp1_sha256", "purpose", "central_question", "perspective",
            "selection_criteria", "theme_framework", "qualifications"}):
        raise ValueError("Scope configuration accepts human-approved scope only, not prior scientific outputs")
    run_id = time.strftime("%Y%m%d-%H%M%S")
    d = RUNS_DIR / run_id / "input"
    d.mkdir(parents=True)
    (d / "topic.md").write_text(topic, encoding="utf-8")
    (d / "notes.md").write_text(notes, encoding="utf-8")
    (d / "seeds.txt").write_text("\n".join(seeds or []), encoding="utf-8")
    (d / "topic_family.txt").write_text(family, encoding="utf-8")
    (d / "code_version.json").write_text(json.dumps(code_version(), indent=2), encoding="utf-8")
    if scope_configuration is not None:
        (d / "human_scope_configuration.json").write_text(json.dumps(scope_configuration, indent=2), encoding="utf-8")
    if outline is not None and corpus_manifest is None:
        run_spec.install_discovery(d.parent, outline, spec_limits)
    elif outline is not None:
        run_spec.install(d.parent, outline, corpus_manifest, spec_limits, spec_base_dir)
        seeds = sorted({p["pmid"] for p in corpus_manifest["papers"] if p.get("pmid")} | set(seeds or []))
        (d / "seeds.txt").write_text("\n".join(seeds), encoding="utf-8")
    policy_fingerprint = corpus_policy.initialize(
        d.parent, corpus_policy.manifest_policy(corpus_manifest) if corpus_manifest is not None
        else corpus_policy.default_policy(corpus_mode))
    if authority:
        (d / "evaluation_budget.json").write_text(json.dumps(authority, indent=2), encoding="utf-8")
    Run(run_id).save_state({"stage": "scope", "status": "READY", "counters": {},
                           "execution_mode": "STAGED_PILOT" if corpus_mode == "FIXED_CORPUS" else "STANDARD",
                           "corpus_policy_fingerprint": policy_fingerprint,
                           **({"profile": profile} if profile else {})})
    return run_id


def compiled_queries(family: dict) -> dict[str, str]:
    """A query family's compiled queries as {source: query}. The A03 contract returns them as a list of
    {source, query} (strict structured output has no free-form maps); a plan saved before that change is a map.
    A source compiled twice is ambiguous and refused rather than silently taking one of the two."""
    raw = family.get("compiled") or {}
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items()}
    out: dict[str, str] = {}
    for entry in raw:
        source = entry.get("source")
        if source in out:
            raise ValueError(f"query family {family.get('family_id')}: source {source} is compiled twice")
        out[source] = entry.get("query") or ""
    return out


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
        recorded = None
        try:
            recorded = json.loads((self.dir / "state.json").read_text(encoding="utf-8")).get("profile")
        except (OSError, ValueError):
            pass
        self.cfg = config.effective(recorded)
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
        # Stream encoder chunks: dumps + write_text holds the full Unicode document,
        # newline translation and UTF-8 buffers together on Windows. Keep the previous
        # accepted artifact intact if encoding/writing is interrupted.
        target = self.data(name)
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(obj, stream, ensure_ascii=False, indent=2)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def load(self, name: str, default=None):
        p = self.data(name)
        if not p.exists():
            return default
        # Decode containers incrementally: json.load(stream) calls read() without
        # a size, retaining a full Unicode document alongside the decoded graph.
        from .json_stream import load
        with p.open(encoding="utf-8", newline="") as stream:
            return load(stream)

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

    def _require_provider_contracts(self) -> None:
        from . import structured
        schema_problems = [r for r in structured.schema_inventory() if r["problems"]]
        if schema_problems:
            self.save("schema_compatibility.json", schema_problems)
            raise Pause("configured provider schema compatibility failed; see data/schema_compatibility.json")

    def preflight_routing(self) -> None:
        """At run start: stop before any spending if some agent has no unrefused model in this family,
        rather than paying for search and extraction and stopping at synthesis."""
        self._require_provider_contracts()
        refused = model_record.refused(self.family())
        done = STAGES[:STAGES.index(self.state()["stage"])]
        for agent_id in self.cfg["agents"]:
            if pilot.enabled(self) and STAGES.index(self.state()["stage"])<=STAGES.index("cp3") and agent_id in pilot.SECOND:continue
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
        if pilot.enabled(self):
            return  # stage-specific guard runs before dispatch/reservation, including before CP2
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
        line = next((x for x in proj.get("lines", []) if x.get("basis") in ("WORST_CASE", "CALIBRATED_FORECAST")
                     and x["stage"] == agent_id), None)
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
        if pilot.enabled(self):
            try:
                pilot.require(self,agent_id)
                p=pilot.project(self,pilot.stage_for(self,agent_id),in_flight=frozenset(steps),candidate=(agent_id,reserve_usd))
            except pilot.AuthorizationRequired as exc:raise Pause(str(exc)) from exc
            if p['verdict']!='WITHIN_CAP':raise Pause('Pilot batch exceeds remaining authorized budget')
            return p
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

    def _reserve(self,key,usd,agent_id,note="",steps=(),margin_included=False):
        # margin_included: the caller's amount already carries the 30% margin (plan_retry's approved hold);
        # adding it again would over-hold and break the exact-candidate check in the stage projection.
        if agent_id in {"A07-SYN", "A08-OL", "A09-WRI", "A10-RV", "A11-RC", "A12-EDI"} and not margin_included:
            # Hold the future-work margin, not merely check it. Actual charges settle this hold.
            usd = float(Decimal(str(usd)) * Decimal("1.30"))
        if agent_id == "A07-SYN" and getattr(self, "_reconciliation_approval", None):
            from .reconciliation_paging import check_spend
            auth = self._reconciliation_approval
            if any("_RECONCILE_" in step for step in steps):
                if not any(step.startswith(f"A07-SYN_job{auth['job_tag']}_{turn}_LOOKUP")
                           for step in steps for turn in auth["approved_turns"]):
                    raise Pause("reconciliation page outside the approved tranche")
                try:
                    check_spend(auth, self.budget.stage_committed("A07"), usd)
                except ValueError as exc:
                    raise Pause(str(exc)) from exc
        if pilot.enabled(self):
            try:
                pilot.require(self,agent_id)
                in_flight={s for p in (self.dir/'data'/'batches').glob('*.json')
                           for r in json.loads(p.read_text(encoding='utf-8'))
                           if r['status'] in ('INTENT','SUBMITTED','UNRESOLVED') for s in r['steps']}
                p=pilot.project(self,pilot.stage_for(self,agent_id),in_flight=frozenset(in_flight|set(steps)),candidate=(agent_id,usd))
                if p['verdict']!='WITHIN_CAP':raise pilot.AuthorizationRequired('New commitment would exceed $35 future-work admission')
            except pilot.AuthorizationRequired as exc:raise Pause(str(exc)) from exc
        ok,available=self.budget.reserve(key,usd,agent_id,note)
        if ok and pilot.enabled(self):
            meta=self.load('pilot_reservations.json',{})
            scope=pilot.stage_for(self,agent_id)
            meta[key]={'scope':scope,'steps':list(steps),'authorization':self.load('pilot_'+scope+'.json')['fingerprint']}
            pilot.atomic(self.data('pilot_reservations.json'),meta)
        return ok,available

    def _supersede_projection(self, reason: str) -> None:
        """Spend the projection did not plan for (a paid turn that produced nothing) makes it stale: the next
        agent call requires a new one, priced from what has actually been spent."""
        if pilot.enabled(self):
            from .synthesis_registry import fingerprint
            self.save('pilot_financial_plan.json',{'superseded_reason':reason,'previous':fingerprint(self.load('pilot_financial_plan.json'))})
        proj = self.load("cost_projection.json")
        if proj is not None:
            proj.update(verdict="SUPERSEDED", superseded_reason=reason[:300],
                        superseded_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
            self.save("cost_projection.json", proj)

    def agent(self, agent_id: str, payload: dict, step: str, overrides: dict | None = None,
              schema_file: str | None = None, exclude_providers: frozenset = frozenset(),
              reservation_key: str | None = None, repair_limit: int | None = None,
              truncation_retries: int | None = None, repair_from: tuple[str, str] | None = None) -> dict:
        from . import a06_batches, decisions
        from .approved_scope import enrich, save_delivery
        if getattr(self.budget, 'profile', None) == 'pilot7':
            from .paths import REPO_ROOT
            from .retained_hold import blocking_holds
            hold_auth = REPO_ROOT/'pilot_retained_hold_authorization.json'
            blocked = blocking_holds(self.budget, hold_auth) if hold_auth.exists() else []
            if blocked and not self._fresh_synthesis_reservation(agent_id, step, reservation_key, blocked):
                raise Pause('New unresolved dispatch; preserve its hold and reconcile before continuing')
        payload = enrich(self, agent_id, payload)
        if agent_id in {"A06-SV", "A07-SYN", "A08-OL", "A09-WRI", "A10-RV", "A11-RC", "A12-EDI"}:
            payload = {**payload, "source_access": payload.get("source_access", self.load("source_access.json", {}))}
        payload = decisions.attach(self.dir, agent_id, payload)   # applied decisions travel in the request identity
        save_delivery(self, agent_id, step, payload)
        if agent_id == "A06-SV" and a06_batches.enabled(self,payload):
            try:return a06_batches.audit(self,payload,step,overrides,schema_file,exclude_providers)
            except ValueError as exc:raise Pause("A06 batch validation rejected: " + str(exc)) from exc
        try:
            corpus_policy.resolve(self)
        except ValueError as exc:
            raise Pause(str(exc)) from exc
        if pilot.enabled(self):
            try:
                corpus_policy.resolve(self)
                if agent_id in {"A04-CQ", "A05-KE"}:
                    records = payload.get("records") if agent_id == "A04-CQ" else [payload.get("record") or {}]
                    if not records:
                        raise ValueError("Publication-bound agent request lacks canonical records")
                    corpus_policy.require_records(self, records, internal_ids=True)
                    for rec in records:
                        level = payload.get("content_level") if agent_id == "A05-KE" else rec.get("content_level")
                        required = corpus_policy.fixed(self)[str(rec["pmid"])]
                        if agent_id == "A05-KE" and level != required:
                            raise ValueError("Extraction access level differs from corpus authority")
                        if level == "FULL_TEXT":
                            corpus_policy.require_source(self, rec)
                            verify_cached_source(rec, rec.get("content") or rec.get("sections"), self.load(f"fulltext_provenance/{rec['record_id']}.json"))
                        elif agent_id == "A05-KE" and set(rec.get("content") or {}) != {"Abstract"}:
                            raise ValueError("Abstract-only extraction contains unapproved source sections")
            except ValueError as exc:
                raise Pause(str(exc)) from exc
            # Reuse an accepted, version-identical output before considering another paid submission.
            # A logged response settles only its own hold; uncertain provider usage remains held.
            try:pilot.require(self,agent_id,financial=False)
            except pilot.AuthorizationRequired as exc:raise Pause(str(exc)) from exc
            from .synthesis_registry import fingerprint
            actual_model=self.route(agent_id,exclude_providers)
            if overrides:actual_model=dataclasses.replace(actual_model,**overrides)
            approved_route=self.load('pilot_'+pilot.stage_for(self,agent_id)+'.json')['context']['routes'][agent_id]
            if actual_model.model!=approved_route['model'] or actual_model.provider!=approved_route['provider']:
                raise Pause('Actual route differs from the financially approved route; re-project before dispatch')
            replay=fingerprint([agent_id,payload,dataclasses.asdict(actual_model),schema_file,pilot.identity(self,pilot.stage_for(self,agent_id))['versions']])
            saved=self.load('pilot_requests.json',{}).get(step)
            accepted_path=self.dir/'outputs'/f'{step}.json'
            if saved and saved['request']==replay and accepted_path.exists():
                from .agents.base import validate
                accepted=json.loads(accepted_path.read_text(encoding='utf-8'));validate(agent_id,accepted,schema_file)
                if saved.get('output_hash') and saved['output_hash']!=fingerprint(accepted):raise Pause('Accepted output changed')
                logged={e.get('reservation_key') for e in self.budget.entries() if e['step']==step}
                for key,meta in self.load('pilot_reservations.json',{}).items():
                    if step in meta.get('steps',[]) and key in logged:self.budget.release(key)
                return accepted
            try: pilot.require(self,agent_id,financial=not bool(reservation_key))
            except pilot.AuthorizationRequired as exc: raise Pause(str(exc)) from exc
        self._require_projection()
        self._check_worst_case_line(agent_id)
        m = self.route(agent_id, exclude_providers)
        if "max_tokens" not in (overrides or {}):   # a cap sized to the content level (A05: abstract or full text)
            m = dataclasses.replace(m, max_tokens=config.level_cap(agent_id, payload, m.max_tokens))
        if overrides:
            m = dataclasses.replace(m, **overrides)
        staged = pilot.enabled(self)
        receipt_id = None
        if not staged:
            # A resume never pays twice: an accepted output saved under this step for this exact request is reused.
            receipt_id = self._receipt_request(agent_id, payload, m, schema_file)
            reused = self._receipt_reuse(agent_id, step, receipt_id, schema_file)
            if reused is not None:
                if reservation_key:
                    self.budget.release(reservation_key)
                return reused
        watched = self._context_check(agent_id, payload, step, m)
        if reservation_key:   # the call's cost is already held under the cap
            self._spend_review(agent_id, step, 0.0)
        else:                 # worst case for this call: its input (count, else bound) and every output token
            self._spend_review(agent_id, step, self.budget.cost(
                m.model, watched["input_counted"] or watched["input_byte_bound"], watched["output_reserve"]) or 0.0)
        try:
            if staged:   # the staged pilot's approved holds cover exactly one attempt per call
                extra = {"reservation_key": reservation_key, "repair_limit": 0} if reservation_key else {}
                extra["truncation_retries"] = 0
            else:        # every send, a truncation retry and a repair included, is reserved by the guard below
                extra = ({"reservation_key": reservation_key,
                          "repair_limit": int(self.cfg["loops"].get("reserved_call_repairs", 0))}
                         if reservation_key else {})
                extra["dispatch_guard"] = self._call_guard(agent_id, step, reservation_key)
                from .job_ledger import Ledger
                extra["ledger"] = Ledger(self.dir)
                extra["request_id"] = receipt_id
            if repair_limit is not None:extra['repair_limit']=repair_limit
            if truncation_retries is not None:extra['truncation_retries']=truncation_retries
            if repair_from is not None:extra['repair_from']=repair_from
            if pilot.enabled(self):
                from .synthesis_registry import fingerprint
                request_id=fingerprint([agent_id,payload,dataclasses.asdict(m),schema_file,pilot.identity(self,pilot.stage_for(self,agent_id))['versions']])
                cached=self.load('pilot_requests.json',{}).get(step)
                if cached:
                    if cached['request']!=request_id:raise Pause('Changed paid request identity; review and use a new step after approval')
                    output=self.dir/'outputs'/f'{step}.json'
                    if output.exists():
                        from .agents.base import validate
                        accepted=json.loads(output.read_text(encoding='utf-8'));validate(agent_id,accepted,schema_file)
                        if cached.get('output_hash') and cached['output_hash']!=fingerprint(accepted):raise Pause('Accepted output changed')
                        return accepted
                    if any(e['step']==step for e in self.budget.entries()) or any(k.startswith('pilot-'+request_id[:24]) for k in self.budget.reservations()):
                        raise Pause('Interrupted paid request: reconcile provider billing/accepted output before retry')
                requests=self.load('pilot_requests.json',{})
                requests[step]={'request':request_id}
                pilot.atomic(self.data('pilot_requests.json'),requests)
                def guard(attempt,system,message,model):
                    try: pilot.require(self,agent_id,financial=False)
                    except pilot.AuthorizationRequired as exc:raise Pause(str(exc)) from exc
                    if reservation_key:
                        if agent_id in {"A07-SYN", "A08-OL", "A09-WRI", "A10-RV", "A11-RC", "A12-EDI"}:
                            from .writing_admission import quote_call, require_hold
                            required = quote_call(system, message, model, self.cfg['admission'], self.budget)
                            require_hold(self.budget, reservation_key, required)
                        meta=self.load('pilot_reservations.json',{}).get(reservation_key,{})
                        if meta.get('scope')!=pilot.stage_for(self,agent_id) or meta.get('authorization')!=(self.load('pilot_'+meta.get('scope','')+'.json') or {}).get('fingerprint'):
                            raise Pause('Reservation lacks current stage authorization')
                        return reservation_key
                    from .synthesis_registry import offline_tokens
                    tokens=offline_tokens(system)+offline_tokens(message)
                    from .admission import output_reserve
                    amount=self.budget.cost(model.model,0,output_reserve(model,self.cfg['admission']),0,0,tokens)
                    key='pilot-'+request_id[:24]+'-'+str(attempt)
                    if key in self.budget.reservations():raise Pause('Unsettled pilot request; reconcile before retry')
                    self._spend_review(agent_id,step,amount)
                    if not self._reserve(key,amount,agent_id,'pilot per-attempt reservation',steps=[step])[0]:
                        raise BudgetExceeded('Pilot request exceeds remaining $35 authorization')
                    return key
                extra['dispatch_guard']=guard
            if not staged:
                extra["loops"] = self.cfg["loops"]
            out = run_agent(agent_id, payload, self.dir, step, self.budget, self.prov, model=m,
                            schema_file=schema_file, **extra)
        except RefusalError as e:
            model_record.add(e.model, agent_id, self.family(), "REFUSED", self.id, step, e.category)
            raise
        except Exception as e:   # noqa: BLE001 — only to turn one named state into a pause; everything else re-raises
            from .job_ledger import AmbiguousDispatch
            if isinstance(e, AmbiguousDispatch):
                raise Pause(str(e)) from e
            raise
        if pilot.enabled(self):
            requests=self.load('pilot_requests.json',{})
            requests[step]['output_hash']=fingerprint(out)
            if agent_id in pilot.SECOND:
                from .admission import input_bound, output_reserve
                s=self.cfg['forecast']['scenarios']['baseline']
                forecast_usd=self.budget.cost(m.model,int(input_bound(build_system_prompt(agent_id),payload)/float(s['bytes_per_token'])),
                                              int(output_reserve(m,self.cfg['admission'])*float(s['output'])))
                requests[step].update(agent=agent_id,projection_basis=pilot.work_basis(self),forecast_usd=forecast_usd)
            pilot.atomic(self.data('pilot_requests.json'),requests)
        if receipt_id is not None:
            self._receipt_save(step, receipt_id, out, m)
        self._context_actual(watched)
        model_record.add(m.model, agent_id, self.family(), "COMPLETED", self.id, step)
        self.last_model = m.model
        if self.budget.should_warn():
            notify.send("budget_warning", f"Run {self.id}: 80% of budget used", self.budget.summary_text())
        return out

    # --- receipts: what was paid for and accepted, so a resume reuses it ---------------------------------
    def _receipt_request(self, agent_id: str, payload: dict, m, schema_file: str | None) -> str:
        """Identity of a request for reuse: agent, payload, vendor and model, system prompt and schema. Output caps
        and effort are left out: an output accepted under one cap is the same accepted output under another."""
        from .agents.registry import AGENTS
        from .synthesis_registry import fingerprint
        schema = (SCHEMAS_DIR / (schema_file or AGENTS[agent_id].schema_file)).read_bytes()
        from .extraction_mode import active, identity
        basis=[agent_id, payload, m.provider, m.model,
               hashlib.sha256(build_system_prompt(agent_id).encode()).hexdigest(),hashlib.sha256(schema).hexdigest()]
        if active(agent_id):basis.append(identity())
        return fingerprint(basis)

    def _receipt_reuse(self, agent_id: str, step: str, request_id: str, schema_file: str | None):
        """The accepted output saved for this step, if its receipt matches this request (or it is a researcher's
        repair import, which binds to the first request that asks for the step). None: the call must be made."""
        from .agents.base import validate
        from .synthesis_registry import fingerprint
        receipts = self.load("receipts.json", {})
        rec = receipts.get(step)
        path = self.dir / "outputs" / f"{step}.json"
        if not rec or not path.exists():
            return None
        if rec.get("imported") and not rec.get("request"):
            rec["request"] = request_id
            receipts[step] = rec
            pilot.atomic(self.data("receipts.json"), receipts)
        if rec.get("request") != request_id:
            return None   # the input, prompt, schema or model changed: this is a different request
        accepted = json.loads(path.read_text(encoding="utf-8"))
        if rec.get("output_sha256") != fingerprint(accepted):
            raise Pause(f"{step}: the saved output no longer matches its receipt (data/receipts.json). It was edited "
                        "after acceptance; restore it or import it with `litreview repair-import`.")
        try:
            validate(agent_id, accepted, schema_file)
            from .extraction_mode import active
            if active(agent_id):
                # The receipt request already binds the original payload; run_many also rechecks its source.
                if not (self.dir/'input/extraction_generation.json').exists():raise ValueError('Missing ordinary-mode receipt identity')
        except Exception as exc:   # noqa: BLE001 — jsonschema raises several families; any means "not reusable"
            raise Pause(f"{step}: the saved output fails its current schema ({str(exc)[:200]}). Repair it with "
                        "`litreview repair-import` or delete its receipt to pay for a fresh call.") from exc
        self.prov.tool_run("receipt_reuse", step, {"request": request_id[:16], "imported": bool(rec.get("imported")),
                                                   "paid_again": False})
        return accepted

    def _receipt_save(self, step: str, request_id: str, out: dict, m) -> None:
        from .synthesis_registry import fingerprint
        receipts = self.load("receipts.json", {})
        receipts[step] = {"request": request_id, "output_sha256": fingerprint(out), "model": m.model,
                          "provider": m.provider, "accepted_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        pilot.atomic(self.data("receipts.json"), receipts)

    def _fresh_synthesis_reservation(self, agent, step, key, blocked):
        from .job_ledger import Ledger
        match = re.fullmatch(r"A07-SYN_job([0-9a-f]{16})_(PLAN|FINAL|(?:GROUP_G|RECONCILE_)[0-9]{4}_LOOKUP[0-9]+)", step)
        return (agent == "A07-SYN" and match and key == f"a07-{match[1]}-{match[2]}"
                and blocked == [key] and getattr(self, "_active_synthesis_reservation", None) == key
                and not Ledger(self.dir).events(step)
                and not any(e.get("reservation_key") == key for e in self.budget.entries()))

    def _call_guard(self, agent_id: str, step: str, reservation_key: str | None):
        """reserve() before every send on the standard path. The first send uses the caller's reservation when it
        made one; every other send (a first send with none, a truncation retry, a repair) holds its own cold worst
        case, input at the cache-write rate and output at the cap, and is refused if that does not fit."""
        from .synthesis_registry import fingerprint, offline_tokens
        from .writing_admission import worst_case_usd

        def guard(attempt, system, message, model):
            if attempt == 0 and reservation_key:
                return reservation_key
            reserve = (self.cfg.get("admission") or {}).get("reasoning_reserve_tokens") or {}
            out_tokens = int(model.max_tokens) + int(reserve.get(model.provider) or 0)
            usd = worst_case_usd(self.budget, model, offline_tokens(system) + offline_tokens(message), out_tokens)
            if getattr(self, "_reconciliation_approval", None) and "_RECONCILE_" in step:
                from .reconciliation_paging import body_bytes, generation_body
                body = generation_body(system, message, model, model.max_tokens, model.cache_system, model.cache_ttl)
                input_upper = len(body_bytes(body)) + 2048
                if input_upper + out_tokens > self.cfg["synthesis"]["context_ceiling_tokens"]:
                    raise Pause("reconciliation repair exceeds the configured context limit")
                usd = self.budget.cost(model.model, 0, out_tokens, 0, 0, input_upper)
            if usd is None:
                raise UnpricedModel(model.model)
            key = "call-" + fingerprint([step, attempt, model.model, model.max_tokens])[:24]
            if key in self.budget.reservations():
                raise Pause(f"unsettled reservation {key} for {step}: a previous attempt ended without a logged "
                            "response. Reconcile provider billing (scripts/reconcile_billing.py) before retrying.")
            ok, available = self._reserve(key, usd, agent_id, "pre-call reservation", steps=[step])
            if not ok:
                raise BudgetExceeded(f"{agent_id} {step}: this call reserves ${usd:.2f}; only ${available:.2f} "
                                     f"remains under the ${self.budget.cap:.2f} cap")
            return key
        return guard

    def _context_check(self, agent_id: str, payload: dict, step: str, m) -> dict:
        """(input + reserved output) / window for this exact request (context_watch.py), logged with both the byte
        bound and the provider's count where available. WARN: logged and notified. REVIEW: stops for the
        researcher's approval of this request (CP_CONTEXT), unless it is already recorded. Operational defaults,
        not reliability guarantees; the hard admission ceilings are unchanged."""
        from . import context_watch
        from .agents.base import build_system_prompt, user_parts
        from .synthesis_registry import fingerprint
        system, user = build_system_prompt(agent_id), user_parts(payload, m.cache_payload)
        counting = ((self.cfg.get("context_utilisation") or {}).get("provider_count") or {}).get(m.provider)
        rec = context_watch.measure(agent_id, step, system, user, payload, m, self.cfg,
                                    context_watch.anthropic_counter if counting else None)
        if rec["level"] == "REVIEW":
            rec["review_fingerprint"] = fingerprint({"agent": agent_id, "step": step, "model": m.model,
                                                     "max_tokens": m.max_tokens, "payload": payload})
            rec["approved"] = checkpoints.review_approved(self.dir, "CP_CONTEXT", rec["review_fingerprint"]) is not None
        self.prov.tool_run("context_utilisation", step, rec)
        if rec["level"] == "WARN":
            notify.send("context_warning", f"Run {self.id}: {step} uses {rec['utilisation']:.0%} of {m.model}'s window",
                        f"Basis {rec['basis']}; warn at {rec['thresholds']['warn']:.0%}, review at "
                        f"{rec['thresholds']['review']:.0%} (operational defaults, not reliability guarantees).")
        if rec["level"] == "REVIEW" and not rec["approved"]:
            checkpoints.write_context_review(self.dir, rec["review_fingerprint"], {
                k: rec[k] for k in ("agent", "model", "step", "utilisation", "window", "basis", "input_byte_bound",
                                    "input_counted", "output_reserve", "utilisation_byte_bound", "utilisation_counted")}
                | {"warn_threshold": rec["thresholds"]["warn"], "review_threshold": rec["thresholds"]["review"]})
            self.pause_for_checkpoint("CP_CONTEXT")
        return rec

    def _spend_review(self, agent_id: str, step: str, request_usd: float) -> None:
        """The run's spend review point (run.spend_review_usd): before the call that would take committed spend
        (spent + reserved + this call's worst case not yet reserved) past it, the run stops and asks (CP_SPEND,
        recorded in provenance); after approval it continues to the hard cap, which never moves."""
        from .synthesis_registry import fingerprint
        legacy = (self.cfg.get("run") or {}).get("spend_review_usd")
        points = sorted(set(getattr(self.budget, "review_points", None) or [])) \
            if getattr(self.budget, "profile", None) not in (None, "pilot", "sample") else \
            ([float(legacy)] if legacy is not None else [])
        spent, reserved = self.budget.spent(), self.budget.reserved()
        after = spent + reserved + float(request_usd)
        point = digest = None
        for candidate in points:   # the lowest point passed and not yet approved
            if after <= candidate:
                break
            d = fingerprint({"run": self.id, "spend_review_usd": float(candidate)})
            if not checkpoints.review_approved(self.dir, "CP_SPEND", d):
                point, digest = candidate, d
                break
        if point is None:
            return
        detail = {"agent": agent_id, "step": step, "spent_usd": round(spent, 4), "reserved_usd": round(reserved, 4),
                  "request_usd": round(float(request_usd), 4), "committed_after_usd": round(after, 4),
                  "review_point_usd": float(point), "cap_usd": self.budget.cap}
        self.prov.tool_run("spend_review_point", step, detail)
        checkpoints.write_spend_review(self.dir, digest, detail)
        self.pause_for_checkpoint("CP_SPEND")

    def _context_actual(self, rec: dict) -> None:
        """After the call: utilisation from the provider-reported input tokens (calibrates the bound and count)."""
        from . import context_watch
        entry = next((e for e in reversed(self.budget.entries()) if e.get("step") == rec["step"]), None)
        act = context_watch.actual(rec, entry)
        if act:
            self.prov.tool_run("context_utilisation_actual", rec["step"], act)

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
        from . import preflight
        from .job_ledger import RunLock
        preflight.require_start(self.dir)   # redirected provider endpoints or an archived run: nothing starts
        with RunLock(self.dir) as lock:     # two processes never dispatch for one run
            if lock.took_over:
                self.prov.tool_run("run_lock_takeover", "run", lock.took_over)
            return self._run(until)

    def _run(self, until: str | None = None) -> str:
        st = self.state()
        corpus_policy.resolve(self)
        st["status"] = "RUNNING"
        self.save_state(st)
        try:
            self.preflight_routing()
            while st["stage"] != "done":
                if until and st["stage"] == until:
                    raise Pause(f"stopped before {until} (--until)")
                if pilot.enabled(self):
                    try:
                        agent='A08-OL' if STAGES.index(st['stage'])>STAGES.index('cp3') else 'A02-SP'
                        pilot.require(self,agent)
                    except pilot.AuthorizationRequired as exc:raise Pause(str(exc)) from exc
                handler = getattr(self, f"stage_{st['stage']}")
                nxt = handler(st)
                if pilot.enabled(self) and nxt=='outline':
                    try:pilot.require(self,'A08-OL')
                    except pilot.AuthorizationRequired as exc:
                        pilot.partial(self,str(exc))
                        raise Pause(str(exc)) from exc
                st = self.state() | {"stage": nxt}
                self.save_state(st)
                if pilot.enabled(self):
                    # Recalculate from accepted work at every completed stage. Reprojection is not approval.
                    financial_stage=pilot.STAGE_2 if STAGES.index(nxt)>STAGES.index('cp3') else pilot.STAGE_1
                    try:
                        projection=pilot.project(self,financial_stage)
                        self.save('pilot_live_projection.json',projection)
                    except pilot.AuthorizationRequired as exc:
                        if financial_stage==pilot.STAGE_2:pilot.partial(self,str(exc))
                        raise Pause(str(exc)) from exc
                    if nxt=='outline':
                        try:pilot.require(self,'A08-OL')
                        except pilot.AuthorizationRequired as exc:raise Pause(str(exc)) from exc
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
            "journal_profile": pilot.journal(self),
            "corpus_policy": corpus_policy.resolve(self),
            "human_scope_configuration": json.loads((inp / "human_scope_configuration.json").read_text(encoding="utf-8")) if (inp / "human_scope_configuration.json").exists() else None,
            "theme_guidance": self.cfg.get("themes", {"primary_min": 5, "primary_max": 8}),
            "revision_feedback": feedback,
            **self._outline_input(),
        }, step=f"A02-SP_scope_v{self.counter(st, 'scope')}")
        spec["corpus_policy"] = corpus_policy.resolve(self)
        from . import run_spec
        outline, _ = run_spec.load(self.dir)
        if outline:   # the researcher's subsections are the themes; A02's proposal is kept for the record only
            spec["theme_framework_proposed_by_A02"] = spec.get("theme_framework")
            spec["theme_framework"] = run_spec.framework_from_outline(outline)
            spec["researcher_outline"] = run_spec.outline_brief(outline)
        self.save("spec.json", spec)
        return "cp1"

    def stage_cp1(self, st: dict) -> str:
        decision = checkpoints.approved(self.dir, "CP1")
        if not decision:
            checkpoints.write_cp1(self.dir, self.load("spec.json"))
            self.pause_for_checkpoint("CP1")
        spec = self.load("spec.json")
        spec["researcher_decision"] = decision
        if decision.get('scope_guide'):
            spec['approved_scope_guide'] = decision['scope_guide']
            spec['central_question'] = decision['scope_guide']['organizing_question']
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

    def _decision_identity(self, agent_id: str) -> dict:
        """{} when no applied decision can reach this agent (identities of runs without decisions are unchanged);
        otherwise the decisions' fingerprint, so a job whose turns depend on each other is rebuilt when one changes."""
        from . import decisions
        if not [d for d in decisions.active(self.dir)
                if not d["applies_to"].get("agents") or agent_id in d["applies_to"]["agents"]]:
            return {}
        return {"applied_decisions": decisions.fingerprint(self.dir, agent_id)}

    def decide(self, kind: str, instruction: str, applies_to: dict, author: str, checkpoint: str = "",
               reason: str = "", decision_id: str | None = None, withdraw: bool = False) -> dict:
        """Record an applied researcher decision (decisions.py) and log it as a human decision."""
        from . import decisions
        entry = decisions.add(self.dir, kind, instruction, applies_to, author, checkpoint, reason, decision_id, withdraw)
        self.prov.human_decision("APPLIED_DECISION", {k: entry[k] for k in ("decision_id", "version", "status", "kind",
                                                                           "instruction", "applies_to", "author")},
                                 reason)
        return entry

    def revise_framework(self, primary_themes: list[dict], author: str, note: str) -> dict:
        """The one way a theme is relabelled, redefined, added or removed after CP1: a new framework version.
        Everything built on the framework carries it in its input, so the affected identities regenerate; theme
        records are marked stale so the theme pass is rebuilt before synthesis."""
        if not (author or "").strip() or not (note or "").strip():
            raise ValueError("a framework revision needs its author and the reason for the change")
        fw = self.load("theme_framework.json")
        if not fw:
            raise ValueError("this run has no approved theme framework yet (it is created at CP1)")
        ids = [t.get("theme_id") for t in primary_themes]
        if not ids or any(not i for i in ids) or len(ids) != len(set(ids)):
            raise ValueError("every primary theme needs a unique theme_id")
        new = theme_framework.revise(fw, primary_themes, "RESEARCHER_REVISION", f"{author.strip()}: {note.strip()}")
        self.save("theme_framework.json", new)
        if self.data("theme_records.json").exists():
            self.save("theme_records_stale.json", sorted(set(self.load("theme_records.json", {}))
                                                         | set(self.load("theme_records_stale.json", []))))
        self.prov.human_decision("THEME_FRAMEWORK", {"version": new["version"], "author": author.strip(),
                                                     **{k: new["history"][-1][k] for k in ("added", "removed")}}, note)
        return new

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

    def _agent_human_review(self, agent, step, output):
        if output.get("status") != "NEEDS_HUMAN_INPUT":
            return
        from .synthesis_registry import fingerprint
        digest = fingerprint([agent, step, output, self.load("spec_approved.json"), corpus_policy.resolve(self)])
        if checkpoints.review_approved(self.dir, "CP_AGENT_REVIEW", digest):
            return
        checkpoints.write_agent_review(self.dir, digest, agent, step, output)
        self.pause_for_checkpoint("CP_AGENT_REVIEW")

    def stage_search(self, st: dict) -> str:
        spec = self.load("spec_approved.json")
        sources = enabled_sources()
        rcfg = self.cfg["retrieval"]
        budget = {"max_records_total": rcfg["max_records_total"], "max_records_per_family": rcfg["max_records_per_family"]}
        from .approved_scope import guide, search_plan
        if guide(self):
            plan = search_plan(self, spec, sources, budget)
        else:
            plan = self.agent("A03-LM", {"mode": "PLAN", "review_spec": spec, "sources_enabled": sources,
                                         "budget": budget, "corpus_policy": corpus_policy.resolve(self),
                                         "corpus_policy_fingerprint": self.state().get("corpus_policy_fingerprint"),
                                         **self._outline_input()}, step="A03-LM_plan")
        self.save("search_plan.json", plan)
        self._agent_human_review("A03-LM", "PLAN", plan)
        results = self._execute_plan(plan, sources)
        all_results = list(results)
        seeds = spec.get("search_seeds", {}).get("seed_papers", [])
        for i in range(int(self.cfg["loops"]["max_search_repairs"])):
            report = self._execution_report(plan, results, seeds)
            if not report["problems"]:
                break
            if guide(self):
                plan = search_plan(self, spec, sources, budget, mode='REPAIR', previous=plan, execution=report, repair_number=i+1)
            else:
                plan = self.agent("A03-LM", {"mode": "REPAIR", "review_spec": spec, "sources_enabled": sources,
                                             "budget": budget, "previous_plan": plan,
                                             "execution_report": report["families"],
                                             "seed_recall": report["seed_recall"], "corpus_policy": corpus_policy.resolve(self),
                                             **self._outline_input()}, step=f"A03-LM_repair{i + 1}")
            self.save("search_plan.json", plan)
            self._agent_human_review("A03-LM", f"REPAIR{i + 1}", plan)
            results = self._execute_plan(plan, sources)
            all_results.extend(results)
        # Repairs do not discard independently retrieved records or query yields.
        all_results = list({(r['source'], r['family_id'], r['query']): r for r in all_results}.values())
        self.save("search_plan.json", plan)
        all_records = [Record(**{k: v for k, v in r.items() if k in Record.__dataclass_fields__})
                       for res in all_results for r in res["records"]]
        records, stats = deduplicate(all_records)
        self.save("records.json", records)
        self.save("search_log.json", [{k: v for k, v in r.items() if k != "records"} for r in all_results])
        self.prov.tool_run("search+dedup", "search", stats)
        return "qualify"

    def _execute_plan(self, plan: dict, sources: dict) -> list[dict]:
        out = []
        # Preflight every query before dispatching even the first source request.
        families = plan.get("query_families", [])
        try:
            compiled = [compiled_queries(family) for family in families]
            for family, queries in zip(families, compiled):
                for source in family.get("sources", []):
                    corpus_policy.require_query(self, source, family, queries.get(source, ""))
        except ValueError as exc:
            raise Pause(str(exc)) from exc
        for fam, queries in zip(families, compiled):
            for src in fam.get("sources", []):
                if src not in sources or src not in queries:
                    continue
                maximum = min(int(fam.get("max_records") or 200), self.cfg["retrieval"]["max_records_per_family"])
                cache_key = hashlib.sha256(json.dumps([src, queries[src], fam["family_id"], maximum]).encode()).hexdigest()
                cached = self.load(f'search_results/{cache_key}.json')
                if cached is not None:
                    out.append(cached)
                    continue
                res = search(src, queries[src], fam["family_id"], maximum)
                try:
                    corpus_policy.require_records(self, [r.to_dict() for r in res.records])
                except ValueError as exc:
                    self.save("retrieval_boundary_error.json", {"source": src, "family_id": fam["family_id"],
                        "unexpected_pmids": [r.pmid for r in res.records if str(r.pmid) not in corpus_policy.fixed(self)]})
                    raise Pause(str(exc)) from exc
                entry = {"source": res.source, "family_id": res.family_id, "purpose": fam.get("purpose"),
                         "query": res.query, "hit_count": res.hit_count, "returned": len(res.records),
                         "section_ids": fam.get('section_ids', []), "searched_at": time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                         "error": res.error, "records": [r.to_dict() for r in res.records]}
                self.save(f'search_results/{cache_key}.json', entry)
                out.append(entry)
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
        if corpus_policy.fixed(self):
            self.prov.tool_run("citation_expansion_skipped", "expand", {"reason": "FIXED_CORPUS"})
            return "cp2"
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
        try:
            corpus_policy.require_records(self, records, internal_ids=True)
        except ValueError as exc:
            raise Pause(str(exc)) from exc
        reviews = self.load("screening_review.json", {})
        for bid, review in reviews.items():
            self._agent_human_review("A04-CQ", bid, review)
        identities = corpus_policy.registry(records, corpus_policy.fixed(self))
        prior_registry = self.load("corpus_membership.json")
        if prior_registry is not None and prior_registry != identities:
            from .approved_scope import registry_extension
            if corpus_policy.fixed(self) or not registry_extension(prior_registry, identities):
                raise Pause("Canonical corpus mapping changed; explicit human identity resolution required")
            self.save("corpus_membership.json", identities)
        if prior_registry is None:
            self.save("corpus_membership.json", identities)
        quals: dict[str, dict] = {q["record_id"]: q for q in self.load("qualifications.json", [])}
        fw = self.load("theme_framework.json")
        todo = [r for r in records if r["record_id"] not in quals]
        size = int(self.cfg["loops"]["cq_batch_size"])
        fields = ("record_id", "title", "abstract", "authors", "year", "venue", "publication_type", "doi",
                  "pmid", "pmcid", "nct_id", "is_preprint", "query_family_ids", "expansion")
        for i in range(0, len(todo), size):
            batch = [{**{k: r.get(k) for k in fields},
                      "content_level": "ABSTRACT" if r.get("abstract") else "METADATA_ONLY"} for r in todo[i:i + size]]
            # numbered across resumes, so a rerun batch never overwrites an earlier batch's outputs
            bid = f"B{self.counter(self.state(), 'cq_batch'):03d}"
            out = self.agent("A04-CQ", {"review_spec": spec, "theme_framework": fw, "batch_id": bid,
                                        "records": batch, "identifier_registry": identities, **self._outline_input()},
                             step=f"A04-CQ_{bid}")
            reviews[bid] = {k: out.get(k) for k in ("status", "warnings", "limitations", "human_review_queue", "criteria_defects")}
            reviews[bid].update(origin_agent="A04-CQ", output_step=f"A04-CQ_{bid}", input_record_ids=[r["record_id"] for r in batch])
            reviews[bid]["identifier_registry"] = identities
            self.save("screening_review.json", reviews)
            known = {x["record_id"] for x in batch}
            returned = [q.get("record_id") for q in out.get("qualifications", [])]
            references = [q.get("record_id") for q in out.get("human_review_queue", []) if q.get("record_id")]
            if (any(i not in known for i in returned) or len(returned) != len(set(returned))
                    or any(i not in {r["record_id"] for r in records} for i in references)):
                raise Pause("A04 identifier integrity: record_id must match canonical registry; no PMID substitution")
            if corpus_policy.fixed(self) and any(q.get("exclusion_code") == "OUTSIDE_FIXED_CORPUS" for q in out.get("qualifications", [])):
                reviews[bid]["identifier_conflict"] = "Canonical fixed-corpus member incorrectly classified OUTSIDE_FIXED_CORPUS"
                self.save("screening_review.json", reviews)
                raise Pause("A04 canonical corpus membership contradicts classification; human correction required")
            got = {q["record_id"]: q for q in out.get("qualifications", [])}
            for r in batch:  # nothing may disappear: any record without a disposition is flagged
                quals[r["record_id"]] = {**(got.get(r["record_id"]) or {
                    "record_id": r["record_id"], "disposition": "UNRESOLVED_HUMAN_REVIEW",
                    "reason": "Agent returned no disposition for this record.", "themes": [], "flags": []}),
                    **self._screener()}
                quals[r["record_id"]] = theme_framework.normalize(quals[r["record_id"]], fw) \
                    if quals[r["record_id"]].get("disposition") == "QUALIFIED" else quals[r["record_id"]]
                if corpus_policy.fixed(self):
                    claimed = quals[r["record_id"]].get("in_fixed_corpus")
                    if claimed is False:
                        reviews[bid].setdefault("membership_claim_conflicts", []).append({"record_id": r["record_id"],
                            "pmid": str(r["pmid"]), "model_claim": False, "canonical_membership": True})
                        self.save("screening_review.json", reviews)
                    quals[r["record_id"]]["in_fixed_corpus"] = True
                    quals[r["record_id"]]["membership_source"] = "PERSISTED_RUN_POLICY"
            from .approved_scope import extend_screened_themes
            extend_screened_themes(self, quals, fw)
            self.save("qualifications.json", list(quals.values()))
            self._agent_human_review("A04-CQ", bid, reviews[bid])
        # Level 2: full text for records the agent could not decide from the abstract
        by_id = {r["record_id"]: r for r in records}
        need_ft = [q["record_id"] for q in quals.values() if q["disposition"] == "UNRESOLVED_FULL_TEXT_REQUIRED"
                   and not q.get("_fulltext_checked")]
        for rid in need_ft:
            if corpus_policy.fixed(self).get(str(by_id[rid].get("pmid"))) == "ABSTRACT":
                continue
            if corpus_policy.fixed(self).get(str(by_id[rid].get("pmid"))) == "FULL_TEXT":
                try:
                    corpus_policy.require_source(self, by_id[rid])
                    sections = self.load(f"fulltext/{rid}.json")
                    source = self.load(f"fulltext_provenance/{rid}.json")
                    if sections:
                        verify_cached_source(by_id[rid], sections, source)
                    else:
                        sections, source = fetch_verified_sections(by_id[rid])
                except ValueError as exc:
                    raise Pause(f"Required verified full text unavailable for {rid}: {exc}") from exc
                self.save(f"fulltext/{rid}.json", sections)
                self.save(f"fulltext_provenance/{rid}.json", source)
            else:
                try:
                    sections = self._checked_fulltext(by_id[rid])
                except FullTextUnavailable as exc:
                    self.save(f"identity_quarantine/{rid}_retrieval.json", {
                        "record": by_id[rid], "reason": str(exc), "level_used": "ABSTRACT"})
                    sections = {}
            quals[rid]["_fulltext_checked"] = True
            if not sections:
                continue
            out = self.agent("A04-CQ", {"review_spec": spec, "batch_id": f"FT-{rid}", "records": [
                {**{k: by_id[rid].get(k) for k in fields}, "content_level": "FULL_TEXT", "sections": sections}],
                "identifier_registry": identities, **self._outline_input()}, step=f"A04-CQ_FT_{rid}")
            bid = f"FT-{rid}"
            reviews[bid] = {k: out.get(k) for k in ("status", "warnings", "limitations", "human_review_queue", "criteria_defects")}
            reviews[bid].update(origin_agent="A04-CQ", output_step=f"A04-CQ_FT_{rid}", input_record_ids=[rid])
            reviews[bid]["identifier_registry"] = identities
            self.save("screening_review.json", reviews)
            returned = out.get("qualifications", [])
            if len(returned) != 1 or returned[0].get("record_id") != rid:
                raise Pause("A04 full-text identifier integrity mismatch")
            if corpus_policy.fixed(self) and returned[0].get("exclusion_code") == "OUTSIDE_FIXED_CORPUS":
                raise Pause("A04 canonical corpus membership contradicts full-text classification")
            quals[rid] = {**returned[0], "_fulltext_checked": True, **self._screener()}
            if corpus_policy.fixed(self):
                if returned[0].get("in_fixed_corpus") is False:
                    reviews[bid]["membership_claim_conflicts"] = [{"record_id": rid, "canonical_membership": True, "model_claim": False}]
                    self.save("screening_review.json", reviews)
                quals[rid].update(in_fixed_corpus=True, membership_source="PERSISTED_RUN_POLICY")
            from .approved_scope import extend_screened_themes
            extend_screened_themes(self, quals, fw)
            self.save("qualifications.json", list(quals.values()))
            self._agent_human_review("A04-CQ", bid, reviews[bid])
        from .approved_scope import extend_screened_themes
        extend_screened_themes(self, quals, fw)
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
                                  framework=self.load("theme_framework.json"),
                                  review_issues={"search_plan": {k: (self.load("search_plan.json") or {}).get(k)
                                      for k in ("status", "warnings", "limitations")},
                                      "screening": self.load("screening_review.json", {})},
                                  identities=corpus_policy.registry(self.load("records.json"), corpus_policy.fixed(self)),
                                  source_readiness={"required": corpus_policy.fixed(self),
                                      "materialization_stage": "extract before A05 dispatch",
                                      "verified_sources": self.load("source_readiness.json", {})})
            self._cp2_costs(quals)
            self._retraction_check([r for r in self.load("records.json")], "cp2")
            self._propose_selection(quals)
            self.pause_for_checkpoint("CP2")
        checkpoints.require_cp2_current(self.dir)
        self._framework_update(decision, "CP2")
        by_id = {r["record_id"]: r for r in self.load("records.json")}
        report = self._retraction_check([by_id[rid] for rid in decision["selected_record_ids"]], "cp2_selection")
        excused = decision.get("retraction_exceptions") or {}
        retracted = [r["record_id"] for r in report["retracted"] if not str(excused.get(r["record_id"]) or "").strip()]
        if retracted:
            raise Pause(f"CP2 selection includes retracted paper(s) {', '.join(retracted)} (Crossref; see "
                        "checkpoints/CP2_retractions.md). Deselect them, or record a reason for citing each one "
                        'under "retraction_exceptions" in CP2_approved.json, then approve CP2 again.')
        quals = {q["record_id"]: q for q in self.load("qualifications.json")}
        corpus = []
        from . import run_spec
        _, manifest = run_spec.load(self.dir)
        outline, _ = run_spec.load(self.dir)
        if outline and not manifest:   # a discovery run: check provisionally, show, and only then freeze
            review = self._cp2_review_selection(decision["selected_record_ids"], by_id, quals)
            self._write_cp2_selection_review(review, approved=True)
            if review["problems"] or decision.get("selection_review_fingerprint") != review["fingerprint"]:
                self.save("corpus_manifest.provisional.json", review["manifest"])
                self.save("cost_projection.provisional.json", review["projection"])
                why = ("; ".join(review["problems"]) + ". Change the marks in checkpoints/CP2_records.csv, then approve CP2 again "
                       "(search and screening are kept; nothing is frozen)") if review["problems"] else \
                    ("the selection's actual reading levels and its revised projection are now in checkpoints/CP2_review.md "
                     "(Selection under review). Read them, then approve CP2 again to freeze this corpus")
                raise Pause(f"CP2 selection not frozen: {why}.")
            self.save("cost_projection.json", review["projection"])
            self.prov.tool_run("cost_projection", "cp2", {k: review["projection"][k] for k in
                                                          ("projected_total_usd", "cap_usd", "verdict", "papers")})
            self._derive_stage_caps(review["projection"])
            manifest = self._freeze_corpus(review["manifest"])
            self.save("selected_corpus.json", self._corpus_records(decision["selected_record_ids"], by_id, quals, manifest))
            return "extract"
        if manifest:
            mismatch = run_spec.selection_problems(manifest, [by_id[rid] for rid in decision["selected_record_ids"]])
            if mismatch:
                raise Pause("CP2 selection differs from the corpus manifest (input/corpus_manifest.json): "
                            + "; ".join(mismatch) + ". The manifest is the corpus: fix the selection, or change the "
                            "manifest in a new run.")
        corpus = self._corpus_records(decision["selected_record_ids"], by_id, quals, manifest, decision)
        # the projection decides here, where changing the selection is still cheap
        if pilot.enabled(self):
            try:proj=pilot.project(self,pilot.STAGE_1,records=corpus)
            except pilot.AuthorizationRequired as exc:raise Pause(str(exc)) from exc
        else:
            proj = cost_projection.for_selection(cost_projection.load_rates(), corpus, self.dir, self.budget, self.route,
                                                 self.cfg)
        self.save("cost_projection.json", proj)
        self.prov.tool_run("cost_projection", "cp2", {k: proj[k] for k in ("projected_total_usd", "cap_usd", "verdict", "papers")})
        if proj["verdict"] == "WITHIN_CAP":
            self._derive_stage_caps(proj)
        if proj["verdict"] != "WITHIN_CAP":
            raise Pause(f"CP2 selection of {len(corpus)} papers is projected at ${proj['projected_total_usd']:.2f}, over "
                        f"the ${proj['cap_usd']:.2f} cap (data/cost_projection.json). Deselect papers or raise the cap, "
                        "then approve CP2 again.")
        self.save("selected_corpus.json", corpus)
        return "extract"

    def accounts(self, proj: dict | None = None, caps: dict | None = None) -> dict:
        """The money in one view: actual discovery and screening spend, prior spend carried into the run (the smoke
        test), spend so far, the projection of what is ahead (PROVISIONAL), the retry and repair allowance, the
        combined maximum exposure, the hard cap, and the projected spend by provider."""
        proj = proj if proj is not None else (self.load("cost_projection.json") or {})
        caps = caps if caps is not None else self.load("stage_caps.json")
        entries = self.budget.entries()
        spent_by = lambda agents: sum(e["cost_usd"] or 0.0 for e in entries if e["agent"] in agents)   # noqa: E731
        projected = float(proj.get("projected_remaining_usd", proj.get("projected_total_usd")) or 0.0)
        caps_total = float((caps or {}).get("total_usd") or 0.0)
        allowance = max(0.0, caps_total - sum(float(v) for v in ((caps or {}).get("projected_usd") or {}).values()))
        by_provider: dict[str, float] = {}
        for line in proj.get("lines", []):
            agent = line["stage"] if line.get("stage") in self.cfg["agents"] else \
                "A05-KE" if str(line.get("stage", "")).startswith(("A05", "A06")) else None
            if agent and line.get("usd") is not None:
                prov = config.agent_model(agent).provider
                by_provider[prov] = by_provider.get(prov, 0.0) + float(line["usd"])
        spent_now = self.budget.spent()
        nonstage = self.budget.prior_spend() + sum(e["cost_usd"] or 0.0 for e in entries
                                                    if not config.stage_group(e["agent"]))
        exposure = max(spent_now + projected, caps_total + nonstage) + self.budget.reserved()
        return {"discovery_and_screening_spent_usd": round(spent_by(("A02-SP", "A03-LM", "A04-CQ")), 4),
                "smoke_test_and_other_prior_spend_usd": round(self.budget.prior_spend(), 4),
                "smoke_test_spent_in_run_usd": round(spent_by(("smoke-test",)), 4),
                "unsettled_reservations_usd": round(self.budget.reserved(), 4),
                "spent_so_far_total_usd": round(spent_now, 4),
                "projected_remaining_usd_provisional": round(projected, 4),
                "retry_and_repair_allowance_usd": round(allowance, 4),
                "combined_maximum_exposure_usd": round(exposure, 4),
                "hard_cap_usd": self.budget.cap,
                "projected_by_provider_usd": {k: round(v, 4) for k, v in sorted(by_provider.items())},
                "spent_by_provider_usd": {p: round(sum(e["cost_usd"] or 0.0 for e in entries if e["provider"] == p), 4)
                                          for p in sorted({e["provider"] for e in entries})},
                "basis": "projection PROVISIONAL: October 2026 per-paper rates re-priced (older procedure) and assumed "
                         "output sizes; not a measured current-code cost. Provider allocation is estimated; the early "
                         "combined extraction/validation forecast is split equally between their providers"}

    def _corpus_records(self, selected_ids, by_id, quals, manifest=None, decision=None) -> list[dict]:
        from . import run_spec
        discovered = bool(manifest and manifest.get("generated_from") == "DISCOVERY_AND_SCREENING")
        corpus = []
        for rid in selected_ids:
            q = quals.get(rid, {})
            paper = (next(p for p in manifest["papers"] if p["record_id"] == rid) if discovered
                     else run_spec.paper_for(manifest, by_id[rid]))
            corpus.append({**by_id[rid], "role": q.get("role") or "PRIMARY", "themes": q.get("themes", []),
                           "subthemes": q.get("subthemes", []),
                           "tier": (paper["scientific_importance"] if paper else
                                    ((decision or {}).get("tier_overrides") or {}).get(rid) or q.get("proposed_tier")),
                           "flags": q.get("flags", []), "is_contrary_evidence": q.get("is_contrary_evidence"),
                           **({"manifest_paper_id": paper["paper_id"],
                               "intended_reading_level": paper["intended_reading_level"]} if paper else {}),
                           **({"corpus_source": "DISCOVERY", "source_access": paper.get("actual_access")} if discovered else {})})
        return corpus

    def _stage_caps_for(self, proj: dict) -> tuple[dict | None, str | None]:
        """(the stage sub-caps this projection needs, or None for a profile without derived caps; why they do not fit,
        or None). Profiles with `stage_caps_usd: derived` only. Saves nothing."""
        from .budget import derive_stage_caps
        settings = config.run_settings(self.state().get("profile"))
        if settings.get("stage_caps_usd") != "derived":
            return None, None
        stage_usd: dict[str, float] = {}
        for x in proj.get("lines", []):   # per-paper lines are named by work, not agent: map them to their stage
            agent = x.get("stage") if x.get("stage") in self.cfg["agents"] else \
                "A05-KE" if str(x.get("stage", "")).startswith(("A05", "A06")) else None
            if agent and x.get("usd") is not None:
                stage_usd[agent] = stage_usd.get(agent, 0.0) + float(x["usd"])
        for e in self.budget.entries():   # stages already paid for keep at least what they spent
            stage_usd[e["agent"]] = stage_usd.get(e["agent"], 0.0) + (e["cost_usd"] or 0.0)
        derived = derive_stage_caps(stage_usd, float(settings.get("recovery_allowance", 0.15)))
        derived["from_projection_created"] = proj.get("created")
        room = self.budget.cap - self.budget.prior_spend() - sum(
            e["cost_usd"] or 0.0 for e in self.budget.entries() if not config.stage_group(e["agent"])) - self.budget.reserved()
        problem = (f"the stage limits this projection needs add up to ${derived['total_usd']:.2f}, over the "
                   f"${room:.2f} the run's ${self.budget.cap:.2f} cap leaves after prior spend and retained reservations; reduce the selection"
                   if derived["total_usd"] > room else None)
        return derived, problem

    def _derive_stage_caps(self, proj: dict) -> None:
        """Save the sub-caps for an accepted projection (the checks ran before: _stage_caps_for)."""
        derived, problem = self._stage_caps_for(proj)
        if derived is None:
            return
        if problem:
            raise Pause(problem + " (data/stage_caps.json).")
        self.save("stage_caps.json", {**derived, "run_cap_usd": self.budget.cap})
        self.budget = BudgetTracker(self.dir)
        self.prov.tool_run("stage_caps", "cp2", derived)

    def _outline_input(self) -> dict:
        """{"researcher_outline": ...} for the agents before A08, in an outlined run; {} otherwise."""
        from . import run_spec
        outline, _ = run_spec.load(self.dir)
        from .approved_scope import enrich
        return enrich(self, 'A03-LM', {"researcher_outline": run_spec.outline_brief(outline)}) if outline else {}

    def _propose_selection(self, quals: list[dict]) -> None:
        """A discovery run: propose the corpus from the screening results and pre-mark it in CP2_records.csv. Only
        rows the researcher has not touched are marked; the researcher confirms or changes the selection."""
        from . import run_spec
        outline, manifest = run_spec.load(self.dir)
        if not outline or manifest:
            return
        limit = int((self.cfg.get("run_spec") or {}).get("max_papers", 15))
        proposal = run_spec.propose_selection(quals, self.load("records.json"), self.load("theme_framework.json"), limit)
        self.save("selection_proposal.json", {"max_papers": limit, "proposed": proposal,
                                              "rule": "qualified records, strongest tier first, greedy coverage of the "
                                                      "outline's subsections, one contrary-evidence paper if screening "
                                                      "found any; access level not considered"})
        checkpoints.prefill_cp2(self.dir, {p["record_id"]: p["reason"] for p in proposal}, limit)
        self.prov.tool_run("selection_proposal", "cp2", {"proposed": [p["record_id"] for p in proposal], "max_papers": limit})
        if proposal:   # access and costs of the proposal, checked for free, before the researcher decides
            by_id = {r["record_id"]: r for r in self.load("records.json")}
            review = self._cp2_review_selection([p["record_id"] for p in proposal], by_id, {q["record_id"]: q for q in quals})
            self._write_cp2_selection_review(review, approved=False)

    def _write_cp2_selection_review(self, review: dict, approved: bool) -> None:
        """Append the selection's access, projection, limits and accounts to CP2_review.md, and put its fingerprint in
        CP2_decision.json: approving CP2 then accepts exactly what was shown."""
        d = checkpoints.cp_dir(self.dir)
        proj, caps, acc = review["projection"], review["stage_caps"] or {}, review["accounts"]
        log = self.load("retrieval_log.json", {})
        lines = ["", "## Selection under review" + (" (as approved)" if approved else " (the proposal)"), "",
                 "Access was checked for free before any extraction is budgeted. Scientific relevance was decided by "
                 "screening, independently of access.", "",
                 "| Paper | Record | Importance | Access found | Read as | Legends read | Images inspected |",
                 "|---|---|---|---|---|---|---|"]
        for p in review["manifest"]["papers"]:
            a = log.get(p["record_id"]) or {}
            lines.append(f"| {p['paper_id']} | {p['record_id']} | {p['scientific_importance']} | {a.get('category')} | "
                         f"{a.get('level_read')} | {'yes' if a.get('figure_legends_read') else 'no'} | no |")
        lines += ["", "Routes not attempted for any paper: " + ", ".join(next(iter(log.values()), {}).get("routes_not_attempted", [])) + ".",
                  "", f"**Projection (PROVISIONAL):** ${proj['projected_total_usd']:.2f} for the stages ahead, margin "
                  "included. It rests on per-paper rates from the October 2026 run re-priced (an older procedure) and on "
                  "assumed output sizes; it is not a measured current-code cost.", "",
                  "| Account | USD |", "|---|---:|"]
        lines += [f"| {k.replace('_', ' ')} | {v:.2f} |" for k, v in acc.items() if isinstance(v, (int, float))]
        lines += ["", "Estimated by provider (projected, stages ahead): "
                  + ", ".join(f"{k} ${v:.2f}" for k, v in acc["projected_by_provider_usd"].items()), ""]
        if caps:
            lines += ["Stage limits this selection needs: " + ", ".join(f"{k} ${v:.2f}" for k, v in caps["caps_usd"].items()), ""]
        lines += (["**Problems (the corpus cannot be frozen until they are resolved):**", *[f"- {x}" for x in review["problems"]], ""]
                  if review["problems"] else ["No problem found: approving CP2 freezes this selection.", ""])
        text = (d / "CP2_review.md").read_text(encoding="utf-8")
        cut = text.find("\n## Selection under review")
        (d / "CP2_review.md").write_text((text if cut < 0 else text[:cut]) + "\n".join(lines) + "\n", encoding="utf-8")
        decision_path = d / "CP2_decision.json"
        decision = json.loads(decision_path.read_text(encoding="utf-8")) if decision_path.exists() else {}
        decision["selection_review_fingerprint"] = review["fingerprint"]
        decision_path.write_text(json.dumps(decision, indent=2), encoding="utf-8")
        self.save("cp2_selection_review.json", {k: review[k] for k in ("problems", "fingerprint", "accounts")}
                  | {"papers": [p["record_id"] for p in review["manifest"]["papers"]]})

    def _provisional_discovered_corpus(self, selected_ids: list[str], by_id: dict, quals: dict) -> tuple[dict, list[str]]:
        """A discovery run's selection as a PROVISIONAL manifest: the cap and duplicate checks, then the free access
        check of every selected paper, so the extraction budget is set from what can actually be read. Nothing is
        frozen here. Returns (manifest, problems that stop the selection)."""
        from . import run_spec
        from .synthesis_registry import fingerprint
        limit = int((self.cfg.get("run_spec") or {}).get("max_papers", 15))
        selected = [by_id[rid] for rid in selected_ids]
        problems = []
        if len(selected) > limit:
            problems.append(f"{len(selected)} papers are selected; this run allows at most {limit}")
        seen: dict[str, str] = {}
        for r in selected:
            for key in ([f"doi:{r['doi'].lower()}"] if r.get("doi") else []) + ([f"pmid:{r['pmid']}"] if r.get("pmid") else []) \
                    + [f"title:{run_spec._norm_title(r.get('title'))}"]:
                if key in seen and seen[key] != r["record_id"]:
                    problems.append(f"{seen[key]} and {r['record_id']} look like versions of one publication (same "
                                    f"{key.split(':')[0]}); keep one")
                seen[key] = r["record_id"]
        access = {r["record_id"]: self._access_check(r) for r in selected[:max(limit, 0) or len(selected)]}
        for rid, a in access.items():
            if a.get("materialization_blocker"):
                problems.append(f"{rid}: source materialization blocked: {a['materialization_blocker']}")
            if a["category"] == "NO_SOURCE_TEXT":
                problems.append(f"{rid}: neither full text nor an abstract could be obtained, so it cannot be read")
        proposals = {p["record_id"]: p["reason"] for p in (self.load("selection_proposal.json", {}) or {}).get("proposed", [])}
        manifest = run_spec.build_manifest(selected, quals, proposals, self.load("theme_framework.json"),
                                           run_spec.load(self.dir)[0], fingerprint(selected_ids), access)
        return manifest, problems

    def _cp2_review_selection(self, selected_ids: list[str], by_id: dict, quals: dict) -> dict:
        """Everything CP2 must show for a selection before its corpus can be frozen: access per paper, the projection
        from actual reading levels, the stage limits it needs, the accounts, and every problem. Writes nothing that
        freezes; returns the review, with a fingerprint the CP2 approval must carry."""
        from .synthesis_registry import fingerprint
        manifest, problems = self._provisional_discovered_corpus(selected_ids, by_id, quals)
        corpus = self._corpus_records(selected_ids, by_id, quals, manifest)
        levels = {p["record_id"]: (self.load("retrieval_log.json", {}).get(p["record_id"]) or {}).get("level_for_budget", "ABSTRACT")
                  for p in manifest["papers"]}
        proj = cost_projection.for_selection(cost_projection.load_rates(), corpus, self.dir, self.budget, self.route,
                                             self.cfg, levels=levels)
        derived, cap_problem = self._stage_caps_for(proj)
        if proj["verdict"] != "WITHIN_CAP":
            problems.append(f"the projection is ${proj['projected_total_usd']:.2f}, over the ${proj['cap_usd']:.2f} cap")
        if cap_problem:
            problems.append(cap_problem)
        digest = fingerprint({"selected": list(selected_ids), "levels": levels, "projected": round(proj["projected_total_usd"], 2),
                              "caps": derived and derived["caps_usd"], "problems": problems})
        return {"manifest": manifest, "corpus": corpus, "projection": proj, "stage_caps": derived, "problems": problems,
                "fingerprint": digest, "accounts": self.accounts(proj, derived)}

    def _freeze_corpus(self, manifest: dict) -> dict:
        """Freeze the checked selection as the corpus manifest (once; a later different freeze is refused)."""
        from . import run_spec
        from .synthesis_registry import fingerprint
        prior = run_spec.generated_manifest(self.dir)
        if prior is not None:
            if [p["record_id"] for p in prior["papers"]] != [p["record_id"] for p in manifest["papers"]]:
                raise Pause("the corpus is already frozen (data/corpus_manifest.json) with different papers; start a new "
                            "run to change it")
            return prior
        manifest = {**manifest, "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.save("corpus_manifest.json", manifest)
        self.prov.human_decision("CORPUS_FROZEN", {"papers": [p["record_id"] for p in manifest["papers"]],
                                                   "manifest_sha256": fingerprint(manifest)},
                                 "corpus manifest generated from discovery and screening; frozen at CP2 after its access, "
                                 "projection and stage limits were checked")
        return manifest

    ACCESS_CATEGORIES = {
        "FULL_TEXT_RETRIEVED": "an open-access copy in PMC was found and its identity verified",
        "NO_PMC_COPY_FOUND": "the PMC lookup answered: no PMC copy is listed. This does not establish that the paper is "
                             "paywalled or that no open-access full text exists elsewhere",
        "PMC_COPY_NOT_VERIFIED": "a PMC copy is listed but could not be retrieved, or its identity or body did not verify",
        "LOOKUP_UNAVAILABLE": "no lookup service could be reached; access is unresolved and is budgeted as full text",
        "NO_SOURCE_TEXT": "neither full text nor an abstract could be obtained",
    }

    def _access_check(self, rec: dict, retry: bool = False) -> dict:
        """The free retrieval and readiness check for one discovered paper, run at CP2 before its extraction budget is
        set, and again before extraction only when access was unresolved. Caches what it obtains (data/fulltext,
        data/fulltext_provenance) and logs every route tried and every route not tried (data/retrieval_log.json).
        Never raises for a missing copy: access is recorded, scientific relevance is decided elsewhere."""
        from .tools.fulltext import ROUTES_NOT_ATTEMPTED, find_pmcid, lookup_status
        rid = rec["record_id"]
        log = self.load("retrieval_log.json", {})
        entry = log.get(rid)
        if entry and not (retry and entry.get("category") == "LOOKUP_UNAVAILABLE"):
            if entry.get("level_read") == "FULL_TEXT":
                try:
                    if entry.get("identity_only_source"):
                        import base64, hashlib
                        from .tools.fulltext import verify_article_xml
                        proof = self.load(entry["identity_only_source"])
                        raw = base64.b64decode(proof["xml_base64"], validate=True)
                        if hashlib.sha256(raw).hexdigest() != proof["xml_sha256"]:
                            raise FullTextUnavailable("Identity-only source hash mismatch")
                        verify_article_xml(rec, raw)
                        if not entry.get("materialization_blocker"):
                            raise FullTextUnavailable("Identity-only source cannot be extractor-ready")
                    else:
                        verify_cached_source(rec, self.load(f"fulltext/{rid}.json"),
                                             self.load(f"fulltext_provenance/{rid}.json"))
                except (ValueError, KeyError, TypeError) as exc:
                    self.save(f"identity_quarantine/{rid}_access_cache.json", {
                        "record": rec, "access_entry": entry, "reason": str(exc)})
                    entry = None
            if entry:
                return entry
        entry = {"record_id": rid, "pmid": rec.get("pmid"), "doi": rec.get("doi"), "attempts": (entry or {}).get("attempts", [])}
        sections, category = None, None
        pmcid = rec.get("pmcid")
        if not pmcid:
            pmcid, why = find_pmcid(rec.get("pmid"), rec.get("doi"))
            status = lookup_status(pmcid, why)
            entry["attempts"].append({"route": "PMC identifier lookup (Europe PMC, then NCBI)", "outcome": status,
                                      "detail": pmcid or why, "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
            category = {"NOT_LISTED": "NO_PMC_COPY_FOUND", "UNAVAILABLE": "LOOKUP_UNAVAILABLE"}.get(status)
        if pmcid:
            try:
                sections, source = fetch_verified_sections({**rec, "pmcid": pmcid})
                self.save(f"fulltext/{rid}.json", sections)
                self.save(f"fulltext_provenance/{rid}.json", source)
                entry["attempts"].append({"route": "PMC open-access XML via Europe PMC", "outcome": "RETRIEVED_VERIFIED",
                                          "detail": pmcid, "xml_sha256": source["xml_sha256"],
                                          "identifiers_confirmed": source.get("identifiers_confirmed"),
                                          "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
                category = "FULL_TEXT_RETRIEVED"
            except FullTextUnavailable as exc:
                entry["attempts"].append({"route": "PMC open-access XML via Europe PMC", "outcome": "FAILED", "detail": str(exc),
                                          "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
                category = "PMC_COPY_NOT_VERIFIED"
        if category != "FULL_TEXT_RETRIEVED" and category != "LOOKUP_UNAVAILABLE":
            if (rec.get("abstract") or "").strip():
                self.save(f"fulltext/{rid}.json", {"Abstract": rec["abstract"]})
            else:
                category = "NO_SOURCE_TEXT"
        legends = bool(sections) and any(k.lower().startswith(("figure legend", "verbatim figure legend")) for k in sections)
        entry.update(category=category, meaning=self.ACCESS_CATEGORIES[category],
                     level_read={"FULL_TEXT_RETRIEVED": "FULL_TEXT", "LOOKUP_UNAVAILABLE": "UNRESOLVED",
                                 "NO_SOURCE_TEXT": "NONE"}.get(category, "ABSTRACT"),
                     level_for_budget="FULL_TEXT" if category in ("FULL_TEXT_RETRIEVED", "LOOKUP_UNAVAILABLE") else "ABSTRACT",
                     figure_legends_read=legends, figure_images_inspected=False, supplements_inspected=False,
                     routes_not_attempted=ROUTES_NOT_ATTEMPTED,
                     note="Figure legends are read as text only; figure images and supplementary files are not retrieved. "
                          "Routes not attempted are listed, so a missing copy here says nothing about the paper's access "
                          "elsewhere.")
        log[rid] = entry
        self.save("retrieval_log.json", log)
        return entry

    def _retrieve_discovered(self, rec: dict) -> tuple[dict, dict]:
        """Extraction input for a discovered paper, from its access check (re-run only if access was unresolved)."""
        rid = rec["record_id"]
        entry = self._access_check(rec, retry=True)
        if entry.get("materialization_blocker"):
            raise Pause(f"{rid}: source materialization requires review: {entry['materialization_blocker']}")
        if entry["category"] in ("NO_SOURCE_TEXT",) or (entry["category"] == "LOOKUP_UNAVAILABLE" and not (rec.get("abstract") or "").strip()):
            raise Pause(f"{rid} ({rec.get('manifest_paper_id')}): no full text and no abstract could be obtained "
                        "(data/retrieval_log.json). Nothing is extracted from a title. Supply its text in "
                        f"data/fulltext/{rid}.json, or start a new run without it.")
        if entry["category"] == "LOOKUP_UNAVAILABLE":   # still unresolved at extraction: read the abstract, recorded so
            self.save(f"fulltext/{rid}.json", {"Abstract": rec["abstract"]})
            entry = {**entry, "level_read": "ABSTRACT"}
            log = self.load("retrieval_log.json", {})
            log[rid] = {**entry, "note": entry["note"] + " Access was still unresolved at extraction: read as abstract."}
            self.save("retrieval_log.json", log)
        sections = self.load(f"fulltext/{rid}.json")
        if entry["category"] == "FULL_TEXT_RETRIEVED":
            verify_cached_source({**rec, "pmcid": self.load(f"fulltext_provenance/{rid}.json")["pmcid"]}, sections,
                                 self.load(f"fulltext_provenance/{rid}.json"))
        level = "FULL_TEXT" if entry["category"] == "FULL_TEXT_RETRIEVED" else "ABSTRACT"
        return sections, {"level": level, "figure_legends_read": entry["figure_legends_read"],
                          "figure_images_inspected": False, "supplements_inspected": False,
                          "scientific_importance": rec.get("tier"), "access_category": entry["category"],
                          "note": entry["note"] + ("" if level == "FULL_TEXT" else f" {entry['meaning'][0].upper()}{entry['meaning'][1:]}.")}

    def _retraction_check(self, records: list[dict], label: str) -> dict:
        """Crossref retraction status of the given records (free; cached in data/crossref_cache). Written to
        data/retraction_<label>.json and, for the researcher, checkpoints/CP2_retractions.md. A record that cannot
        be checked (no DOI, DOI unknown, Crossref unreachable) is listed as unchecked, never assumed clean."""
        report = references.retraction_report(records, os.environ.get("CROSSREF_MAILTO"),
                                              cache_dir=self.data("crossref_cache"))
        self.save(f"retraction_{label}.json", report)
        self.prov.tool_run("retraction_check", label, {"checked": report["checked"],
                                                       "retracted": [r["record_id"] for r in report["retracted"]],
                                                       "concern": [r["record_id"] for r in report["concern"]],
                                                       "unchecked": len(report["unchecked"])})
        lines = [f"# Retraction check ({label})", "",
                 f"Checked against Crossref: {report['checked']} of {len(records)} records.", "",
                 "## Retracted", *[f"- {r['record_id']} ({r['doi']}): {r.get('title')}" for r in report["retracted"]],
                 *([] if report["retracted"] else ["- none found"]), "",
                 "## Expression of concern", *[f"- {r['record_id']} ({r['doi']}): {r.get('title')}"
                                               for r in report["concern"]],
                 *([] if report["concern"] else ["- none found"]), "",
                 "## Not checked (treat as unknown, not as clean)",
                 *[f"- {r['record_id']}: {r['reason']}" for r in report["unchecked"]],
                 *([] if report["unchecked"] else ["- none"])]
        (checkpoints.cp_dir(self.dir) / "CP2_retractions.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report

    def _cp2_costs(self, quals: list[dict]) -> None:
        """Cost lines in CP2_review.md: the projection for every qualified paper, and per paper by level."""
        try:
            rates = cost_projection.load_rates()
        except FileNotFoundError as e:
            note = f"\n\n## Cost projection\n\nNot available: {e}. CP2 approval will refuse without it.\n"
        else:
            by_id = {r["record_id"]: r for r in self.load("records.json")}
            qualified = [by_id[q["record_id"]] for q in quals if q.get("disposition") == "QUALIFIED" and q["record_id"] in by_id]
            proj = (pilot.project(self, pilot.STAGE_1, records=qualified) if pilot.enabled(self)
                    else cost_projection.for_selection(rates, qualified, self.dir, self.budget, self.route, self.cfg))
            if pilot.enabled(self):
                note = ("\n\n## Stage 1-only cost projection\n\nA02?A07 through CP3 only; Stage 2 excluded. "
                        "Source levels are planning requirements, not proof of completed retrieval.\n\n```json\n"
                        + json.dumps(proj, indent=2) + "\n```\n\n"
                        "Selection/source-level/cost admission is enforced on resume; approval never authorizes Stage 2.\n")
                p = checkpoints.cp_dir(self.dir) / "CP2_review.md"
                p.write_text(p.read_text(encoding="utf-8") + note, encoding="utf-8")
                return
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
            from . import a06_batches
            if agent_id == "A06-SV" and a06_batches.enabled(self,payload):
                on_output(step,self.agent(agent_id,payload,step,exclude_providers=frozenset(exclude(step))))
                continue
            done = self.dir / "outputs" / f"{step}.json"
            if done.exists():
                from .extraction_mode import active,record_identity
                if active(agent_id):
                    from .agents.base import prepare_output
                    record_identity(self.dir)
                    accepted=prepare_output(agent_id,done.read_text(encoding="utf-8"),payload)
                else:accepted=json.loads(done.read_text(encoding="utf-8"))
                on_output(step,accepted)
            else:
                pending.append((step, payload))
        bcfg = self.cfg.get("batch") or {}
        if pending and bcfg.get("enabled") and agent_id in (bcfg.get("agents") or []):
            BatchStage(self, agent_id, pending, on_output, exclude).run_all()
            return
        for step, payload in pending:
            on_output(step, self.agent(agent_id, payload, step, exclude_providers=frozenset(exclude(step))))

    def _checked_fulltext(self, rec: dict) -> dict:
        """No unverified cache or bare-PMCID lookup reaches screening/extraction."""
        rid = rec["record_id"]
        sections = self.load(f"fulltext/{rid}.json")
        source = self.load(f"fulltext_provenance/{rid}.json")
        if sections:
            try:
                verify_cached_source(rec, sections, source)
                return sections
            except FullTextUnavailable as exc:
                self.save(f"identity_quarantine/{rid}_cache.json", {
                    "record": rec, "sections": sections, "source": source, "reason": str(exc)})
        sections, source = fetch_verified_sections(rec)
        self.save(f"fulltext/{rid}.json", sections)
        self.save(f"fulltext_provenance/{rid}.json", source)
        return sections

    def stage_extract(self, st: dict) -> str:
        spec = self.load("spec_approved.json")
        items, rid_of = [], {}
        for rec in self.load("selected_corpus.json"):
            rid = rec["record_id"]
            if self.data(f"extractions/{rid}.json").exists():
                continue
            required = corpus_policy.fixed(self).get(str(rec.get("pmid")))
            if required == "ABSTRACT":
                sections = {"Abstract": rec.get("abstract") or ""}
            elif required == "FULL_TEXT":
                sections = self.load(f"fulltext/{rid}.json")
                try:
                    if sections:
                        verify_cached_source(rec, sections, self.load(f"fulltext_provenance/{rid}.json"))
                    else:
                        corpus_policy.require_source(self, rec)
                        sections, source = fetch_verified_sections(rec)
                        self.save(f"fulltext/{rid}.json", sections)
                        self.save(f"fulltext_provenance/{rid}.json", source)
                    ready = self.load("source_readiness.json", {})
                    ready[rid] = {"required": required, "status": "VERIFIED"}
                    self.save("source_readiness.json", ready)
                except ValueError as exc:
                    ready = self.load("source_readiness.json", {})
                    ready[rid] = {"required": required, "status": "BLOCKED", "reason": str(exc)}
                    self.save("source_readiness.json", ready)
                    raise Pause(f"Required verified full text unavailable for {rid}: {exc}") from exc
            elif rec.get("corpus_source") == "DISCOVERY":
                sections, access_now = self._retrieve_discovered(rec)
            elif rec.get("intended_reading_level") == "ABSTRACT":
                sections = {"Abstract": rec.get("abstract") or ""}   # the manifest says abstract, whatever its importance
            elif rec.get("intended_reading_level") == "FULL_TEXT":
                try:
                    sections = self._checked_fulltext(rec)
                except FullTextUnavailable as exc:
                    raise Pause(f"{rid}: required full text identity/body could not be verified: {exc}") from exc
                if not sections or len(sections) < 2:
                    raise Pause(f"{rid} ({rec.get('manifest_paper_id')}) is marked for full-text reading in the corpus "
                                "manifest, but no full text could be loaded. It is not silently read as an abstract: "
                                f"place its sections in data/fulltext/{rid}.json, or start a run whose manifest says ABSTRACT.")
            elif not self._tier_allows("extraction", "full_text_tiers", rec):
                sections = {"Abstract": rec.get("abstract") or ""}   # not a full-text tier: abstract only, labelled so
            else:
                try:
                    sections = self._checked_fulltext(rec)
                except FullTextUnavailable as exc:
                    self.save(f"identity_quarantine/{rid}_retrieval.json", {
                        "record": rec, "reason": str(exc), "level_used": "ABSTRACT"})
                    sections = {"Abstract": rec.get("abstract") or ""}
            level = "FULL_TEXT" if len(sections) > 1 else "ABSTRACT"
            self.save(f"fulltext/{rid}.json", sections)
            rid_of[f"A05-KE_{rid}"] = rid
            payload = {"review_spec": spec, "theme_framework": self.load("theme_framework.json"),
                       "content_level": level, "record": {**rec, "content": sections}}
            from . import run_spec
            outline, manifest = run_spec.load(self.dir)
            paper = run_spec.paper_for(manifest, rec)
            if rec.get("corpus_source") == "DISCOVERY":   # what retrieval actually obtained
                payload["source_access"] = access_now
                access = self.load("source_access.json", {})
                access[rid] = {"paper_id": rec.get("manifest_paper_id"), **access_now}
                self.save("source_access.json", access)
            elif paper:   # what was actually accessible, so nothing is described that was never read
                payload["source_access"] = run_spec.source_access(paper, level, sections)
                access = self.load("source_access.json", {})
                access[rid] = {"paper_id": paper["paper_id"], **payload["source_access"]}
                self.save("source_access.json", access)
            if outline:
                payload["outline_questions"] = [{"section_id": s["section_id"], "heading": s["heading"],
                                                 "questions": s["questions"], "guidance": s.get("guidance") or []}
                                                for s in outline["sections"]]
            items.append((f"A05-KE_{rid}", payload))
        save = lambda step, out: self.save(f"extractions/{rid_of[step]}.json", self._normalize(rid_of[step], out))  # noqa: E731
        first = self._first_tranche()
        if first:
            self.run_many("A05-KE", [it for it in items if rid_of[it[0]] in first], save)
            self._validate_subset([r for r in self.load("selected_corpus.json") if r["record_id"] in first])   # the early check judges extraction and its independent validation together
            self._early_check(first)
            items = [it for it in items if rid_of[it[0]] not in first]
        self.run_many("A05-KE", items, save)
        return "validate"

    def _validate_papers(self, rids: list[str]) -> None:
        """Independent A06 validation of these papers (those not validated yet), on a vendor other than the one that
        extracted each. Used by the validate stage and, before CP_EARLY, for the first papers."""
        spec = self.load("spec_approved.json")
        items, rid_of = [], {}
        for rid in rids:
            if self.data(f"validations/{rid}.json").exists():
                continue
            ext, sections = self._prepare_validation(rid)
            # a paper re-extracted before re-extraction was turned off keeps its label (v2)
            n = 2 if (self.dir / "outputs" / f"A05-KE_{rid}_reextract.json").exists() else 1
            rid_of[f"A06-SV_{rid}_v{n}"] = rid
            payload = {"mode": "PER_PAPER", "review_spec": spec, "extraction": ext,
                       "gate1_results": span_check.check_findings(ext, sections), "paper_text": sections,
                       "source_access": self.load("source_access.json", {}).get(rid, {})}
            self._save_a06_input(rid, f"A06-SV_{rid}_v{n}", payload)
            items.append((f"A06-SV_{rid}_v{n}", payload))
        entries = self.budget.entries()
        vendor = {step: frozenset({self._extraction_vendor(rid, entries)}) for step, rid in rid_of.items()}
        self.run_many("A06-SV", items, lambda step, out: self._save_validation(rid_of[step], out),
                      exclude=vendor.__getitem__)

    def _first_tranche(self) -> list[str]:
        """run_spec.first_tranche: the papers read (and validated) first, before the early check. {papers: N} takes N
        papers in manifest order, at least one of each reading level actually obtained when the corpus has both, so
        the check works for whatever mix of full texts and abstracts discovery and retrieval produced. The older
        {full_text: a, abstract: b} form is honoured as a preference and filled up to a + b."""
        from . import run_spec
        want = (self.cfg.get("run_spec") or {}).get("first_tranche") or {}
        manifest = run_spec.manifest_of(self.dir)
        if not manifest or not want:
            return []
        order = {p["paper_id"]: i for i, p in enumerate(manifest["papers"])}
        corpus = sorted((r for r in self.load("selected_corpus.json", []) if r.get("manifest_paper_id")),
                        key=lambda r: order.get(r["manifest_paper_id"], 999))
        actual_access = self.load("source_access.json", {})
        level = lambda r: actual_access.get(r["record_id"], {}).get("level") or r.get("intended_reading_level")   # noqa: E731  (for discovered papers: what retrieval obtained)
        out: list[str] = []
        if "papers" in want:
            total = int(want["papers"])
            for lv in ("FULL_TEXT", "ABSTRACT"):
                first = next((r["record_id"] for r in corpus if level(r) == lv), None)
                if first and len(out) < total:
                    out.append(first)
        else:
            total = int(want.get("full_text", 0)) + int(want.get("abstract", 0))
            for lv, n in (("FULL_TEXT", int(want.get("full_text", 0))), ("ABSTRACT", int(want.get("abstract", 0)))):
                out += [r["record_id"] for r in corpus if level(r) == lv][:n]
        out += [r["record_id"] for r in corpus if r["record_id"] not in out][:max(0, total - len(out))]
        return out if len(out) < len(corpus) else []   # a tranche that is the whole corpus is no early check

    def _early_check(self, first: list[str]) -> None:
        """Stop after the first papers are extracted AND independently validated, until the researcher has looked
        (CP_EARLY, approved once per tranche). Reports extraction and validation separately, compares the one quantity
        the projection forecast (extraction plus validation per paper, by reading level), and re-forecasts the rest of
        the run from these measurements: the remaining papers at the measured cost per level, and the downstream
        stages at the findings count the measured papers imply."""
        from .synthesis_registry import fingerprint
        from .extraction_mode import identity as extraction_identity
        digest = fingerprint({"run": self.id, "first_tranche": sorted(first),"extraction_generation":extraction_identity(),
            "reviewed_artifacts":{rid:{name:self.load(f"{name}/{rid}.json") for name in ("extractions","validations","fulltext")} for rid in sorted(first)}})
        if checkpoints.review_approved(self.dir, "CP_EARLY", digest):
            return
        from . import run_spec
        corpus = {r["record_id"]: r for r in self.load("selected_corpus.json", [])}
        proj = self.load("cost_projection.json") or {}
        projected_per_paper = {}
        for line in proj.get("lines", []):
            for lv in ("FULL_TEXT", "ABSTRACT"):
                if line.get("stage") == f"A05-KE + A06-SV per paper ({lv})" and line.get("calls"):
                    projected_per_paper[lv] = float(line["usd"]) / int(line["calls"])
        retrieval = self.load("retrieval_log.json", {}) or {}
        entries = self.budget.entries()
        cost = lambda agent, rid: sum(e["cost_usd"] or 0.0 for e in entries if e["agent"] == agent   # noqa: E731
                                      and re.match(rf"{agent}_{rid}(_|$)", e["step"]))
        groups = {"supported": ("SUPPORTED", "SUPPORTED_WITH_CONSTRAINTS", "SUPPORTED_FOR_OBSERVATION", "PARTIALLY_SUPPORTED"),
                  "not_established": ("DOES_NOT_ESTABLISH",), "rejected": ("BLOCKED_PROVENANCE", "BLOCKED_ALIGNMENT"),
                  "unresolved": ("HUMAN_REVIEW_REQUIRED", "UNRESOLVED_SOURCE_ACCESS")}
        papers, measured = [], {}
        for rid in first:
            ext = self.load(f"extractions/{rid}.json") or {}
            val = self.load(f"validations/{rid}.json") or {}
            lv = ext.get("content_level") or corpus.get(rid, {}).get("intended_reading_level") or "ABSTRACT"
            contexts = {c.get("context_id"): c for c in ext.get("contexts") or []}
            finding_contexts = [contexts.get(f.get("context_id")) or f.get("context") or {} for f in ext.get("findings") or []]
            comparators = [(c.get("fields") or c).get("comparator") for c in finding_contexts]
            disp = [v.get("disposition") for v in val.get("validations") or []]
            a = retrieval.get(rid) or {}
            row = {"record_id": rid, "paper_id": corpus.get(rid, {}).get("manifest_paper_id"), "level": lv,
                   "access_category": a.get("category"), "figure_legends_read": a.get("figure_legends_read", False),
                   "figure_images_inspected": False,
                   "extraction_usd": round(cost("A05-KE", rid), 4), "validation_usd": round(cost("A06-SV", rid), 4),
                   "findings": len(ext.get("findings") or []),
                   **{k: sum(d in v for d in disp) for k, v in groups.items()},
                   "comparator_not_reported": sum(c in ("NONE_REPORTED",) for c in comparators),
                   "comparator_missing": sum(c in (None, "") for c in comparators),
                   "access_limitations": a.get("meaning") if a.get("category") != "FULL_TEXT_RETRIEVED" else
                   "legends read as text; images and supplements not retrieved",
                   "projected_per_paper_usd": projected_per_paper.get(lv)}
            row["omission_review"]={"status":"REQUIRES_SOURCE_COMPARISON",
                "source":f"data/fulltext/{rid}.json","extraction":f"data/extractions/{rid}.json",
                "independent_validation":f"data/validations/{rid}.json",
                "instruction":"Inspect relevant source passages for omitted analytes, matrices, measurement tasks, numerical values/units, comparators, uncertainty, contrary findings and author qualifications. Matching spans and a complete schema do not establish recall. Concentration classification does not establish numerical estimation."}
            row["measured_per_paper_usd"] = round(row["extraction_usd"] + row["validation_usd"], 4)
            papers.append(row)
            measured.setdefault(lv, []).append(row)
        # re-forecast the rest from the measurements
        remaining = [r for rid, r in corpus.items() if rid not in first]
        rest_usd, rest_findings = 0.0, 0
        rates = cost_projection.load_rates().get("per_paper", {})
        for r in remaining:
            lv = r.get("intended_reading_level") or "ABSTRACT"
            got = measured.get(lv)
            rest_usd += (sum(x["measured_per_paper_usd"] for x in got) / len(got)) if got else projected_per_paper.get(lv, 0.0)
            rest_findings += (sum(x["findings"] for x in got) / len(got)) if got else float((rates.get(lv) or {}).get("findings_p90", 0))
        findings_total = int(round(sum(p["findings"] for p in papers) + rest_findings))
        outline, _ = run_spec.load(self.dir)
        downstream = cost_projection.downstream(self.budget, self.route, self.cfg, findings_total,
                                                words=run_spec.total_words(outline) if outline else None)
        downstream_usd = sum(float(x["usd"]) for x in downstream)
        auxiliary = sum(float(x["usd"]) for x in proj.get("lines", [])
                        if x.get("stage") in ("A06-SV whole-paper repeat (instability test)", "A06-SV per theme"))
        revised = {**proj, "projected_remaining_usd": rest_usd + downstream_usd + auxiliary,
                   "projected_total_usd": self.budget.spent() + rest_usd + downstream_usd + auxiliary,
                   "lines": [{"stage": "A05-KE", "usd": rest_usd / 2},
                             {"stage": "A06-SV", "usd": rest_usd / 2 + auxiliary}, *downstream]}
        old_downstream = sum(float(x["usd"]) for x in proj.get("lines", []) if x.get("stage") in self.cfg["agents"])
        report = {"papers": papers, "spent_usd": round(sum(p["measured_per_paper_usd"] for p in papers), 4),
                  "forecast": {"remaining_papers": len(remaining),
                               "remaining_extraction_and_validation_usd": round(rest_usd, 2),
                               "findings_expected_total": findings_total,
                               "downstream_usd_revised": round(downstream_usd, 2),
                               "validation_retest_and_theme_reserve_usd": round(auxiliary, 2),
                               "downstream_usd_at_cp2": round(old_downstream, 2),
                               "basis": "remaining papers at the cost measured here for their reading level (the CP2 "
                                        "per-paper projection where a level was not measured); downstream stages re-projected "
                                        "at the findings count these papers imply. Three papers are an early signal, not an "
                                        "average."},
                  "accounts": self.accounts(revised)}
        self.save("early_check.json", report)
        self.prov.tool_run("early_check", "extract", {k: report[k] for k in ("spent_usd", "forecast")})
        checkpoints.write_early_review(self.dir, digest, report)
        self.pause_for_checkpoint("CP_EARLY")

    def _tier_allows(self, section: str, key: str, rec: dict) -> bool:
        """pipeline.yaml -> <section>.<key>: the tiers a costly step applies to. None or missing: every paper."""
        tiers = (self.cfg.get(section) or {}).get(key)
        return tiers is None or rec.get("tier") in tiers

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
        from .source_semantics import interpret, load_evidence
        try:
            corrected, semantic_audit = interpret(ext, sections, load_evidence(self.dir, self.load(f'entity_label_evidence/{rid}.json', [])))
        except ValueError as exc:
            raise Pause(f'{rid}: source interpretation requires correction: {exc}') from exc
        prior = self.load(f'source_semantics/{rid}.json', {})
        if prior.get('entity_label_defects') and not semantic_audit['entity_label_defects']:
            semantic_audit['entity_label_defects'] = prior['entity_label_defects']
        self.save(f'source_semantics/{rid}.json', semantic_audit)
        if corrected != ext:
            archive = f'source_semantics/original_extractions/{rid}.json'
            if not self.data(archive).exists():
                self.save(archive, ext)
            self._write_validation(f'extractions/{rid}.json', corrected)
            ext = corrected
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

    def _validate_subset(self, corpus: list[dict]) -> None:
        """Validate selected papers, including configured repairs, without downstream theme work."""
        spec = self.load("spec_approved.json")
        max_re = int(self.cfg["loops"]["max_reextractions"])
        if max_re == 0:
            self._validate_papers([r["record_id"] for r in corpus])
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
                           "paper_text": sections, "source_access": self.load("source_access.json", {}).get(rid, {})}
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

    def stage_validate(self, st: dict) -> str:
        corpus = self.load("selected_corpus.json")
        self._validate_subset(corpus)
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
        semantic_audit = self.load(f'source_semantics/{rid}.json')
        if semantic_audit:
            payload['source_interpretation'] = semantic_audit
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
            if not pilot.enabled(self) and not self._tier_allows("validation", "instability_tiers", rec):
                skipped[rid] = f"tier {rec.get('tier')}: the retest runs for {self.cfg['validation']['instability_tiers']} only; its blocked findings stay blocked"
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
            merged=self.load('a06_batch_receipts/'+step+'.json')
            if merged:
                return {'step':step,'channel':'bounded_interactive','model':merged['model'],'json_repair':False,
                        'batch_steps':[b['step'] for b in merged['batches']]}
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
            base = {"mode": "PER_THEME", "theme": th, "theme_definition": definition,
                    "same_study_flags": same_study,
                    "records": [{k: r.get(k) for k in ("record_id", "authors", "year", "title")} for r in corpus]}
            step = f"A06-SV_theme_{re.sub(r'[^A-Za-z0-9]+', '_', th)[:40]}{label}"
            from . import theme_paging
            from .synthesis_registry import offline_tokens
            paging = theme_paging.settings(self.cfg)
            cap = self.route("A06-SV", theme_exclude).max_tokens
            overhead = 0
            if paging:
                bpt = float(paging.get("bytes_per_token", 2.1))
                overhead = int(offline_tokens(build_system_prompt("A06-SV")) / bpt) + theme_paging.est_tokens(base, bpt)
            try:
                paged = bool(paging) and theme_paging.needs_paging(fs, paging, cap, overhead)
                if paged:   # bounded packets, then one reconciliation over the whole theme (theme_paging.py)
                    theme_records[th] = theme_paging.run(
                        th, fs, base, paging, cap, overhead,
                        lambda suffix, payload: self.agent("A06-SV", payload, step=f"{step}_{suffix}",
                                                           exclude_providers=theme_exclude),
                        save=lambda proof: self.save(f"theme_paging/{theme_paging.slug(th)}{label}.json", proof))
                    self.prov.tool_run("theme_paging", step, theme_records[th]["theme_paging"])
            except theme_paging.PagingError as exc:
                raise Pause(f"A06 theme pass for {th}: {exc}") from exc
            if not paged:
                theme_records[th] = self.agent("A06-SV", {**base, "validated_findings": fs}, step=step,
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
            ext, semantic_sections = self._prepare_validation(rid)
            from .source_semantics import interpret, load_evidence
            _, semantic_audit = interpret(ext, semantic_sections, load_evidence(self.dir, self.load(f'entity_label_evidence/{rid}.json', [])))
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
            recovery_path = f"offline_recovery/{rid}/audit.json"
            recovered = self.load(recovery_path, {}).get("after_recovery", {}).get("source_derived_additions", [])
            ctx = {c["context_id"]: c for c in ext.get("contexts", [])}
            for f in ext.get("findings", []):
                v = val.get(f["finding_id"], {})
                out.append({"finding_id": f"{rid}:{f['finding_id']}", "record_id": rid,
                            **self._finding_themes(f, rec),
                            **({"source_recovery": {"audit": recovery_path, "basis": f.get("warrant_note")}}
                               if f["finding_id"] in recovered else {}),
                            # the handoff contract (handoff.py): relation, direction, hedging, attribution
                            **handoff.project(f, v, ext.get("prompt_version")),
                            "source_interpretation": semantic_audit['findings'].get(f['finding_id'], {}),
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

    def _synthesis_settings(self) -> dict:
        """The A07 settings that enter the job identity. Sample mode (singlepaper_eval) adds its scope here,
        so a sample job never shares a job directory, ledger or turn with a full synthesis."""
        return self.cfg["synthesis"]

    def _synthesis_job_class(self):
        from .synthesis_bounded import RegistrySynthesisJob
        return RegistrySynthesisJob

    def _a07_quote(self, mode: str, payload: dict, count) -> tuple[int, int, float]:
        """(input bound, output cap, pre-margin reservation USD) for one A07 call. No cache hit assumed: the whole
        prefix is charged as a 1h cache write. Run._reserve adds and HOLDS the 30% margin for A07-A12."""
        scfg = self.cfg["synthesis"]
        limit = int(scfg["output_limits"][mode])
        tokens = count(payload)
        m = self.route("A07-SYN")
        usd = self.budget.cost(m.model, 0, limit, 0, 0, tokens)
        if usd is None:
            raise UnpricedModel(m.model)
        return tokens, limit, usd

    def stage_synthesize(self, st: dict) -> str:
        """Bounded registry-backed A07 with a human alignment stop before detailed synthesis."""
        from .synthesis_bounded import AlignmentRequired
        job, tag = self._synthesis_job()
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

    def _synthesis_job(self):
        """The A07 registry job for this run's current inputs, and its tag. Builds the registry and the job (which
        writes only its own identity and registry snapshot); makes no model call."""
        from .synthesis_registry import EvidenceRegistry, fingerprint, offline_tokens
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
        scfg = self._synthesis_settings()
        identity = {"prompt": build_system_prompt("A07-SYN"),
                    "schemas": {p.name: p.read_text(encoding="utf-8") for p in sorted(SCHEMAS_DIR.glob("A07-SYN*.json"))},
                    "model": dataclasses.asdict(self.route("A07-SYN")), "pricing": self.budget.prices,
                    **self._decision_identity("A07-SYN")}
        tag = fingerprint({"corpus": registry.digest, "execution": identity, "settings": scfg})[:16]
        system = build_system_prompt("A07-SYN")

        def count(payload):
            return offline_tokens(system) + offline_tokens(user_parts(payload))

        def call(mode, payload, name):
            if mode != "PLAN":
                decision = checkpoints.approved(self.dir, "CP_SYN")
                if not decision or decision.get("fingerprint") != job.identity or not (
                        decision.get("approve_alignment") and decision.get("keep_approved_framework")):
                    raise Pause("A07 synthesis requires the matching approved CP_SYN decision")
                plan = job._committed("PLAN")
                payload = {**payload, "cp_syn_researcher_decision": decision,
                           "reviewed_organization_proposals": plan["theme_change_proposals"]}
            if mode == "GROUP":
                payload = {**payload, "coverage_instruction": (
                    "For satisfies use exact IDs from group.manifest_item_ids only. Assign each fulfilled "
                    "obligation once to the proposition or gap that fulfills it. Leave satisfies empty "
                    "elsewhere. Use source_item_ids for source links. A paper with usable evidence needs "
                    "a proposition citing its eligible finding. Keep unknown study independence explicit.")}
            tokens, limit, usd = self._a07_quote(mode, payload, count)
            if mode == "RECONCILE" and "prefill_finding_ids" in payload:
                from . import reconciliation_paging, decisions
                from .approved_scope import enrich
                enriched = enrich(self, "A07-SYN", payload)
                enriched = decisions.attach(self.dir, "A07-SYN", {**enriched,"source_access":self.load("source_access.json", {})})
                route = self.route("A07-SYN")
                body = reconciliation_paging.provider_body(self, enriched, route, limit)
                request_bytes = reconciliation_paging.body_bytes(body)
                reviewed = getattr(self, "_reconciliation_request_hashes", {})
                if reviewed and name.endswith("_LOOKUP0"):
                    from hashlib import sha256
                    if reviewed.get(name.removesuffix("_LOOKUP0")) != sha256(request_bytes).hexdigest():
                        raise Pause("reconciliation request differs from its reviewed provider body")
                tokens = len(request_bytes) + 2048
                usd = self.budget.cost(route.model, 0, limit, 0, 0, tokens)

            if tokens + limit > scfg["context_ceiling_tokens"]:
                raise JobStopped("A07 context admission refused before dispatch")
            key = f"a07-{tag}-{name}"
            if key in self.budget.reservations():
                raise Pause("unsettled A07 call reservation: reconcile provider usage before retrying " + key)
            ok, available = self._reserve(key, usd, "A07-SYN", "bounded synthesis pre-call reservation", steps=[f"A07-SYN_job{tag}_{name}"])
            if not ok:
                raise BudgetExceeded(f"A07 call reserves ${usd:.2f}; only ${available:.2f} remains")
            self._active_synthesis_reservation = key
            try:
                out = self.agent("A07-SYN", payload, step=f"A07-SYN_job{tag}_{name}",
                                 overrides={"cache_system": True, "cache_payload": (), "cache_ttl": scfg.get("cache_ttl", "1h"),
                                            "max_tokens": limit},
                                 schema_file=f"A07-SYN.bounded-{mode.lower()}.schema.json", reservation_key=key,
                                 truncation_retries=0 if mode == "RECONCILE" and "prefill_finding_ids" in payload else None)
            except AgentError as exc:
                # Known responses are logged, including refusal/truncation; unknown API billing stays held.
                if any(e["step"] == f"A07-SYN_job{tag}_{name}" for e in self.budget.entries()):
                    self.budget.release(key)
                raise
            except (Pause, BudgetExceeded, UnpricedModel):
                from .job_ledger import Ledger
                sent = any(e["state"] == "DISPATCHED" and e.get("reservation") == key
                           for e in Ledger(self.dir).events(f"A07-SYN_job{tag}_{name}"))
                if not sent or any(e.get("reservation_key") == key for e in self.budget.entries()):
                    self.budget.release(key)
                raise
            finally:
                self._active_synthesis_reservation = None
            self.budget.release(key)
            return out

        def approve(digest, alignment):
            decision = checkpoints.approved(self.dir, "CP_SYN")
            if decision and decision.get("fingerprint") == digest and decision.get("approve_alignment") is True:
                return True
            checkpoints.write_synthesis_alignment(self.dir, digest, alignment)
            return False

        job = self._synthesis_job_class()(self.dir / "data" / f"synthesis_job_{tag}", registry, call, count, scfg,
                                          identity, approve, served_by=lambda: self.last_model)
        auth = self.load("reconciliation_repair_approved.json")
        if auth:
            plan = self.load("reconciliation_repair_plan.json")
            if (not plan or auth.get("approved") is not True or not auth.get("approved_by")
                    or auth.get("job_tag") != tag or plan.get("job_identity") != job.identity
                    or plan.get("run_id") != self.id or auth.get("plan_fingerprint") != fingerprint(plan)
                    or plan.get("registry") != job.registry.digest
                    or not auth.get("approved_turns") or auth.get("max_increment_usd", 0) <= 0
                    or auth.get("baseline_stage_usd") != plan.get("baseline_stage_usd")
                    or any(t not in plan.get("reservations", {}) for t in auth["approved_turns"])
                    or len(set(auth["approved_turns"])) != len(auth["approved_turns"])
                    or Decimal(str(auth["max_increment_usd"])) > sum(
                        Decimal(plan["reservations"][t]) for t in auth["approved_turns"])):
                raise Pause("reconciliation approval or plan identity mismatch")
            job.evidence_pages = plan["pages"]
            self._reconciliation_approval = auth
            self._reconciliation_request_hashes = plan["request_hashes"]
        return job, tag

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
        if pkg.get("sample") and not self._sample_mode():
            raise Pause("a NON-REPRESENTATIVE sample synthesis can never feed a full writing run")
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
        bcfg, journal = self._bridge_cfg(), self._journal()
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
            payload = self._outline_payload(pkg, corpus, journal, table, bcfg, findings)
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
            problems, report = bridge.validate_plan(plan, ledger, pkg, corpus, table, journal, bcfg, findings)
            from . import run_spec
            outline, _ = run_spec.load(self.dir)
            if outline:
                from .approved_scope import writing_outline, heading_problems
                extra, coverage = run_spec.plan_problems(plan, writing_outline(self, outline))
                extra += heading_problems(self, plan)
                problems = problems + extra
                queue = run_spec.unmapped(ledger)
                self.save("unmapped_evidence.json", {"status": "NEEDS_RESEARCHER_REVIEW" if queue else "EMPTY",
                                                     "items": queue, "outline_coverage": coverage})
                (checkpoints.cp_dir(self.dir) / "CP_LEDGER_unmapped_evidence.md").write_text(
                    "# Evidence outside the outline\n\n"
                    f"{len(queue)} item(s) fit no section of your outline. They are not written about and not lost. "
                    "Decide for each: extend the outline (new run specification), or leave it out and say why.\n\n"
                    + "\n".join(f"- {q['item_id']}: {q.get('reason') or 'no reason given'}" for q in queue)
                    + "\n\n## Outline sections the evidence does not fill\n\n"
                    + ("\n".join(f"- {s}" for s in coverage["sections_without_evidence"]) or "- none")
                    + "\n\nA section without evidence is reported as such; it is not padded.\n", encoding="utf-8")
                self.prov.tool_run("unmapped_evidence", "outline", {"items": len(queue), **coverage})
            check = {"basis": basis, "plan_version": bridge.plan_version(plan, ledger), "problems": problems,
                     "report": report}
            self.save("bridge/plan_check.json", check)
            self.prov.tool_run("plan_check", "outline", {"problems": len(problems), "counts": report["counts"],
                                                         "theme_to_sections": report["theme_to_sections"]})
            if problems:
                raise Pause(f"A08 plan rejected by the bridge ({len(problems)} problems; first: {problems[0]}). "
                            "See data/bridge/plan_check.json; rerun the outline stage")
        self._save_comparative_table(table, plan, ledger, pkg, findings)
        self.save("bridge/argument_map.json", bridge.argument_map(pkg, corpus, findings))
        if bcfg.get("ledger_approval", True):
            self._ledger_approved(plan, ledger, check["report"], pkg, corpus, table)
        return "draft"

    def _save_comparative_table(self, table: dict, plan: dict | None = None, ledger: list | None = None,
                                pkg: dict | None = None, findings: list | None = None) -> None:
        from . import bridge
        discussed_in = None
        if plan is not None and ledger is not None and pkg is not None and findings is not None:
            register = bridge.contrary_register(pkg, findings, table, plan, ledger)
            self.save("bridge/contrary_register.json", register)
            used = {s for e in register if not e["in_table"] for s in e.get("sections") or []}
            discussed_in = [s.get("heading") for s in plan.get("sections") or [] if s.get("section_id") in used]
        out_dir = self.dir / "data" / "display_items"
        if out_dir.exists():
            shutil.rmtree(out_dir)   # one display item: the comparative table replaces anything built before
        out_dir.mkdir(parents=True)
        display_items._write_csv(out_dir / "T1.csv", table["columns"], table["rows"])
        (out_dir / "T1.json").write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
        # A10 and the export see the reader-facing table only (bridge.reader_table); the selection record stays above
        self.save("display_items.json", [bridge.reader_table(table, self.load("selected_corpus.json", []), discussed_in)])
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
                     'prompt':system,'schema':(SCHEMAS_DIR/'A10-RV.bounded.schema.json').read_text(),
                     **self._decision_identity('A10-RV')}
        def call(mode, payload, name):
            cap = cfg['output_limits'][mode]
            model = self.route('A10-RV',prose)
            # No hit assumed; reserve all input at the configured cache-write rate.
            usd = self.budget.cost(model.model,0,cap,0,count(payload))
            if usd is None:raise UnpricedModel(model.model)
            key = 'a10-'+fingerprint([execution,mode,payload])[:32]
            if key in self.budget.reservations():raise Pause('unsettled A10 reservation: reconcile provider billing before retry '+key)
            if not self._reserve(key,usd,'A10-RV','bounded verification pre-call reservation',steps=[step+'_'+key+'_'+name])[0]:
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
        register = self._contrary_register(pkg, self._findings() or [], plan or None, self.load('allocation_ledger.json'))
        from .verification_job import version
        digest = fingerprint([version(manuscript,plan,pkg,registry,tables),execution,cfg])[:24]
        job = VerificationJob(self.data('verification_jobs')/digest,manuscript,plan,pkg,registry,tables,
            cfg,call,count,execution,cache_directory=self.data('verification_cache'),prior_report=self.load('rv_latest.json',{}),
            contrary_register=register)
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

    def _journal_limits(self) -> dict:
        return config.load("journal_scirev").get("limits") or {}

    def submission_check(self) -> dict:
        """Recompute final/submission_status.json after the researcher edited the declarations (no model call).
        A finalised declaration is written into the exported manuscript's back matter by re-running the export."""
        final_dir = self.dir / "final"
        checks_path = final_dir / "export_checks.json"
        if not checks_path.exists():
            raise ValueError(f"run {self.id} has no export yet (final/export_checks.json): finish the run first")
        checks = json.loads(checks_path.read_text(encoding="utf-8"))
        ready = submission.status(final_dir, checks["reference_problems"], checks["table_problems"],
                                  checks["compliance"], self.load("retraction_cp2_selection.json"),
                                  checks.get("science_lint"))
        (final_dir / "submission_status.json").write_text(json.dumps(ready, indent=2), encoding="utf-8")
        self.prov.tool_run("submission_status", "recheck", {"submission_ready": ready["submission_ready"],
                                                            "blockers": len(ready["blockers"])})
        return ready

    def _journal(self) -> dict:
        """Journal profile handed to A08/A09 (pilot limits applied). Sample mode narrows the word limit."""
        return pilot.journal(self)

    def _outline_payload(self, pkg, corpus, journal, table, bcfg, findings) -> dict:
        from . import bridge, run_spec
        payload = bridge.outline_payload(pkg, corpus, journal, table, bcfg, findings)
        outline, _ = run_spec.load(self.dir)
        if outline:
            from .approved_scope import writing_outline
            payload["researcher_outline"] = writing_outline(self, outline)
            payload["source_access"] = self.load("source_access.json", {})
        from .approved_scope import enrich
        return enrich(self, 'A08-OL', payload)

    def _sample_mode(self) -> bool:
        return False

    def _bridge_inputs(self) -> tuple[dict, list[dict], list[dict]]:
        pkg = self._publishable("synthesis_approved.json")
        if not pkg:
            raise Pause("approved synthesis missing: the bridge has nothing to hand to the writing agents")
        findings = self._findings() or []
        from .scientific_validation import require_package
        try:   # Task 1's contract, against current evidence: the bridge never hands on what CP3 could not approve
            require_package(pkg, findings)
        except ValueError as exc:
            raise Pause(f"approved synthesis no longer satisfies its evidence contract: {exc}") from exc
        return pkg, findings, self.load("selected_corpus.json", [])

    def _reproject(self, stage: str) -> None:
        """Re-project the rest of the run from what has been spent, before the stage makes its first call. A
        projection over the cap stops the next call (_require_projection)."""
        proj = (pilot.project(self,pilot.STAGE_2 if STAGES.index(self.state()['stage'])>STAGES.index('cp3') else pilot.STAGE_1) if pilot.enabled(self) else cost_projection.remaining_for_run(self))
        if pilot.enabled(self):proj={**proj,'created':time.strftime('%Y-%m-%dT%H:%M:%S')}
        self.save("cost_projection.json", proj)
        self.prov.tool_run("reprojection", stage, {"projected_remaining_usd": proj["projected_remaining_usd"],
                                                   "projected_total_usd": proj["projected_total_usd"],
                                                   "verdict": proj["verdict"]})

    def _admitted(self, agent_id: str, payload: dict, step: str, schema_file: str | None = None,
                  exclude: frozenset = frozenset(), limit: str | None = None, extra: dict | None = None) -> dict:
        """One downstream request: bounded and checked against the model's window (admission.py), the pricing
        threshold, the projection line, the runtime gate and the cap (an existing reservation, held for the call).
        Raises AdmissionRefused when the request does not fit; the caller subdivides by its fixed rule or stops."""
        from . import admission
        from .approved_scope import enrich
        payload = enrich(self, agent_id, payload)
        from .synthesis_registry import fingerprint
        m = self.route(agent_id, exclude)
        overrides = {}
        if limit:   # an output cap sized to the unit requested (pipeline.yaml -> bridge.output_limits)
            overrides = {"max_tokens": int(self._bridge_cfg()["output_limits"][limit])}
            m = dataclasses.replace(m, **overrides)
        if extra:   # sample mode only: its own output cap / effort (singlepaper_eval.SAMPLE); default runs pass none
            overrides = {**overrides, **extra}
            m = dataclasses.replace(m, **extra)
        a = admission.assess(agent_id, payload, m, self.cfg.get("admission") or {}, self.budget.prices)
        from .writing_admission import worst_case_usd
        usd = worst_case_usd(self.budget, m, a["input_bound"], a["output_reserve"])   # input at cache-write rate
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
        ok, available = self._reserve(key, usd, agent_id, "downstream pre-call reservation", steps=[step])
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
        if pilot.enabled(self):
            try:pilot.require(self,agent_id)
            except pilot.AuthorizationRequired as exc:raise Pause(str(exc)) from exc
            return
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
            packets = bridge.section_packets(plan, ledger, pkg, findings, corpus,
                                             self._contrary_register(pkg, findings, plan, ledger))
        except bridge.BridgeError as exc:
            raise Pause(f"section packets: {exc}") from exc
        ev = bridge.evidence_version(pkg, findings)
        for sid, packet in packets.items():   # evidence A09 retrieved for a section stays in its packet
            saved = self.load(f"sections/{pv[:16]}/{sid}.json")
            if saved and saved.get("evidence_version") == ev:
                packet["retrieved"] = saved.get("retrieved") or {}
        return {"pkg": pkg, "findings": findings, "corpus": corpus, "plan": plan, "ledger": ledger, "packets": packets,
                "amap": bridge.argument_map(pkg, corpus, findings), "pv": pv, "ev": ev, "journal": self._journal(),
                "table": (self.load("display_items.json") or [None])[0]}

    def _contrary_register(self, pkg: dict, findings: list, plan: dict | None, ledger: list | None) -> list | None:
        """The contrary-evidence register for the current evidence, table record and plan (None before a table)."""
        from . import bridge
        full = self.load("display_items/T1.json")
        if not full or full.get("type") != "TABLE_COMPARISON" or full.get("status") != "BUILT":
            return None
        return bridge.contrary_register(pkg, findings, full, plan, ledger)

    def _contrary_release(self, m: dict, rv: dict) -> None:
        """Release gate: every material contrary finding is in the final table, addressed in A10-verified cited
        prose, or excluded by the researcher with a recorded justification (CP_CONTRARY, bound to this register and
        this verified manuscript). Anything else pauses the run; no table row may conceal its contrary evidence."""
        from . import bridge
        from .synthesis_registry import fingerprint
        full = self.load("display_items/T1.json") or {}
        if full.get("type") != "TABLE_COMPARISON" or full.get("status") != "BUILT":
            return    # no comparative table was built by the bridge (legacy runs): nothing to account for
        pkg, findings, _ = self._bridge_inputs()
        register = self._contrary_register(pkg, findings, self.load("manuscript_plan.json"),
                                           self.load("allocation_ledger.json"))
        if register is None:
            return
        digest = fingerprint({"register": register, "verification": rv.get("verification_fingerprint")})
        approved = checkpoints.review_approved(self.dir, "CP_CONTRARY", digest) or {}
        exclusions = {x["finding_id"]: x["justification"] for x in approved.get("exclusions") or []}
        acc = bridge.contrary_accounting(register, rv, self.load("display_items/T1.json"), exclusions)
        self.save("bridge/contrary_release.json", {"fingerprint": digest, **acc})
        self.prov.tool_run("contrary_release", rv.get("pass") or "release",
                           {"counts": acc["counts"], "unaddressed": acc["unaddressed"],
                            "table_conceals": acc["table_conceals"], "exclusions": exclusions})
        if acc["release_blocked"]:
            checkpoints.write_contrary_review(self.dir, digest, acc, register)
            self.pause_for_checkpoint("CP_CONTRARY")

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
        from .synthesis_registry import fingerprint
        payload = bridge.front_matter_payload(ps["plan"], sections, ps["amap"], ps["journal"], ps["table"])
        key = fingerprint([ps["pv"], ps["ev"], payload])
        cached = self.load(f"bridge/front_{label}.json") or {}
        if cached.get("key") == key:   # resuming: the front matter for exactly these sections is not requested again
            front = cached["front"]
        else:
            try:
                front = self._admitted("A09-WRI", payload, f"A09-WRI_{label}_front", schema_file="A09-WRI.front.schema.json",
                                       limit="A09_FRONT_MATTER")
            except AdmissionRefused as exc:
                raise Pause(f"front matter request not admitted ({exc})") from exc
            self.save(f"bridge/front_{label}.json", {"key": key, "front": front})
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
        from .synthesis_registry import fingerprint
        key = fingerprint([ps["pv"], ps["ev"], draft])
        cached = self.load(f"bridge/integrated_{label}.json") or {}
        if cached.get("key") == key:   # resuming: the same draft is not integrated (paid) again
            integrated = cached["integrated"]
        else:
            integrated = self._edit("INTEGRATION", draft, ps, f"A12-EDI_integration_{label}")
            self.save(f"bridge/integrated_{label}.json", {"key": key, "integrated": integrated})
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
        self._compliance_gate(proof, "A12-EDI PROOF")
        final = self._stamp(self._verify(proof, "FINAL", "A10-RV_final"), proof, ps)
        self.save("rv_final.json", final)
        if final.get("release_disposition") not in ("APPROVED", "APPROVED_WITH_MINOR_FINDINGS"):
            raise Pause(f"final verification: {final.get('release_disposition')} (see data/rv_final.json)")
        return "finalize"

    def _compliance_gate(self, m: dict, where: str) -> None:
        """A broken hard journal limit (tools/compliance.py) stops the run after editing: the edited manuscript is
        saved for inspection, but it is not verified, exported or called complete over the limit."""
        cited = tags.cited_records("\n".join(s.get("text_markdown", "") for s in m.get("sections", [])))
        comp = compliance.check({**m, "references": cited,
                                 "display_items": self.load("manuscript_plan.json", {}).get("display_items", [])})
        self.save("compliance_latest.json", {"where": where, **comp})
        if not comp["all_pass"]:
            detail = "; ".join(f"{c['rule']} ({c['detail']})" for c in comp["checks"] if c["hard"] and not c["pass"])
            raise Pause(f"{where}: the manuscript breaks journal limits: {detail}. See data/compliance_latest.json; "
                        "revise at CP3/CP_LEDGER or edit the saved manuscript, then run again.")

    def stage_finalize(self, st: dict) -> str:
        m = self._current()
        report = self.load('rv_final.json',{})
        defects = any(f.get('severity') in ('MAJOR','BLOCKING') for f in report.get('findings',[]))
        if defects or not self._verification_current(report,m) or report.get('release_disposition') not in ('APPROVED','APPROVED_WITH_MINOR_FINDINGS'):
            raise Pause('final release requires current complete A10 approval with no unresolved major/blocking findings')
        self._contrary_release(m, report)
        plan = self.load("manuscript_plan.json")
        corpus = {r["record_id"]: r for r in self.load("selected_corpus.json")}
        tables = self._built_tables()
        # tables come after the text, so a paper cited only in a table is numbered after every text citation
        texts = [s["text_markdown"] for s in m["sections"]] + [" ".join(c for row in t["rows"] for c in row)
                                                                for t in tables]
        numbers = references.number_citations(texts)
        missing = sorted(rid for rid in numbers if rid not in corpus)
        if missing:
            raise Pause(f"export stopped: the manuscript cites record ID(s) not in the selected corpus: "
                        f"{', '.join(missing)}. A citation to an unknown record cannot be numbered or referenced; "
                        "correct the text (data/manuscripts) and run again.")

        def render(text: str, where: str) -> str:
            try:
                return references.render_citations(text, numbers, where)
            except references.UnknownCitation as exc:
                raise Pause(f"export stopped: {exc}") from exc

        levels = {s.get("section_id"): s.get("level", 1) for s in plan.get("sections", [])}
        body = []
        for s in m["sections"]:
            t = tags.strip_tags(s["text_markdown"])
            t = render(t, f"section '{s['heading']}'")
            t = tags.DISPLAY_RE.sub(lambda x: ("Fig. " if x.group(1)[0] == "F" else "Table ") + x.group(1)[1:], t)
            body.append({"heading": s["heading"], "level": levels.get(s.get("section_id"), 1), "text": t})
        refs, ref_problems, retracted = [], {}, []
        for rid, n in sorted(numbers.items(), key=lambda x: x[1]):
            try:
                text, problems, meta = references.build_reference(corpus[rid], os.environ.get("CROSSREF_MAILTO"),
                                                                  cache_dir=self.data("crossref_cache"))
            except references.UnknownCitation as exc:
                raise Pause(f"export stopped: {exc}") from exc
            if meta is not None and references.is_retracted(meta):
                retracted.append(rid)
            refs.append(f"{n}. {text}")
            if problems:
                ref_problems[str(n)] = [f"{rid}: {p}" for p in problems]
        excused = (checkpoints.approved(self.dir, "CP2") or {}).get("retraction_exceptions") or {}
        retracted = [rid for rid in retracted if not str(excused.get(rid) or "").strip()]
        self.prov.tool_run("retraction_check", "export", {"cited": len(numbers), "retracted": retracted,
                                                          "references_with_problems": len(ref_problems)})
        if retracted:
            raise Pause(f"export stopped: cited paper(s) {', '.join(retracted)} are retracted according to Crossref "
                        "(retracted after CP2, or not checkable then). Remove the citations, or record a reason "
                        'under "retraction_exceptions" in CP2_approved.json, then run again.')
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
        provenance_summary = self._provenance_summary()
        declarations = submission.write_declaration_drafts(final_dir, provenance_summary)
        doc = {"title": m["title"], "abstract": m["abstract"], "keywords": m.get("keywords", []),
               "sections": body, "references": refs,
               "back_matter": submission.back_matter(declarations),
               "figures": figures,
               "tables": [{"display_id": t["display_id"], "columns": t["columns"],
                           "caption": captions.get(t["display_id"], "[CAPTION TO BE WRITTEN]"),
                           "rows": [[render(c, f"table {t['display_id']}") for c in row] for row in t["rows"]],
                           "notes": ["NR, not reported. Values are taken from validated findings; "
                                     "check against the source papers before submission."]
                                    + [render(n["text"], f"table {t['display_id']} note")
                                       for n in t.get("inconsistency_notes", [])]
                                    + [tags.strip_tags(n) for n in t.get("notes", [])]
                                    + ([f"Left blank for the authors: {', '.join(t['unmapped_columns'])}."]
                                       if t.get("unmapped_columns") else [])}
                          for t in tables]}
        (final_dir / "manuscript.md").write_text(manuscript_export.render_markdown(doc), encoding="utf-8")
        manuscript_export.render_docx(doc, final_dir / "manuscript.docx")
        comp = compliance.check({**m, "references": list(numbers),
                                 "display_items": self.load("manuscript_plan.json").get("display_items", [])})
        (final_dir / "compliance.json").write_text(json.dumps(comp, indent=2), encoding="utf-8")
        (final_dir / "costs.txt").write_text(self.budget.summary_text(), encoding="utf-8")
        (final_dir / "provenance_summary.json").write_text(json.dumps(provenance_summary, indent=2),
                                                           encoding="utf-8")
        exported = {d["display_id"]: d for d in doc["tables"]}
        table_issues = submission.table_problems(
            [{**t, "caption": exported[t["display_id"]]["caption"], "notes": exported[t["display_id"]]["notes"]}
             for t in tables], corpus, float(self._journal_limits().get("table_max_pages", 1)))
        from . import run_spec
        outline_now, _ = run_spec.load(self.dir)
        if outline_now:
            from .approved_scope import writing_outline
            outline_now = writing_outline(self, outline_now)
        lengths = (run_spec.chapter_word_report(outline_now, m["sections"], compliance.word_count,
                                                float((self.cfg.get("run_spec") or {}).get("chapter_tolerance", 0.15)))
                   if outline_now else [])
        (final_dir / "chapter_lengths.json").write_text(json.dumps(lengths, indent=2), encoding="utf-8")
        from .tools import science_lint
        access = {rid: a.get("level") for rid, a in (self.load("source_access.json", {}) or {}).items()}
        lint = science_lint.check_manuscript(m, access or None)
        (final_dir / "science_lint.json").write_text(json.dumps(lint, ensure_ascii=False, indent=2), encoding="utf-8")
        ready = submission.status(final_dir, ref_problems, table_issues, comp,
                                  self.load("retraction_cp2_selection.json"), lint)
        export_checks = {"reference_problems": ref_problems, "table_problems": table_issues, "compliance": comp,
                         "science_lint": lint}
        (final_dir / "export_checks.json").write_text(json.dumps(export_checks, indent=2), encoding="utf-8")
        (final_dir / "submission_status.json").write_text(json.dumps(ready, indent=2), encoding="utf-8")
        self.prov.tool_run("submission_status", "export", {"submission_ready": ready["submission_ready"],
                                                           "blockers": len(ready["blockers"])})
        notify.send("complete", f"Run {self.id}: review draft exported ("
                    + ("submission-ready" if ready["submission_ready"] else f"{len(ready['blockers'])} blockers") + ")",
                    ("Submission checklist: all items pass.\n" if ready["submission_ready"] else
                     "NOT submission-ready. Blockers (final/submission_status.json):\n- "
                     + "\n- ".join(ready["blockers"][:40]) + "\n\n")
                    + f"Compliance: {'PASS' if comp['all_pass'] else 'see compliance.json'}\n"
                    f"Main text: {comp['main_text_words']} words, {comp['references']} references\n\n"
                    f"{self.budget.summary_text()}\n\n"
                    f"{verification_scope.detail_report_text(self._a10_detail_report())}",
                    attachments=[final_dir / "manuscript.docx", final_dir / "manuscript.md", final_dir / "compliance.json",
                                 final_dir / "provenance_summary.json"])
        return "done"
