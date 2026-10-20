"""Orchestrator: a deterministic state machine. It routes; it never makes scientific judgements.

Run state lives in runs/<run_id>/state.json, so a run can stop (checkpoint, budget, error)
and resume exactly where it left off with `litreview run <run_id>`.

Stage order
  scope -> cp1 -> search -> qualify -> expand -> cp2 -> extract -> validate -> synthesize -> cp3
  -> outline -> draft -> review_loop -> finish_edit -> finalize -> done
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path

from . import checkpoints, config, notify
from .agents import AgentError, run_agent
from .budget import BudgetExceeded, BudgetTracker, UnpricedModel
from .paths import RUNS_DIR
from .provenance import ProvenanceLog
from .tools import compliance, display_items, manuscript_export, references, span_check, tags
from .tools.fulltext import fetch_sections
from .tools.literature import Record, enabled_sources, search
from .tools.literature.dedup import deduplicate
from .tools.literature.expansion import choose_next_seeds, choose_seeds, expand
from .tools.normalization import normalize_entities

STAGES = ["scope", "cp1", "search", "qualify", "expand", "cp2", "extract", "validate", "synthesize", "cp3",
          "outline", "draft", "review_loop", "finish_edit", "finalize", "done"]


class Pause(Exception):
    """Stop the run and wait for the researcher."""


# ------------------------------------------------------------------ run setup
def new_run(topic: str, notes: str = "", seeds: list[str] | None = None) -> str:
    run_id = time.strftime("%Y%m%d-%H%M%S")
    d = RUNS_DIR / run_id / "input"
    d.mkdir(parents=True)
    (d / "topic.md").write_text(topic, encoding="utf-8")
    (d / "notes.md").write_text(notes, encoding="utf-8")
    (d / "seeds.txt").write_text("\n".join(seeds or []), encoding="utf-8")
    Run(run_id).save_state({"stage": "scope", "status": "READY", "counters": {}})
    return run_id


class Run:
    def __init__(self, run_id: str):
        self.id = run_id
        self.dir = RUNS_DIR / run_id
        self.budget = BudgetTracker(self.dir)
        self.prov = ProvenanceLog(self.dir)
        self.cfg = config.load("pipeline")

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

    def agent(self, agent_id: str, payload: dict, step: str) -> dict:
        out = run_agent(agent_id, payload, self.dir, step, self.budget, self.prov)
        if self.budget.should_warn():
            notify.send("budget_warning", f"Run {self.id}: 80% of budget used", self.budget.summary_text())
        return out

    def counter(self, st: dict, key: str) -> int:
        st["counters"][key] = st["counters"].get(key, 0) + 1
        self.save_state(st)
        return st["counters"][key]

    # --- main loop -----------------------------------------------------
    def run(self) -> str:
        st = self.state()
        st["status"] = "RUNNING"
        self.save_state(st)
        try:
            while st["stage"] != "done":
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
        self.save("spec_approved.json", spec)
        return "search"

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
        todo = [r for r in records if r["record_id"] not in quals]
        size = int(self.cfg["loops"]["cq_batch_size"])
        fields = ("record_id", "title", "abstract", "authors", "year", "venue", "publication_type", "doi",
                  "pmid", "nct_id", "is_preprint", "query_family_ids", "expansion")
        for i in range(0, len(todo), size):
            batch = [{**{k: r.get(k) for k in fields},
                      "content_level": "ABSTRACT" if r.get("abstract") else "METADATA_ONLY"} for r in todo[i:i + size]]
            out = self.agent("A04-CQ", {"review_spec": spec, "batch_id": f"B{i // size + 1:03d}",
                                        "records": batch}, step=f"A04-CQ_B{i // size + 1:03d}")
            got = {q["record_id"]: q for q in out.get("qualifications", [])}
            for r in batch:  # nothing may disappear: any record without a disposition is flagged
                quals[r["record_id"]] = got.get(r["record_id"]) or {
                    "record_id": r["record_id"], "disposition": "UNRESOLVED_HUMAN_REVIEW",
                    "reason": "Agent returned no disposition for this record.", "themes": [], "flags": []}
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
                quals[rid] = {**q, "_fulltext_checked": True}
        self.save("qualifications.json", list(quals.values()))
        self.save("bias_report.json", self._bias_report(records, list(quals.values())))

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
        return {"exclusion_rate_by_query_purpose": rates, "excluded_seed_records": excluded_seeds,
                "qualified_per_theme": dict(themes),
                "note": "A markedly higher exclusion rate for CONTRARY_EVIDENCE, or any excluded seed, "
                        "suggests a screening or criteria problem."}

    def stage_cp2(self, st: dict) -> str:
        decision = checkpoints.approved(self.dir, "CP2")
        if not decision:
            checkpoints.write_cp2(self.dir, self.load("records.json"), self.load("qualifications.json"),
                                  self.load("bias_report.json"))
            self.pause_for_checkpoint("CP2")
        by_id = {r["record_id"]: r for r in self.load("records.json")}
        quals = {q["record_id"]: q for q in self.load("qualifications.json")}
        corpus = []
        for rid in decision["selected_record_ids"]:
            q = quals.get(rid, {})
            corpus.append({**by_id[rid], "role": q.get("role") or "PRIMARY", "themes": q.get("themes", []),
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
            out = self.agent("A05-KE", {"review_spec": spec, "content_level": level,
                                        "record": {**rec, "content": sections}}, step=f"A05-KE_{rid}")
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
            for attempt in range(max_re + 1):
                ext = self.load(f"extractions/{rid}.json")
                gate1 = span_check.check_findings(ext, sections)
                val = self.agent("A06-SV", {"mode": "PER_PAPER", "review_spec": spec, "extraction": ext,
                                            "gate1_results": gate1, "paper_text": sections},
                                 step=f"A06-SV_{rid}_v{attempt + 1}")
                serious = [d for d in val.get("defect_reports", []) if d.get("severity") in ("CRITICAL", "MAJOR")]
                if not serious or attempt == max_re:
                    break
                ext = self.agent("A05-KE", {"review_spec": spec, "content_level": ext.get("content_level"),
                                            "record": {**rec, "content": sections},
                                            "defects_from_previous_extraction": serious},
                                 step=f"A05-KE_{rid}_reextract")
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
            theme_records[th] = self.agent("A06-SV", {"mode": "PER_THEME", "theme": th, "validated_findings": fs,
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
                            "themes": f.get("themes") or rec.get("themes", []),
                            "subject": f.get("subject_entity_id"), "predicate": f.get("predicate"),
                            "object": f.get("object_entity_id"), "polarity": f.get("polarity"),
                            "span": f.get("span"), "quantities": f.get("quantities", []),
                            "context": ctx.get(f.get("context_id"), {}).get("fields"),
                            "disposition": v.get("disposition"), "constraints": v.get("constraints", []),
                            "plain_language_limit": v.get("plain_language_limit"),
                            "entities": {e["entity_id"]: {k: e.get(k) for k in (
                                "mention", "type", "approved_symbol", "normalized_id", "normalization_state",
                                "drug_status_verified", "drug_status_conflict", "drugbank_id",
                                "problematic_cell_line") if e.get(k) is not None}
                                for e in ext.get("entities", [])}})
        return out

    def stage_synthesize(self, st: dict) -> str:
        corpus = self.load("selected_corpus.json")
        theme_records = self.load("theme_records.json")
        manifest = [{"item_id": f"PAPER:{r['record_id']}", "kind": "SELECTED_PAPER", "required_visibility": "CITED",
                     "narrative_required": r.get("tier") == "CORE" and bool(r.get("is_contrary_evidence"))}
                    for r in corpus]
        for th, rec in theme_records.items():
            for i, c in enumerate(rec.get("conflicts", []), 1):
                manifest.append({"item_id": f"CONFLICT:{th}:{i}", "kind": "CONFLICT", "detail": c,
                                 "required_visibility": "NARRATIVE"})
            manifest.append({"item_id": f"REACH:{th}", "kind": "EVIDENCE_REACH",
                             "detail": rec.get("evidence_reach"), "required_visibility": "NARRATIVE"})
            for m in (rec.get("evidence_reach") or {}).get("systems_missing", []):
                manifest.append({"item_id": f"MISSING:{th}:{m}", "kind": "SYSTEM_GAP", "required_visibility": "NARRATIVE"})
        self.save("coverage_manifest.json", manifest)
        pkg = self.agent("A07-SYN", {"review_spec": self.load("spec_approved.json"),
                                     "selected_corpus": [{k: r.get(k) for k in ("record_id", "title", "authors", "year",
                                                                                "venue", "tier", "themes", "is_preprint")}
                                                         for r in corpus],
                                     "validated_findings": self.load("validated_findings.json"),
                                     "theme_records": theme_records, "coverage_manifest": manifest,
                                     "revision_feedback": self.load("cp3_feedback.json")},
                         step=f"A07-SYN_v{self.counter(st, 'synth')}")
        self.save("synthesis_package.json", pkg)
        return "cp3"

    def stage_cp3(self, st: dict) -> str:
        decision = checkpoints.approved(self.dir, "CP3")
        if not decision:
            checkpoints.write_cp3(self.dir, self.load("synthesis_package.json"))
            self.pause_for_checkpoint("CP3")
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
                                     "journal_profile": config.load("journal_scirev")},
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
        built = display_items.build_all(plan, self.load("synthesis_approved.json"),
                                        self.load("validated_findings.json", []),
                                        self.load("selected_corpus.json", []), out_dir)
        self.save("display_items.json", built)
        self.prov.tool_run("display_items", "outline",
                           {d["display_id"]: d["status"] for d in built})
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

    def _deterministic_report(self, m: dict) -> dict:
        plan = self.load("manuscript_plan.json", {})
        known = {i["item_id"] for s in plan.get("sections", []) for i in s.get("ordered_items", [])} | {"ORG"}
        selected = {r["record_id"] for r in self.load("selected_corpus.json", [])}
        text = "\n".join(s.get("text_markdown", "") for s in m.get("sections", []))
        binds = tags.bindings(text)
        built = self.load("display_items.json", [])
        cited = tags.cited_records(text) + tags.cited_records(
            " ".join(c for d in built if d.get("kind") == "TABLE" for row in d.get("rows", []) for c in row))
        return {
            "display_item_warnings": {d["display_id"]: d.get("warnings") for d in built if d.get("warnings")},
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
            rv = self._verify(draft, "DRAFT", f"A10-RV_draft{i + 2}")
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
            rv = self._verify(ed, "REVISION", f"A10-RV_revision{cycle}", ed.get("change_log"))
            self.save("rv_latest.json", rv)
        raise Pause("critique cycles exhausted without ACCEPT — review data/rc_latest.json "
                    "(the draft is never accepted just because cycles ran out)")

    def stage_finish_edit(self, st: dict) -> str:
        plan = self.load("manuscript_plan.json")
        line = self.agent("A12-EDI", {"mode": "LINE", "manuscript": self._current(), "manuscript_plan": plan},
                          step="A12-EDI_line")
        self._save_manuscript(line, "m03_line")
        rv = self._verify(line, "REVISION", "A10-RV_line", line.get("change_log"))
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
                                    + ([f"Left blank for the authors: {', '.join(t['unmapped_columns'])}."]
                                       if t.get("unmapped_columns") else [])}
                          for t in tables]}
        (final_dir / "manuscript.md").write_text(manuscript_export.render_markdown(doc), encoding="utf-8")
        manuscript_export.render_docx(doc, final_dir / "manuscript.docx")
        comp = compliance.check({**m, "references": list(numbers),
                                 "display_items": self.load("manuscript_plan.json").get("display_items", [])})
        (final_dir / "compliance.json").write_text(json.dumps(comp, indent=2), encoding="utf-8")
        (final_dir / "costs.txt").write_text(self.budget.summary_text(), encoding="utf-8")
        ev = self.prov.events()
        prov = {"agent_calls": sum(e["type"] == "agent_call" for e in ev),
                "human_decisions": [e for e in ev if e["type"] == "human_decision"],
                "verification_statement": self.load("rv_final.json", {}).get("verification_statement")}
        (final_dir / "provenance_summary.json").write_text(json.dumps(prov, indent=2), encoding="utf-8")
        notify.send("complete", f"Run {self.id}: review draft complete",
                    f"Compliance: {'PASS' if comp['all_pass'] else 'see compliance.json'}\n"
                    f"Main text: {comp['main_text_words']} words, {comp['references']} references\n\n"
                    f"{self.budget.summary_text()}",
                    attachments=[final_dir / "manuscript.docx", final_dir / "manuscript.md", final_dir / "compliance.json",
                                 final_dir / "provenance_summary.json"])
        return "done"
