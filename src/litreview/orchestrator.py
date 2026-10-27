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

from . import checkpoints, config, model_record, notify
from .agents import AgentError, RefusalError, run_agent
from .agents.base import prompt_version
from .budget import BudgetExceeded, BudgetTracker, UnpricedModel
from .paths import RUNS_DIR
from .provenance import ProvenanceLog
from . import synthesis_input, theme_framework
from .agents.base import build_system_prompt, user_parts
from .synthesis_job import JobStopped, SynthesisJob
from .tools import compliance, display_items, manuscript_export, references, span_check, tags, themes
from .tools.fulltext import fetch_sections
from .tools.literature import Record, enabled_sources, search
from .tools.literature.dedup import deduplicate
from .tools.literature.expansion import choose_next_seeds, choose_seeds, expand
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
    Run(run_id).save_state({"stage": "scope", "status": "READY", "counters": {}})
    return run_id


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

    def route(self, agent_id: str) -> config.AgentModel:
        """First of the agent's candidate models that has not refused in this run's topic family."""
        refused = model_record.refused(self.family())
        candidates = config.agent_candidates(agent_id)
        for m in candidates:
            if m.model not in refused:
                if m is not candidates[0]:
                    self._check_alternate_cost(agent_id, candidates[0].model, m.model)
                return m
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

    def _check_alternate_cost(self, agent_id: str, primary: str, alternate: str) -> None:
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
        msg = (f"{agent_id}: {primary} has refused this topic family, and its alternate {alternate} would cost "
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

    def agent(self, agent_id: str, payload: dict, step: str, overrides: dict | None = None,
              schema_file: str | None = None) -> dict:
        m = self.route(agent_id)
        if overrides:
            m = dataclasses.replace(m, **overrides)
        try:
            out = run_agent(agent_id, payload, self.dir, step, self.budget, self.prov, model=m,
                            schema_file=schema_file)
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
        self.save_state(st)
        return st["status"]

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
        self.save("selected_corpus.json", corpus)
        return "extract"

    def stage_extract(self, st: dict) -> str:
        spec = self.load("spec_approved.json")
        for rec in self.load("selected_corpus.json"):
            rid = rec["record_id"]
            if self.data(f"extractions/{rid}.json").exists():
                continue
            sections = fetch_sections(rec.get("pmcid")) or {"Abstract": rec.get("abstract") or ""}
            level = "FULL_TEXT" if len(sections) > 1 else "ABSTRACT"
            self.save(f"fulltext/{rid}.json", sections)
            out = self.agent("A05-KE", {"review_spec": spec, "theme_framework": self.load("theme_framework.json"),
                                        "content_level": level, "record": {**rec, "content": sections}},
                             step=f"A05-KE_{rid}")
            self.save(f"extractions/{rid}.json", normalize_entities(out, self.data("normalization_cache.json")))
        return "validate"

    def stage_validate(self, st: dict) -> str:
        spec = self.load("spec_approved.json")
        corpus = self.load("selected_corpus.json")
        max_re = int(self.cfg["loops"]["max_reextractions"])
        for rec in corpus:
            rid = rec["record_id"]
            if self.data(f"validations/{rid}.json").exists():
                continue
            sections = self.load(f"fulltext/{rid}.json")
            # resume after an interruption: a paper already re-extracted continues at its next validation
            start = 1 if (self.dir / "outputs" / f"A05-KE_{rid}_reextract.json").exists() else 0
            label_offset = start - min(start, max_re)   # keeps v2 as v2 if re-extraction was later turned off
            for attempt in range(min(start, max_re), max_re + 1):
                ext = self.load(f"extractions/{rid}.json")
                gate1 = span_check.check_findings(ext, sections)
                val = self.agent("A06-SV", {"mode": "PER_PAPER", "review_spec": spec, "extraction": ext,
                                            "gate1_results": gate1, "paper_text": sections},
                                 step=f"A06-SV_{rid}_v{attempt + 1 + label_offset}")
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
                self.save(f"extractions/{rid}.json", normalize_entities(ext, self.data("normalization_cache.json")))
            self.save(f"validations/{rid}.json", val)
        # theme-level pass
        findings = self._validated_findings(corpus)
        by_theme: dict[str, list] = defaultdict(list)
        for f in findings:
            for th in f["themes"] or ["(unthemed)"]:
                by_theme[th].append(f)
        same_study = {r["record_id"]: [x for x in r.get("flags", []) if "SAME_STUDY" in x] for r in corpus}
        theme_records = {}
        for th, fs in by_theme.items():
            definition = next((t for t in (self.load("theme_framework.json") or {}).get("primary_themes", [])
                               if t["theme_id"] == th), None)
            theme_records[th] = self.agent("A06-SV", {"mode": "PER_THEME", "theme": th, "theme_definition": definition,
                                                      "validated_findings": fs,
                                                      "same_study_flags": same_study,
                                                      "records": [{k: r.get(k) for k in ("record_id", "authors", "year", "title")}
                                                                  for r in corpus]},
                                           step=f"A06-SV_theme_{re.sub(r'[^A-Za-z0-9]+', '_', th)[:40]}")
        self.save("validated_findings.json", findings)
        self.save("theme_records.json", theme_records)
        return "synthesize"

    def _validated_findings(self, corpus: list[dict]) -> list[dict]:
        """Join A05 findings with A06 dispositions into one compact list with global IDs (R0001:F3)."""
        out = []
        for rec in corpus:
            rid = rec["record_id"]
            ext = self.load(f"extractions/{rid}.json", {})
            val = {v["finding_id"]: v for v in self.load(f"validations/{rid}.json", {}).get("validations", [])}
            ctx = {c["context_id"]: c for c in ext.get("contexts", [])}
            for f in ext.get("findings", []):
                v = val.get(f["finding_id"], {})
                out.append({"finding_id": f"{rid}:{f['finding_id']}", "record_id": rid,
                            **self._finding_themes(f, rec),
                            "subject": f.get("subject_entity_id"), "predicate": f.get("predicate"),
                            "object": f.get("object_entity_id"), "polarity": f.get("polarity"),
                            "span": f.get("span"), "quantities": f.get("quantities", []),
                            "context_id": f"{rid}:{f['context_id']}" if f.get("context_id") else None,
                            "context": ctx.get(f.get("context_id"), {}).get("fields"),
                            "disposition": v.get("disposition"), "constraints": v.get("constraints", []),
                            "plain_language_limit": v.get("plain_language_limit"),
                            # only this finding's own subject and object, not the paper's whole entity list
                            "entities": {e["entity_id"]: {k: e.get(k) for k in (
                                "mention", "type", "approved_symbol", "normalized_id", "normalization_state",
                                "drug_status_verified", "drug_status_conflict", "drugbank_id",
                                "problematic_cell_line") if e.get(k) is not None}
                                for e in ext.get("entities", [])
                                if e["entity_id"] in (f.get("subject_entity_id"), f.get("object_entity_id"))}})
        return out

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
        """A07 as one logical job over bounded calls (synthesis_job.py). The frozen corpus is the cached
        prefix of every call; the runtime keeps the coverage and finding ledgers."""
        corpus = self.load("selected_corpus.json")
        theme_records = self.load("theme_records.json")
        findings, theme_records_for_a07 = self._consolidate_themes(self.load("validated_findings.json"), theme_records)
        manifest = synthesis_input.build_manifest(corpus, theme_records, self._inconsistency_items(corpus))
        self.save("coverage_manifest.json", manifest)
        feedback = self.load("cp3_feedback.json")
        frozen = {**synthesis_input.build_corpus(self.load("spec_approved.json"), corpus, findings,
                                                 theme_records_for_a07, manifest, self.load("theme_framework.json")),
                  "revision_feedback": feedback}
        scfg = self.cfg["synthesis"]
        # a CP3 revision starts a new job; an interrupted job resumes in the same directory
        tag = hashlib.sha256(json.dumps(feedback, sort_keys=True).encode()).hexdigest()[:8]
        overrides = {"cache_system": True, "cache_payload": ("corpus",), "cache_ttl": scfg.get("cache_ttl", "5m"),
                     "max_tokens": int(scfg["max_tokens_per_turn"])}

        def call(mode: str, turn: dict, name: str) -> dict:
            return self.agent("A07-SYN", {"corpus": frozen, "turn": turn}, step=f"A07-SYN_job{tag}_{name}",
                              overrides=overrides, schema_file=f"A07-SYN.{mode.lower()}.schema.json")

        def count(turn: dict) -> int:
            m = self.route("A07-SYN")
            parts = user_parts({"corpus": frozen, "turn": turn}, ("corpus",))
            if m.provider != "anthropic":   # no counting endpoint: conservative estimate (2.5 chars/token)
                return int(sum(len(p["text"]) for p in parts) / 2.5) + 20000
            from .llm import anthropic_client
            return anthropic_client.count_tokens(build_system_prompt("A07-SYN"), parts, m.model, True,
                                                 overrides["cache_ttl"])

        job = SynthesisJob(self.dir / "data" / f"synthesis_job_{tag}", synthesis_input.mandatory_items(manifest),
                           [f["finding_id"] for f in findings], {f["finding_id"]: f["record_id"] for f in findings},
                           call, count, scfg, served_by=lambda: self.last_model)
        try:
            pkg = job.run()
        except JobStopped as e:
            self.save(f"synthesis_job_{tag}/report.json", self._job_report(tag, job.assemble()))
            raise Pause(f"synthesis job stopped cleanly — {e}. `litreview run` resumes from the last committed turn.")
        self.save(f"synthesis_job_{tag}/report.json", self._job_report(tag, pkg))
        self.save("synthesis_package.json", pkg)
        # which model produced which turns: the source for the AI-use disclosure (provenance_summary.json)
        self.prov.tool_run("synthesis_job", f"A07-SYN_job{tag}",
                           {"models": pkg["models"], "mixed_models": len(pkg["models"]) > 1,
                            "models_by_turn": pkg["models_by_turn"]})
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
    _USABLE = {"SUPPORTED", "SUPPORTED_WITH_CONSTRAINTS", "SUPPORTED_FOR_OBSERVATION", "PARTIALLY_SUPPORTED"}

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
            pkg = self.load("synthesis_package.json")
            checkpoints.write_cp3(self.dir, pkg,
                                  emerging=theme_framework.emerging(self.load("validated_findings.json", []), "finding_id"),
                                  framework=self.load("theme_framework.json"))
            self.pause_for_checkpoint("CP3")
        self._framework_update(decision, "CP3")
        pkg = self.load("synthesis_package.json")
        pkg["researcher_decision"] = decision
        adopted = set(decision.get("adopted_interpretations", []))
        pkg["author_interpretations"] = [{**p, "type": "AUTHOR_INTERPRETATION", "id": p["pi_id"].replace("PI", "AI")}
                                         for p in pkg.get("proposed_interpretations", []) if p.get("pi_id") in adopted]
        pkg["proposed_interpretations"] = []  # unadopted proposals do not exist downstream
        self.save("synthesis_approved.json", pkg)
        return "outline"

    def stage_outline(self, st: dict) -> str:
        plan = self.agent("A08-OL", {"synthesis_package": self.load("synthesis_approved.json"),
                                     "selected_corpus": self.load("selected_corpus.json"),
                                     "journal_profile": config.load("journal_scirev"),
                                     "display_preference": (self.cfg.get("outline") or {}).get("display_preference")},
                          step=f"A08-OL_v{self.counter(st, 'outline')}")
        self.save("manuscript_plan.json", plan)
        if plan.get("status") == "NEEDS_HUMAN_INPUT":
            raise Pause("A08-OL needs input (see data/manuscript_plan.json warnings); "
                        "adjust the selection or plan, then run again")
        self._build_display_items(plan)
        return "draft"

    def _build_display_items(self, plan: dict) -> list[dict]:
        """Tables and the evidence map from validated findings (code only; A08-OL supplies no values)."""
        out_dir = self.dir / "data" / "display_items"
        if out_dir.exists():
            shutil.rmtree(out_dir)   # a new plan replaces every item
        incons = self.load("inconsistencies.json", [])
        built = display_items.build_all(plan, self.load("synthesis_approved.json"),
                                        self.load("validated_findings.json", []),
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
        return self.agent("A10-RV", {"pass": pass_, "manuscript": manuscript,
                                     "manuscript_plan": self.load("manuscript_plan.json"),
                                     "synthesis_package": self.load("synthesis_approved.json"),
                                     "validated_findings": self.load("validated_findings.json"),
                                     "deterministic_report": self._deterministic_report(manuscript),
                                     "changed_passages": changed}, step=step)

    def _maybe_verify(self, manuscript: dict, pass_: str, step: str, previous: dict,
                      changed: list | None = None) -> dict:
        """An intermediate A10 check (after a redraft, a revision or the line edit). With
        loops.verification: draft_and_final only the first-draft and final checks run; a skipped check is
        logged, and the previous findings are passed on, marked as describing an earlier version."""
        if self.cfg["loops"].get("verification", "all") != "draft_and_final":
            return self._verify(manuscript, pass_, step, changed)
        self.prov.tool_run("verification_skipped", step, {"reason": "loops.verification: draft_and_final"})
        return {**previous, "stale": f"{step} skipped; these findings describe an earlier version"}

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

    def stage_draft(self, st: dict) -> str:
        plan = self.load("manuscript_plan.json")
        draft = self.agent("A09-WRI", {"manuscript_plan": plan, "journal_profile": config.load("journal_scirev")},
                           step="A09-WRI_draft1")
        self._save_manuscript(draft, "m01_draft")
        rv = self._verify(draft, "DRAFT", "A10-RV_draft1")
        for i in range(int(self.cfg["loops"]["max_redrafts"])):
            blocking = [f for f in rv.get("findings", []) if f.get("severity") == "BLOCKING"
                        and f.get("responsible_stage") == "A09-WRI"]
            if not blocking and not rv.get("systemic_failure"):
                break
            draft = self.agent("A09-WRI", {"manuscript_plan": plan, "journal_profile": config.load("journal_scirev"),
                                           "revision_request": rv.get("findings"), "previous_draft": draft},
                               step=f"A09-WRI_draft{i + 2}")
            self._save_manuscript(draft, f"m01_draft{i + 2}")
            rv = self._maybe_verify(draft, "DRAFT", f"A10-RV_draft{i + 2}", rv)
        self.save("rv_latest.json", rv)
        return "review_loop"

    def stage_review_loop(self, st: dict) -> str:
        plan, pkg = self.load("manuscript_plan.json"), self.load("synthesis_approved.json")
        for cycle in range(1, int(self.cfg["loops"]["max_critique_cycles"]) + 1):
            m, rv = self._current(), self.load("rv_latest.json")
            rc = self.agent("A11-RC", {"manuscript": m, "manuscript_plan": plan, "synthesis_package": pkg,
                                       "a10_findings": rv, "journal_profile": config.load("journal_scirev"),
                                       "previous_critique": self.load("rc_latest.json")},
                            step=f"A11-RC_cycle{cycle}")
            self.save("rc_latest.json", rc)
            if rc["decision"] == "ACCEPT":
                return "finish_edit"
            if rc["decision"] == "HOLD_FOR_UPSTREAM_REVIEW":
                raise Pause("A11-RC requests upstream review (see data/rc_latest.json)")
            ed = self.agent("A12-EDI", {"mode": "REVISION", "manuscript": m, "manuscript_plan": plan,
                                        "critique": rc, "verification_findings": rv.get("findings")},
                            step=f"A12-EDI_revision{cycle}")
            self._save_manuscript(ed, f"m02_revision{cycle}")
            rv = self._maybe_verify(ed, "REVISION", f"A10-RV_revision{cycle}", rv, ed.get("change_log"))
            self.save("rv_latest.json", rv)
        raise Pause("critique cycles exhausted without ACCEPT — review data/rc_latest.json "
                    "(the draft is never accepted just because cycles ran out)")

    def stage_finish_edit(self, st: dict) -> str:
        plan = self.load("manuscript_plan.json")
        line = self.agent("A12-EDI", {"mode": "LINE", "manuscript": self._current(), "manuscript_plan": plan},
                          step="A12-EDI_line")
        self._save_manuscript(line, "m03_line")
        rv = self._maybe_verify(line, "REVISION", "A10-RV_line", {}, line.get("change_log"))
        if rv.get("finding_severity") == "BLOCKING":
            self.save("rv_latest.json", rv)
            raise Pause("blocking findings after line edit (see data/rv_latest.json)")
        proof = self.agent("A12-EDI", {"mode": "PROOF", "manuscript": line, "manuscript_plan": plan},
                           step="A12-EDI_proof")
        self._save_manuscript(proof, "m04_proof")
        final = self._verify(proof, "FINAL", "A10-RV_final")
        self.save("rv_final.json", final)
        if final.get("release_disposition") not in ("APPROVED", "APPROVED_WITH_MINOR_FINDINGS"):
            raise Pause(f"final verification: {final.get('release_disposition')} (see data/rv_final.json)")
        return "finalize"

    def stage_finalize(self, st: dict) -> str:
        m = self._current()
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
                    f"{self.budget.summary_text()}",
                    attachments=[final_dir / "manuscript.docx", final_dir / "manuscript.md", final_dir / "compliance.json",
                                 final_dir / "provenance_summary.json"])
        return "done"
