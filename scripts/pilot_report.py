"""The pilot report: everything the run produced and what it cost, assembled from the run's own records.

    python scripts/pilot_report.py RUN_DIR            writes RUN_DIR/final/PILOT_REPORT.md and pilot_report.json

Offline, read only (it reads the run folder and writes the two report files). It works on a finished run and on
one that stopped part-way: a section whose source file does not exist yet says so.

Sections: the two chapters and their references; chapter lengths against the outline; retrieval and screening
(search families and hits, deduplication, dispositions and exclusion reasons, the proposed and approved
selection, the frozen corpus manifest, what was actually retrieved per paper, retrieval failures kept apart from
scientific exclusions); extraction and validation (findings and dispositions per paper, the instability retest);
unresolved issues (submission blockers, evidence outside the outline, wording flags, held findings, verification
findings); expenditure by stage, agent and attempt; failures, retries and repairs; every human intervention.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
STAGE_OF = {"A02-SP": "A02-A04 scope, search, screening", "A03-LM": "A02-A04 scope, search, screening",
            "A04-CQ": "A02-A04 scope, search, screening", "A05-KE": "A05-A06 extraction and validation",
            "A06-SV": "A05-A06 extraction and validation", "A07-SYN": "A07 synthesis", "A08-OL": "A08-A09 outline and writing",
            "A09-WRI": "A08-A09 outline and writing", "A10-RV": "A10 verification", "A11-RC": "A11-A12 critique and editing",
            "A12-EDI": "A11-A12 critique and editing"}


def _j(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def collect(run: Path) -> dict:
    data, final = run / "data", run / "final"
    costs, prov = _lines(run / "costs.jsonl"), _lines(run / "provenance.jsonl")
    ledger = _lines(data / "job_ledger.jsonl")
    state = _j(run / "state.json", {})

    # --- spending
    by_stage, by_agent = defaultdict(float), defaultdict(lambda: {"calls": 0, "usd": 0.0, "input": 0, "output": 0})
    for e in costs:
        usd = e.get("cost_usd") or 0.0
        by_stage[STAGE_OF.get(e["agent"], e["agent"])] += usd
        a = by_agent[e["agent"]]
        a["calls"] += 1
        a["usd"] += usd
        a["input"] += e.get("input_tokens", 0) + e.get("cached_input_tokens", 0) + e.get("cache_write_tokens", 0) \
            + e.get("cache_write_1h_tokens", 0)
        a["output"] += e.get("output_tokens", 0)
    attempts = Counter(e["step"] for e in costs)
    repeated = {s: n for s, n in attempts.items() if n > 1}

    # --- failures and recovery
    fail_states = ("REFUSED", "TRUNCATED", "INVALID", "REPAIR_REJECTED", "API_ERROR", "RESOLVED_BILLED", "RESOLVED_NOT_BILLED")
    failures = [e for e in ledger if e["state"] in fail_states]
    latest = {}
    for e in ledger:
        latest[e["step"]] = e
    in_flight = [e for e in latest.values() if e["state"] == "DISPATCHED"]
    tools = Counter(e.get("tool") for e in prov if e.get("type") == "tool_run")
    recovery = {k: tools.get(k, 0) for k in ("truncation_retry", "json_repair", "recovered_saved_response", "receipt_reuse",
                                             "run_lock_takeover")}

    # --- retrieval and screening
    records = _j(data / "records.json", []) or []
    quals = _j(data / "qualifications.json", []) or []
    dispositions = Counter(q.get("disposition") for q in quals)
    exclusion_reasons = Counter(q.get("exclusion_code") or (q.get("reason") or "")[:80] for q in quals
                                if q.get("disposition") != "QUALIFIED")
    search_log = _j(data / "search_log.json", []) or []
    dedup = next((e.get("summary") for e in prov if e.get("tool") == "search+dedup"), None)
    retrieval = _j(data / "retrieval_log.json", {}) or {}
    manifest = _j(data / "corpus_manifest.json")
    proposal = _j(data / "selection_proposal.json")

    # --- extraction and validation
    per_paper = []
    for p in (manifest or {}).get("papers", []):
        rid = p["record_id"]
        ext = _j(data / "extractions" / f"{rid}.json", {}) or {}
        val = _j(data / "validations" / f"{rid}.json", {}) or {}
        per_paper.append({"paper_id": p["paper_id"], "record_id": rid, "title": p.get("title"),
                          "read_as": (retrieval.get(rid) or {}).get("level_read") or "not yet extracted",
                          "findings": len(ext.get("findings") or []),
                          "dispositions": dict(Counter(v.get("disposition") for v in val.get("validations") or []))})
    instability = _j(data / "instability_test.json")

    # --- unresolved issues
    status = _j(final / "submission_status.json", {}) or {}
    unmapped = _j(data / "unmapped_evidence.json")
    lint = _j(final / "science_lint.json", []) or []
    held = _j(data / "held_for_correction.json", []) or []
    rv = _j(data / "rv_final.json", {}) or {}

    # --- human interventions
    human = [{"time": e["time"], "checkpoint": e.get("checkpoint"), "note": (e.get("note") or "")[:300]}
             for e in prov if e.get("type") == "human_decision"]

    return {
        "run": run.name, "state": {k: state.get(k) for k in ("stage", "status", "profile")},
        "spending": {"total_usd": round(sum(by_stage.values()), 4),
                     "by_stage_usd": {k: round(v, 4) for k, v in sorted(by_stage.items())},
                     "by_agent": {k: {**v, "usd": round(v["usd"], 4)} for k, v in sorted(by_agent.items())},
                     "steps_paid_more_than_once": repeated},
        "failures_and_recovery": {"ledger_failures": failures, "requests_in_flight_unresolved": in_flight,
                                  "recovery_events": recovery},
        "retrieval_and_screening": {"search_families": [{k: s.get(k) for k in ("family_id", "source", "query", "hit_count",
                                                                                 "returned", "error") if k in s}
                                                        for s in search_log],
                                    "records_after_deduplication": len(records), "deduplication": dedup,
                                    "screening_dispositions": dict(dispositions),
                                    "scientific_exclusions_by_reason": dict(exclusion_reasons.most_common(25)),
                                    "proposed_selection": proposal, "frozen_manifest": manifest,
                                    "retrieval_per_paper": retrieval,
                                    "retrieval_limitations": [rid for rid, r in retrieval.items()
                                                              if r.get("category") != "FULL_TEXT_RETRIEVED"]},
        "extraction_and_validation": {"per_paper": per_paper, "instability_retest": instability},
        "unresolved": {"submission_blockers": status.get("blockers", []), "outside_outline": unmapped,
                       "wording_flags": lint, "held_for_correction": held,
                       "verification_findings": [f for f in rv.get("findings", []) if f.get("severity") in ("MAJOR", "BLOCKING", "MINOR")]},
        "chapter_lengths": _j(final / "chapter_lengths.json"),
        "human_interventions": human,
        "files": {"manuscript": str(final / "manuscript.md") if (final / "manuscript.md").exists() else None},
    }


def markdown(r: dict, run: Path) -> str:
    out = [f"# Pilot report: run {r['run']}", "",
           f"State: {r['state']['stage']} ({r['state']['status']}); profile {r['state']['profile']}.", ""]
    ms = run / "final" / "manuscript.md"
    out += ["## 1. The chapters and references", "",
            ("The manuscript is in `final/manuscript.md` (and `.docx`); it is reproduced below." if ms.exists()
             else "Not produced yet: the run has not reached export."), ""]
    if ms.exists():
        out += [ms.read_text(encoding="utf-8"), ""]
    if r["chapter_lengths"]:
        out += ["## 2. Chapter lengths", "", "| Chapter | Target | Written | Within 15% |", "|---|---:|---:|---|"]
        out += [f"| {c['section_id']} {c['heading']} | {c['target']} | {c['written']} | {'yes' if c['within_tolerance'] else 'no'} |"
                for c in r["chapter_lengths"]] + [""]
    s = r["spending"]
    out += ["## 3. Expenditure", "", f"Total recorded: **${s['total_usd']:.2f}** (from `costs.jsonl`; reconcile with the "
            "provider consoles using `scripts/reconcile_billing.py`).", "", "| Stage | USD |", "|---|---:|"]
    out += [f"| {k} | {v:.2f} |" for k, v in s["by_stage_usd"].items()] + ["", "| Agent | Calls | Input tokens | Output tokens | USD |",
                                                                           "|---|---:|---:|---:|---:|"]
    out += [f"| {k} | {v['calls']} | {v['input']:,} | {v['output']:,} | {v['usd']:.2f} |" for k, v in s["by_agent"].items()]
    out += ["", f"Steps paid more than once (retries and repairs included): {len(s['steps_paid_more_than_once'])}", ""]
    f = r["failures_and_recovery"]
    out += ["## 4. Failures, retries and recovery", "",
            f"- Failure states recorded: {len(f['ledger_failures'])} "
            + str(dict(Counter(e['state'] for e in f['ledger_failures']))),
            f"- Recovery events: {f['recovery_events']}",
            f"- Requests in flight with unknown outcome: {len(f['requests_in_flight_unresolved'])}", ""]
    out += [f"  - {e['time']} {e['step']} {e['state']}: {str(e.get('error') or e.get('problems') or e.get('category') or '')[:200]}"
            for e in f["ledger_failures"][:40]] + [""]
    rs = r["retrieval_and_screening"]
    out += ["## 5. Retrieval and screening", "",
            f"- Search families run: {len(rs['search_families'])}; records after deduplication: {rs['records_after_deduplication']}",
            f"- Deduplication: {rs['deduplication']}",
            f"- Screening dispositions: {rs['screening_dispositions']}",
            "- Scientific exclusions by reason:", *[f"  - {k or 'no reason given'}: {v}" for k, v in rs["scientific_exclusions_by_reason"].items()],
            f"- Retrieval limitations (kept apart from exclusions): {rs['retrieval_limitations'] or 'none'}", ""]
    if rs["frozen_manifest"]:
        out += ["### The frozen corpus", "", "| Paper | Record | Title | Importance | Read as | Selection reason |", "|---|---|---|---|---|---|"]
        for p in rs["frozen_manifest"]["papers"]:
            got = (rs["retrieval_per_paper"].get(p["record_id"]) or {}).get("level_read") or "not yet retrieved"
            out.append(f"| {p['paper_id']} | {p['record_id']} | {(p.get('title') or '')[:70]} | {p['scientific_importance']} | "
                       f"{got} | {(p.get('selection_reason') or '')[:160]} |")
        out.append("")
    out += ["## 6. Extraction and validation", "", "| Paper | Read as | Findings | Validation dispositions |", "|---|---|---:|---|"]
    out += [f"| {p['paper_id']} | {p['read_as']} | {p['findings']} | {p['dispositions']} |" for p in r["extraction_and_validation"]["per_paper"]]
    out += ["", f"Instability retest: {json.dumps((r['extraction_and_validation']['instability_retest'] or {}).get('agreement'))}", ""]
    u = r["unresolved"]
    out += ["## 7. Unresolved issues", "", f"- Submission blockers: {len(u['submission_blockers'])}",
            *[f"  - {b[:240]}" for b in u["submission_blockers"][:40]],
            f"- Evidence outside the outline: {len((u['outside_outline'] or {}).get('items', []))}; sections without evidence: "
            f"{(u['outside_outline'] or {}).get('outline_coverage', {}).get('sections_without_evidence')}",
            f"- Wording flags: {len(u['wording_flags'])}; findings held for correction: {len(u['held_for_correction'])}; "
            f"verification findings: {len(u['verification_findings'])}", ""]
    out += ["## 8. Human interventions", "", *[f"- {h['time']} {h['checkpoint']}: {h['note']}" for h in r["human_interventions"]], ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    args = ap.parse_args(argv)
    run = Path(args.run_dir)
    if not (run / "state.json").exists():
        print(f"{run} is not a run folder")
        return 1
    r = collect(run)
    (run / "final").mkdir(exist_ok=True)
    (run / "final" / "pilot_report.json").write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
    (run / "final" / "PILOT_REPORT.md").write_text(markdown(r, run), encoding="utf-8")
    print(f"Report written: {run / 'final' / 'PILOT_REPORT.md'}  (spent ${r['spending']['total_usd']:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
