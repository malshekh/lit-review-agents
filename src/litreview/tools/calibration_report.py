"""What a finished (or stopped) run measured, for calibration: report only. Reads the run's cost ledger, provenance
and data files; writes nothing in the run and changes no rate, assumption or procedure.

Per the researcher's decision of 2026-10-30, the pilot (which is also the scientific evaluation) reports:
  * the A06 instability repeat: its cost and calls, and what it caught (agreement counts, quarantined findings by
    cause); disagreement is measured only, the procedure is not changed on this evidence;
  * the A06 theme pass: calls, cost, and what it caught (conflicts and independence notes per theme);
  * A09: retrieval rounds and redrafts per section, and the A10 findings that triggered each redraft;
  * A10: LOCAL and GLOBAL calls and cost per pass, and the issues each kind raised;
and the per-call rates the pilot calibrates: cost per call by agent and model, output tokens per A07 proposition,
cache behaviour, and bytes per token from the context-utilisation records (GPT and Kimi tokenization).
Reasoning tokens: providers bill them as output and the ledger has no separate field, so they are reported as
included in output (not separately measured).
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean, median


def _load(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def _sum(entries: list[dict]) -> dict:
    return {"calls": len(entries), "usd": round(sum(e.get("cost_usd") or 0 for e in entries), 4),
            "input_tokens": sum(e.get("input_tokens") or 0 for e in entries),
            "output_tokens": sum(e.get("output_tokens") or 0 for e in entries)}


def report(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    data = run_dir / "data"
    costs = _lines(run_dir / "costs.jsonl")
    events = _lines(run_dir / "provenance.jsonl")
    tool = lambda name: [e for e in events if e.get("type") == "tool_run" and e.get("tool") == name]

    # ---- A06 instability repeat
    repeat = [e for e in costs if re.fullmatch(r"A06-SV_R\d+_repeat", e.get("step", ""))]
    inst = _load(data / "instability_test.json", {}) or {}
    review = [i for i in _load(data / "validation_review.json", []) or [] if i.get("kind") == "REPEAT"]
    a06_repeat = {**_sum(repeat), "papers_repeated": len(inst.get("papers") or {}), "agreement": inst.get("agreement"),
                  "skipped": inst.get("skipped"), "invalid": inst.get("invalid"),
                  "caught": {"held_for_adjudication": len(review),
                             "quarantined": sum(1 for i in review if i.get("action") == "QUARANTINED"),
                             "by_cause": inst.get("by_cause")},
                  "note": "disagreement measured only; no threshold and no change of procedure on this evidence"}

    # ---- A06 theme pass
    themes = [e for e in costs if e.get("step", "").startswith("A06-SV_theme_")]
    records = _load(data / "theme_records.json", {}) or {}
    a06_theme = {**_sum(themes), "themes": len(records),
                 "revalidation_calls": sum(1 for e in themes if "_reval" in e["step"]),
                 "caught": {th: {"conflicts": len(r.get("conflicts") or []),
                                 "independence_notes": len(r.get("independence") or []) if isinstance(r.get("independence"), list)
                                 else int(bool(r.get("independence")))} for th, r in records.items()}}

    # ---- A09 retrieval and redrafts
    a09 = [e for e in costs if e.get("agent") == "A09-WRI"]
    sections = defaultdict(lambda: {"calls": 0, "retrieval_rounds": 0, "drafts": set()})
    for e in a09:
        m = re.fullmatch(r"A09-WRI_(draft\d+)_(.+)_r(\d+)", e["step"])
        if m:
            s = sections[m.group(2)]
            s["calls"] += 1
            s["retrieval_rounds"] = max(s["retrieval_rounds"], int(m.group(3)))
            s["drafts"].add(m.group(1))
    gates = tool("section_gate")
    redraft_causes = []
    for p in sorted(data.glob("verification_jobs/*/report.json")):
        rv = _load(p, {})
        if rv.get("pass") == "DRAFT":
            redraft_causes += [{"code": f.get("code"), "severity": f.get("severity")} for f in rv.get("findings") or []
                               if f.get("severity") == "BLOCKING" and str(f.get("responsible_stage") or "").startswith("A09")]
    n_sec = max(1, len(sections))
    a09_report = {**_sum(a09), "sections": len(sections),
                  "sections_with_retrieval": sum(1 for s in sections.values() if s["retrieval_rounds"]),
                  "retrieval_frequency": round(sum(1 for s in sections.values() if s["retrieval_rounds"]) / n_sec, 3),
                  "sections_redrafted": sum(1 for s in sections.values() if len(s["drafts"]) > 1),
                  "redraft_frequency": round(sum(1 for s in sections.values() if len(s["drafts"]) > 1) / n_sec, 3),
                  "retrieval_events": len(tool("writer_retrieval")),
                  "section_gate_failures": sum(1 for g in gates if (g.get("summary") or {}).get("problems")),
                  "caught": {"blocking_a10_findings_on_drafts": redraft_causes}}

    # ---- A10 LOCAL and GLOBAL
    a10 = [e for e in costs if e.get("agent") == "A10-RV"]
    local = [e for e in a10 if "_LOCAL_" in e["step"]]
    glob = [e for e in a10 if "_GLOBAL_" in e["step"]]
    issues = {"LOCAL": defaultdict(int), "GLOBAL": defaultdict(int)}
    for job in sorted(data.glob("verification_jobs/*")):
        for p in job.glob("*.json"):
            mode = "GLOBAL" if p.name.startswith("GLOBAL_") else "LOCAL" if p.name.startswith("LOCAL_") else None
            if mode:
                for i in ((_load(p, {}) or {}).get("output") or {}).get("issues") or []:
                    issues[mode][i.get("code")] += 1
    a10_report = {"local": _sum(local), "global": _sum(glob), "total": _sum(a10),
                  "caught": {"LOCAL": dict(issues["LOCAL"]), "GLOBAL": dict(issues["GLOBAL"])},
                  "contrary_release": _load(data / "bridge" / "contrary_release.json", {}) .get("counts")}

    # ---- per-call rates
    by_model = defaultdict(list)
    for e in costs:
        by_model[(e.get("agent"), e.get("model"))].append(e)
    per_call = {f"{a} on {m}": {"calls": len(es), "usd_mean": round(mean(e.get("cost_usd") or 0 for e in es), 4),
                                "usd_median": round(median(e.get("cost_usd") or 0 for e in es), 4),
                                "output_tokens_mean": round(mean(e.get("output_tokens") or 0 for e in es)),
                                "cache": {"hit": sum(1 for e in es if (e.get("cache") or {}).get("hit")),
                                          "wrote": sum(1 for e in es if (e.get("cache") or {}).get("wrote")),
                                          "cached_input_tokens": sum(e.get("cached_input_tokens") or 0 for e in es)}}
                for (a, m), es in sorted(by_model.items(), key=lambda kv: str(kv[0]))}
    pkg = _load(data / "synthesis_approved.json") or _load(data / "synthesis_package.json") or {}
    a07 = [e for e in costs if e.get("agent") == "A07-SYN"]
    props = len(pkg.get("propositions") or [])
    tokenization = defaultdict(list)
    for e in tool("context_utilisation_actual"):
        s = e.get("summary") or {}
        if s.get("byte_bound_over_actual"):
            tokenization[s.get("model")].append(s["byte_bound_over_actual"])
    return {"run": run_dir.name, "label": "REPORT ONLY: measurements for calibration; nothing here changes a rate, "
                                          "assumption or procedure",
            "a06_instability_repeat": a06_repeat, "a06_theme_pass": a06_theme, "a09_retrieval_and_redrafts": a09_report,
            "a10_local_and_global": a10_report,
            "per_call": per_call,
            "a07_output_tokens_per_proposition": round(sum(e.get("output_tokens") or 0 for e in a07) / props, 1) if props else None,
            "bytes_per_token_by_model": {m: {"n": len(v), "median": round(median(v), 3), "min": min(v), "max": max(v)}
                                         for m, v in tokenization.items()},
            "reasoning_tokens": "included in output tokens (billed as output; not separately recorded in the ledger)",
            "spend": {"total_usd": round(sum(e.get("cost_usd") or 0 for e in costs), 4), "calls": len(costs)}}
