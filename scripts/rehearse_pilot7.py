"""Offline rehearsal of the paid discovery pilot, end to end, through the real run loop. No key, no network, no cost.

    python scripts/rehearse_pilot7.py [--keep DIR]

What is real: Run.run() and every stage handler from scope to export, under the pilot7 profile and the researcher's
outline (docs/pilot7/outline.json): the outline reaching scope, search and screening; deduplication; the CP2
proposal, the 7-paper cap and the frozen corpus manifest; full-text retrieval and its log; the early check;
extraction normalization; A06 batches, paging and the instability retest; the A07 job; the bridge, writing,
verification, critique, editing and export; every reservation, receipt and ledger entry of A02-A06; the pilot
report.

What is scripted:
  - the literature: the search returns records of the October 2026 reference run (real titles, abstracts and full
    texts, a different topic); citation expansion returns nothing; Crossref is offline;
  - the models: A02-A06 replay the October run's own extractions and validations of those papers (real verbatim
    spans); A07 is the scripted FixtureModel; A08-A12 are the scripted Agents of the bridge simulation, with A08's
    plan mapped onto the outline's section IDs;
  - every checkpoint is approved by this script, as a researcher would after reading it.
So it proves the route and the machinery hold, not that any science or prose is good. Vendor batching is switched
off here (its path is tested separately in tests/test_batch_stage.py).

Exit 0 when the run reaches export and the checks below pass.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
OCT = ROOT / "runs" / "20261025-100039"
DROPPED: dict[str, int] = {}
CHECKPOINT_NOTES = "Rehearsal: read the review files and approved as a researcher would; scripted, no science judged."


def offline():
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "OPENAI_BASE_URL"):
        os.environ.pop(k, None)
    os.environ["LANGSMITH_TRACING"] = "false"

    def refuse(*a, **k):
        raise OSError("rehearsal: network refused")
    socket.socket.connect = refuse
    socket.create_connection = refuse
    socket.getaddrinfo = refuse


class October:
    """The reference run's records and outputs, keyed by publication (PMID or normalized title)."""

    def __init__(self):
        d = OCT / "data"
        if not d.exists():
            raise SystemExit(f"the reference run is not at {OCT}: copy runs/20261025-100039 from the main checkout")
        self.records = json.loads((d / "records.json").read_text(encoding="utf-8"))
        self.selected = {r["record_id"]: r for r in json.loads((d / "selected_corpus.json").read_text(encoding="utf-8"))}
        self.data = d

    def key(self, r):
        return str(r.get("pmid") or "") or re.sub(r"[^a-z0-9]+", " ", (r.get("title") or "").lower()).strip()

    def by_key(self):
        return {self.key(r): r for r in self.records}

    def pool(self, n_extra=20):
        """The selected October papers (to be qualified) plus some others (to be excluded)."""
        chosen = [r for r in self.records if r["record_id"] in self.selected]
        others = [r for r in self.records if r["record_id"] not in self.selected and r.get("abstract")][:n_extra]
        return chosen, others

    def extraction(self, rid):
        p = self.data / "extractions" / f"{rid}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def validation(self, rid):
        p = self.data / "validations" / f"{rid}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def fulltext(self, rid):
        p = self.data / "fulltext" / f"{rid}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def remap(obj, old, new):
    return json.loads(re.sub(rf'"{old}(?=[":])', f'"{new}', json.dumps(obj, ensure_ascii=False)))


def head(agent, status="COMPLETE"):
    return {"agent_id": agent, "prompt_version": "rehearsal", "status": status, "warnings": [], "limitations": []}


class Models:
    """Scripted replies for A02-A06, replaying the October outputs under this run's record IDs."""

    def __init__(self, run, octo: October, qualified: set[str]):
        self.run, self.oct, self.qualified = run, octo, qualified
        self.octkey = octo.by_key()

    def old_id(self, rec):
        r = self.octkey.get(self.oct.key(rec))
        return r["record_id"] if r else None

    def reply(self, agent, payload, step):
        mode = payload.get("mode")
        if agent == "A02-SP":
            fw = {"primary_themes": [{"theme_id": "T1", "name": "A02's own idea", "scope": "s", "includes": "i", "excludes": "e"}],
                  "count_justification": "rehearsal"}
            return {**head(agent), "spec_state": "READY_FOR_CHECKPOINT", "original_topic": payload["topic_statement"][:200],
                    "normalized_topic": "AI-enabled nanobiosensing for cancer therapy", "readiness": {},
                    "scope": {"central_question": payload.get("researcher_outline", {}).get("review_question")},
                    "perspective_options": [{"option_id": "P1", "angle": "outline as given", "risks": [], "title_candidates": []}],
                    "selection_criteria": {"include": ["reports evidence on an outline question"], "exclude": ["later chapters"]},
                    "theme_framework": fw, "keywords": ["nanobiosensing"],
                    "search_seeds": {"core_concepts": ["nanobiosensor", "machine learning"], "synonyms": {}, "adjacent_fields": [],
                                     "seed_papers": []},
                    "assumptions": [], "questions_for_researcher": [], "researcher_decision": {}}
        if agent == "A03-LM":
            sections = [s["section_id"] for s in payload["researcher_outline"]["sections"]]
            return {**head(agent), "mode": mode, "plan_version": "1", "concept_blocks": [],
                    "query_families": [{"family_id": f"F{i}", "purpose": "DISCOVERY", "sources": ["pubmed"], "max_records": 60,
                                        "section_ids": sections[i::2], "compiled": {"pubmed": f"(nanobiosens*) AND family {i}"}}
                                       for i in range(2)],
                    "citation_expansion_seed_families": ["F0"], "repairs": [], "seeds_not_recalled": []}
        if agent == "A04-CQ":
            quals = []
            for i, r in enumerate(payload["records"]):
                old = self.old_id(r)
                if old in self.qualified:
                    tier = self.oct.selected[old].get("tier") or "SUPPORTING"
                    quals.append({"record_id": r["record_id"], "disposition": "QUALIFIED", "role": "PRIMARY",
                                  "content_inspected": "ABSTRACT", "sections_inspected": ["Abstract"], "exclusion_code": None,
                                  "reason": "Reports evidence bearing on an outline question.",
                                  "primary_theme_id": f"T{sorted(self.qualified).index(old) % 8 + 1}", "subthemes": [],
                                  "emerging": False, "emerging_note": None, "proposed_tier": tier, "tier_signal": "rehearsal",
                                  "is_contrary_evidence": bool(self.oct.selected[old].get("is_contrary_evidence")),
                                  "flags": [], "related_record_ids": []})
                else:
                    quals.append({"record_id": r["record_id"], "disposition": "EXCLUDED", "role": None,
                                  "content_inspected": "ABSTRACT", "sections_inspected": ["Abstract"],
                                  "exclusion_code": "OUT_OF_SCOPE", "reason": "Does not report evidence on any outline question.",
                                  "primary_theme_id": None, "subthemes": [], "emerging": False, "emerging_note": None,
                                  "proposed_tier": None, "tier_signal": None, "is_contrary_evidence": False, "flags": [],
                                  "related_record_ids": []})
            return {**head(agent), "batch_id": payload["batch_id"], "received_record_ids": [r["record_id"] for r in payload["records"]],
                    "qualifications": quals, "human_review_queue": [], "theme_suggestions": [], "criteria_defects": []}
        if agent == "A05-KE":
            rec = payload["record"]
            old = self.old_id(rec)
            ext = copy.deepcopy(self.oct.extraction(old))
            ext = remap(ext, old, rec["record_id"])
            ext.update(record_id=rec["record_id"], content_level=payload["content_level"], prompt_version="rehearsal")
            for f in ext.get("findings", []):   # October outputs predate fields the current schema requires
                if f.get("predicate") == "OTHER_SPECIFIED" and not f.get("predicate_detail"):
                    f["predicate_detail"] = "relation stated in the span (rehearsal fill for a pre-schema October output)"
            import jsonschema
            from litreview.paths import SCHEMAS_DIR
            schema = json.loads((SCHEMAS_DIR / "A05-KE.schema.json").read_text(encoding="utf-8"))
            bad = {e.absolute_path[1] for e in jsonschema.Draft202012Validator(schema).iter_errors(ext)
                   if len(e.absolute_path) > 1 and e.absolute_path[0] == "findings"}
            if bad:   # replay only: findings that fail today's schema are left out and counted
                DROPPED[rec["record_id"]] = len(bad)
                ext["findings"] = [f for i, f in enumerate(ext["findings"]) if i not in bad]
            return ext
        if agent == "A06-SV" and mode == "PER_PAPER":
            rid = payload["extraction"]["record_id"]
            old = self.old_id(next(r for r in self.run.load("selected_corpus.json") if r["record_id"] == rid))
            val = remap(copy.deepcopy(self.oct.validation(old)), old, rid)
            wanted = (payload.get("a06_validation_batch") or {}).get("finding_ids") or [f["finding_id"] for f in payload["extraction"]["findings"]]
            present = {f["finding_id"] for f in (self.run.load(f"extractions/{rid}.json") or payload["extraction"])["findings"]}
            rows = {v["finding_id"]: v for v in val["validations"] if v["finding_id"] in present}
            keep = lambda xs: [x for x in xs if set(x.get("finding_ids", [])) <= set(rows)]   # noqa: E731
            return {**head(agent, "COMPLETE_WITH_WARNINGS"), "mode": "PER_PAPER", "record_id": rid,
                    "validations": [rows[f] for f in wanted], "defect_reports": [],
                    "source_inconsistencies": keep(val.get("source_inconsistencies", [])) if not payload.get("a06_validation_batch") else [],
                    "normalization_conflicts": []}
        if agent == "A06-SV":
            return {**head(agent), "mode": "PER_THEME", "theme": payload["theme"], "conflicts": [], "independence": [],
                    "evidence_reach": {"summary": "rehearsal"}, "cross_packet_candidates": [], "retrieval_requests": []}
        raise AssertionError(f"no scripted reply for {agent} {mode}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep", help="copy the rehearsal run here for inspection")
    args = ap.parse_args(argv)
    offline()
    os.environ["LITREVIEW_TEST_TODAY"] = time.strftime("%Y-%m-%d")
    from litreview import config, model_record
    from litreview import orchestrator as orch
    from litreview.agents import base as agent_base
    from litreview.agents.base import validate
    from litreview.tools import references, fulltext
    from litreview.tools.literature.base import Record, SearchResult
    from integrated_pipeline import Agents, SimModel
    from bridge_fixtures import fixture_plan
    from litreview import bridge, run_spec
    from litreview.synthesis_registry import fingerprint

    octo = October()
    chosen, others = octo.pool()
    qualified = {r["record_id"] for r in chosen[:11]}
    pool = chosen + others
    root = Path(tempfile.mkdtemp(prefix="rehearse-pilot7-"))
    orch.RUNS_DIR = root
    model_record.RECORD = root / "model_record.jsonl"
    orch.notify.send = lambda *a, **k: False
    references.crossref_lookup = lambda *a, **k: None
    outline = json.loads((ROOT / "docs" / "pilot7" / "outline.json").read_text(encoding="utf-8"))
    run_id = orch.new_run((ROOT / "docs" / "pilot7" / "topic.md").read_text(encoding="utf-8"), outline=outline,
                          corpus_mode="OPEN_CORPUS", profile="pilot7")
    run = orch.Run(run_id)
    run.cfg["batch"]["enabled"] = False
    models = Models(run, octo, qualified)

    # --- the literature
    fields = set(Record.__dataclass_fields__) - {"record_id", "query_family_id", "source"}
    orch.search = lambda src, q, fam, n: SearchResult(src, fam, q, len(pool), [
        Record(source=src, query_family_id=fam, **{k: r.get(k) for k in fields if r.get(k) is not None}) for r in pool])
    orch.expand = lambda *a, **k: ([], [])
    old_of = lambda rec: models.old_id(rec)   # noqa: E731

    def fetch(rec, timeout=60):
        ft = octo.fulltext(old_of(rec))
        if ft and len(ft) > 1:
            return ft, {"verified": True, "pmcid": rec.get("pmcid"), "xml_sha256": "offline-fixture", "rehearsal": True}
        raise orch.FullTextUnavailable("Full-text body missing (rehearsal: the October run had abstract only)")
    orch.verify_cached_source = lambda *a, **k: None  # replay fixture, not a retrieval identity test
    orch.fetch_verified_sections = fetch
    fulltext.find_pmcid = lambda pmid, doi, timeout=30: (None, "no PMC copy listed for this identifier (rehearsal)")

    # --- the models
    real_run_agent = orch.run_agent

    def scripted_run_agent(agent_id, payload, run_dir, step, budget, prov, model=None, schema_file=None, **kw):
        guard, key = kw.get("dispatch_guard"), kw.get("reservation_key")
        held = guard(0, "rehearsal system", [{"text": json.dumps(payload)[:4000], "cache": False}], model) if guard else key
        budget.record(agent_id, model.provider, model.model, int(len(json.dumps(payload)) / 3), 1500, step=step,
                      **({"reservation_key": held} if held else {}))
        if held and held != key:
            budget.release(held)
        out = models.reply(agent_id, payload, step)
        validate(agent_id, out, schema_file)
        out_dir = Path(run_dir) / "outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{step}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        prov.agent_call(agent_id, step, model.model, "rehearsal", f"outputs/{step}.json", out.get("status"))
        return out
    orch.run_agent = scripted_run_agent

    captured = {}
    job_class = run._synthesis_job_class()

    class Capture(job_class):
        def __init__(self, directory, registry, *a, **k):
            captured["model"] = SimModel(registry)
            super().__init__(directory, registry, *a, **k)
    run._synthesis_job_class = lambda: Capture
    writers = Agents(run)
    section_of = {t["theme_id"]: t["outline_section_id"] for t in run_spec.framework_from_outline(outline)["primary_themes"]}
    order = [s["section_id"] for s in outline["sections"]]
    budgets = {s["section_id"]: s["word_budget"] for s in outline["sections"]}

    def plan_on_outline(payload):
        pkg, findings, corpus = run._bridge_inputs()
        table = bridge.comparative_table(pkg, findings, corpus, int(run._bridge_cfg().get("table_max_rows", 25)))
        plan, ledger = fixture_plan(pkg, corpus, table)
        first, *rest = plan["sections"]
        themed = [x for x in rest if x["theme_ids"]]
        unthemed = [x for x in rest if not x["theme_ids"]]      # interpretation and conclusion sections
        rename = {first["section_id"]: "S1", **{x["section_id"]: section_of[x["theme_ids"][0]] for x in themed},
                  **{x["section_id"]: "S2" for x in unthemed}}
        merged = {**unthemed[0], "ordered_items": [i for x in unthemed for i in x["ordered_items"]]} if unthemed else None
        plan["sections"] = [first, *themed] + ([merged] if merged else [])
        for x in plan["sections"]:
            x["section_id"] = rename[x["section_id"]]
            x["level"] = 1 if "." not in x["section_id"] else 2
            x["word_budget"] = budgets[x["section_id"]] if "." in x["section_id"] else 60
        plan["sections"].sort(key=lambda x: order.index(x["section_id"]))
        for e in ledger:
            if e.get("section_id"):
                e["section_id"] = rename.get(e["section_id"], e["section_id"])
        if plan.get("writing_order"):
            plan["writing_order"] = list(dict.fromkeys(rename.get(x, x) for x in plan["writing_order"]))
        return {**plan, "allocation_ledger": ledger}

    real_agent = orch.Run.agent

    def logged(agent_id, step, kw, out):
        """A scripted A07-A12 reply is logged like a provider call: cost entry (settling its reservation), provenance."""
        m = run.route(agent_id, kw.get("exclude_providers") or frozenset())
        run.budget.record(agent_id, m.provider, m.model, 20000, 2000, step=step,
                          **({"reservation_key": kw["reservation_key"]} if kw.get("reservation_key") else {}))
        (run.dir / "outputs").mkdir(exist_ok=True)
        (run.dir / "outputs" / f"{step}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        run.prov.agent_call(agent_id, step, m.model, "rehearsal", f"outputs/{step}.json", out.get("status", "UNKNOWN"))
        return out

    def dispatch(agent_id, payload, step, **kw):
        if agent_id == "A07-SYN":
            out = captured["model"](payload["mode"], payload, step.split("_", 2)[2])
            validate(agent_id, out, kw.get("schema_file"))
            return logged(agent_id, step, kw, copy.deepcopy(out))
        if agent_id == "A08-OL":
            out = plan_on_outline(payload)
            validate(agent_id, out, kw.get("schema_file"))
            writers.calls.append((agent_id, step))
            return logged(agent_id, step, kw, out)
        if agent_id in ("A09-WRI", "A10-RV", "A11-RC", "A12-EDI"):
            return logged(agent_id, step, kw, writers(agent_id, payload, step, **kw))
        return real_agent(run, agent_id, payload, step, **kw)
    run.agent = dispatch

    # --- the loop, approving checkpoints as they come
    approvals, statuses = [], []
    for _ in range(40):
        status = run.run()
        statuses.append(status)
        if status == "COMPLETE":
            break
        m = re.search(r"waiting for (CP\w+)", status) or re.search(r"(CP_[A-Z]+|CP\d)", status)
        if not m:
            print("STOPPED:", status)
            break
        cp = m.group(1)
        d = orch.checkpoints.cp_dir(run.dir)
        decision = json.loads((d / f"{cp}_decision.json").read_text(encoding="utf-8")) if (d / f"{cp}_decision.json").exists() else {}
        decision["notes"] = CHECKPOINT_NOTES
        if cp == "CP1":
            decision.update(selected_option_id="P1", approve_selection_criteria=True, confirm_corpus_policy=True)
        elif cp == "CP2":
            state = json.loads((d / "CP2_review_state.json").read_text(encoding="utf-8")) if (d / "CP2_review_state.json").exists() else {}
            decision.update(review_fingerprint=state.get("fingerprint"), review_issues_acknowledged=True)
        elif cp == "CP_SYN":
            decision.update(approve_alignment=True, keep_approved_framework=True, proposal_review_notes=CHECKPOINT_NOTES)
        elif cp == "CP3":
            pkg = run.load("synthesis_package.json")
            decision.update(selected_thesis=pkg["thesis_options"][0]["option_id"])
        elif cp == "CP_LEDGER":
            decision.update(approve_ledger=True)
        elif cp in ("CP_EARLY", "CP_SPEND", "CP_AGENT_REVIEW"):
            decision.update(approve_continue=True)
        elif cp == "CP_CONTEXT":
            decision.update(approve_request=True)
        else:
            print("no rehearsal approval for", cp)
            break
        (d / f"{cp}_decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
        orch.checkpoints.approve(run.dir, cp, run.prov)
        approvals.append(cp)

    final = run.dir / "final"
    manifest = run.load("corpus_manifest.json") or {}
    retrieval = run.load("retrieval_log.json", {}) or {}
    checks = {
        "reached_export": (final / "manuscript.md").exists(),
        "outline_framework": [t.get("outline_section_id") for t in (run.load("theme_framework.json") or {}).get("primary_themes", [])]
                             == ["S1.1", "S1.2", "S1.3", "S1.4", "S2.1", "S2.2", "S2.3", "S2.4"],
        "seven_papers_frozen": len(manifest.get("papers", [])) == 7,
        "every_paper_retrieval_logged": sorted(retrieval) == sorted(p["record_id"] for p in manifest.get("papers", [])),
        "early_check_ran": "CP_EARLY" in approvals,
        "plan_uses_outline": not [s for s in (run.load("manuscript_plan.json") or {}).get("sections", []) if s["section_id"] not in order],
        "chapter_lengths_reported": (final / "chapter_lengths.json").exists(),
        "a10_complete": (run.load("rv_final.json") or {}).get("release_disposition") in ("APPROVED", "APPROVED_WITH_MINOR_FINDINGS"),
    }
    import subprocess
    subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "pilot_report.py"), str(run.dir)], check=False,
                   env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    checks["pilot_report_written"] = (final / "PILOT_REPORT.md").exists()
    result = {"run_dir": str(run.dir), "checkpoints_approved": approvals, "final_status": statuses[-1] if statuses else None,
              "papers": [(p["paper_id"], p["record_id"], (retrieval.get(p["record_id"]) or {}).get("level_read"))
                         for p in manifest.get("papers", [])],
              "calls_by_agent": {a: sum(1 for e in run.budget.entries() if e["agent"] == a) for a in sorted({e["agent"] for e in run.budget.entries()})},
              "replay_findings_dropped_for_schema": DROPPED,
              "checks": checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2))
    if args.keep:
        shutil.copytree(run.dir, Path(args.keep) / run_id, dirs_exist_ok=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
