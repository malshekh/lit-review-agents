"""Cost projection at CP2: what the rest of a run will cost for a selection, before any of it is spent.

Per-paper and per-theme stages (A05 extraction, A06 per-paper and per-theme validation) use rates measured
on a reference run (`records/cost_rates.json`, written by `litreview cost-rates RUN`): the 90th percentile
of the measured cost per paper, by content level (an abstract-only paper costs a fraction of a full text).
A07 uses an explicitly estimated bounded-call envelope, including retrieval. A08 to A12 retain their
existing maximum-output projections. A07 reserves each actual serialized request before dispatch;
the planning envelope is not a strict bound on arbitrarily large scientific source strings.

The pipeline refuses to pass CP2 when the projection exceeds the spend cap, and refuses any agent call after
CP2 without a projection within the cap (orchestrator.Run.agent): spend is decided where changing the
selection is still cheap.
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

# Legacy full-corpus benchmark, retained for historical comparisons only (not current projections).
# A07: input of the largest call of the old job per
# validated finding. Measured 2026-10-29 with the real payload builder and the token-counting endpoint over
# workloads of 28 to 120 papers built from run 20261025-100039's records: at most 1,297 tokens per finding
# above the fixed part (system prompt ~12.0k + review spec ~10.8k). Was 821, measured before the handoff
# contract added entities, eligibility and plain-language limits to every finding: it understated by ~35%.
A07_TOKENS_PER_FINDING = 1300
A10_TOKENS_PER_FINDING = 700          # bound records in full (514 each) for about half, index lines (53) for the rest
FIXED_INPUT = {"A07-SYN": 25000, "A08-OL": 20000, "A09-WRI": 60000, "A10-RV": 80000, "A11-RC": 60000, "A12-EDI": 60000}


def _pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def measured_rates(run_dir: Path) -> dict:
    """Per-paper A05 and A06 cost by content level, per-theme A06 cost, findings and themes per paper, from a
    finished validate stage. Revalidations and probes are not part of a normal run and are left out."""
    run_dir = Path(run_dir)
    entries = [json.loads(x) for x in (run_dir / "costs.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    levels, findings = {}, {}
    for p in (run_dir / "data" / "extractions").glob("*.json"):
        ext = json.loads(p.read_text(encoding="utf-8"))
        levels[p.stem] = ext.get("content_level") or "ABSTRACT"
        findings[p.stem] = len(ext.get("findings", []))
    per = {"A05-KE": {}, "A06-SV": {}}
    themes = []
    for e in entries:
        s = e["step"]
        m = re.fullmatch(r"A05-KE_(R\d+)(_reextract)?", s)
        if m:
            per["A05-KE"][m.group(1)] = per["A05-KE"].get(m.group(1), 0) + (e["cost_usd"] or 0)
        m = re.fullmatch(r"A06-SV_(R\d+)_v\d+", s)
        if m:
            per["A06-SV"][m.group(1)] = per["A06-SV"].get(m.group(1), 0) + (e["cost_usd"] or 0)
        if s.startswith("A06-SV_theme_") and "_reval" not in s:
            themes.append(e["cost_usd"] or 0)
    out = {"reference_run": run_dir.name, "measured_at": time.strftime("%Y-%m-%d"), "per_paper": {}, "per_theme": {}}
    for level in ("ABSTRACT", "FULL_TEXT"):
        rids = [r for r, lv in levels.items() if lv == level]
        cost = [per["A05-KE"].get(r, 0) + per["A06-SV"].get(r, 0) for r in rids]
        a06 = [per["A06-SV"].get(r, 0) for r in rids]
        out["per_paper"][level] = {"papers": len(rids), "mean_usd": round(sum(cost) / max(len(cost), 1), 4),
                                   "p90_usd": round(_pct(cost, .9), 4), "max_usd": round(max(cost or [0]), 4),
                                   "a06_p90_usd": round(_pct(a06, .9), 4),
                                   "findings_mean": round(sum(findings[r] for r in rids) / max(len(rids), 1), 2),
                                   "findings_p90": round(_pct([findings[r] for r in rids], .9), 1)}
    out["per_theme"] = {"themes": len(themes), "mean_usd": round(sum(themes) / max(len(themes), 1), 4),
                        "p90_usd": round(_pct(themes, .9), 4)}
    out["themes_per_paper"] = round(len(themes) / max(len(levels), 1), 3)
    return out


def rates_path() -> Path:
    from ..paths import REPO_ROOT
    return REPO_ROOT / "records" / "cost_rates.json"


def load_rates() -> dict:
    p = rates_path()
    if not p.exists():
        raise FileNotFoundError("no measured cost rates: run `litreview cost-rates <a finished run>` first")
    return json.loads(p.read_text(encoding="utf-8"))


def content_level(rec: dict, run_dir: Path) -> str:
    """What extraction will see: a fetched full text, else a PMC ID to fetch one, else the abstract."""
    ft = Path(run_dir) / "data" / "fulltext" / f"{rec['record_id']}.json"
    if ft.exists():
        return "FULL_TEXT" if len(json.loads(ft.read_text(encoding="utf-8"))) > 1 else "ABSTRACT"
    return "FULL_TEXT" if rec.get("pmcid") else "ABSTRACT"


def _worst(budget, route, agent: str, calls: int, input_tokens: int, cache_write_1h: bool = False,
           max_tokens: int | None = None) -> dict:
    import dataclasses
    m = route(agent)
    if max_tokens:                     # the A07 job sets its own output cap per call
        m = dataclasses.replace(m, max_tokens=max_tokens)
    if cache_write_1h:
        per_call = budget.cost(m.model, 0, m.max_tokens, 0, 0, input_tokens) or 0.0
    else:
        per_call = budget.cost(m.model, input_tokens, m.max_tokens) or 0.0
    return {"stage": agent, "basis": "WORST_CASE", "usd": round(per_call * calls, 4), "calls": calls,
            "detail": f"{calls} calls x ({input_tokens:,} input tokens{' as cache writes' if cache_write_1h else ''} "
                      f"+ {m.max_tokens:,} output at max_tokens) on {m.model}"}


def downstream(budget, route, cfg: dict, n_findings: int, a07_done: int = 0) -> list[dict]:
    """A07 to A12 at worst case, for a corpus of n_findings validated findings. Every A07 turn is one
    attempt: a truncated turn stops the job and supersedes the projection (orchestrator), so a retry is
    re-projected from actual spend rather than assumed. a07_done: turns already committed."""
    loops, syn = cfg["loops"], cfg["synthesis"]
    groups = max(1, math.ceil(n_findings / int(syn["max_findings_per_group"])))
    cycles = int(loops["max_critique_cycles"])
    from ..synthesis_registry import projected_a07
    envelope = projected_a07(syn, n_findings)
    m = route("A07-SYN")
    fraction = max(0, envelope["calls"] - a07_done) / max(1, envelope["calls"])
    a07 = {"stage": "A07-SYN", "basis": "ESTIMATED_ENVELOPE", "calls": max(0, envelope["calls"] - a07_done),
           "usd": round((budget.cost(m.model, envelope["input_tokens"], envelope["output_tokens"]) or 0) * fraction, 4),
           "detail": "bounded registry call envelope including retrieval; no cache savings; per-call admission required"}
    # A10 now has many bounded calls, not four unbounded whole-corpus calls. This is an
    # intentionally conservative planning scenario, NOT a hard bound on a future manuscript.
    # Include optional revisions and retrieval; exact requests reserve individually at dispatch.
    vc = cfg.get('scientific_verification', {})
    candidates = min(320,max(24,n_findings))  # manuscript not yet available; pilot/full-run estimate only
    local = math.ceil(candidates / max(1, vc.get('max_occurrences_per_packet',12)//2))
    global_pages = max(1,math.ceil(n_findings*1.5/vc.get('max_global_entries_per_page',128)))
    versions = 3 + int(loops['max_redrafts']) + cycles
    local_calls = local + (versions-1)*math.ceil(local*.2)
    factor = 1+vc.get('max_retrieval_rounds',2)
    limits = vc.get('output_limits',{'LOCAL':10000,'GLOBAL':8000})
    vm = route('A10-RV')
    a10 = {'stage':'A10-RV','basis':'ESTIMATED_ENVELOPE',
           'calls':factor*(local_calls+versions*global_pages),
           'usd':round(factor*((budget.cost(vm.model,60000,limits['LOCAL']) or 0)*local_calls
                              +(budget.cost(vm.model,60000,limits['GLOBAL']) or 0)*versions*global_pages),4),
           'detail':f'{candidates} estimated candidate occurrences (24-320, corpus-based before manuscript exists); half-full local packets; 1.5 index entries/finding; 20% edited locals; all global pages rechecked; 60k input/call, full output caps and retrieval; no cache savings; actual reservation required'}
    return [a07,
        _worst(budget, route, "A08-OL", 1, FIXED_INPUT["A08-OL"] + n_findings * 300),
        _worst(budget, route, "A09-WRI", 1 + int(loops["max_redrafts"]), FIXED_INPUT["A09-WRI"]),
        a10,
        _worst(budget, route, "A11-RC", cycles, FIXED_INPUT["A11-RC"] + n_findings * 300),
        _worst(budget, route, "A12-EDI", cycles + 2, FIXED_INPUT["A12-EDI"]),
    ]


def for_selection(rates: dict, selection: list[dict], run_dir: Path, budget, route, cfg: dict) -> dict:
    """Projection for a CP2 selection: measured per-paper and per-theme rates, worst-case downstream."""
    lines, n_findings, by_level = [], 0, {"ABSTRACT": 0, "FULL_TEXT": 0}
    for rec in selection:
        by_level[content_level(rec, run_dir)] += 1
    for level, n in by_level.items():
        r = rates["per_paper"][level]
        if n:
            lines.append({"stage": f"A05-KE + A06-SV per paper ({level})", "basis": "MEASURED_P90", "calls": n,
                          "usd": round(n * r["p90_usd"], 4),
                          "detail": f"{n} papers x ${r['p90_usd']:.4f} (90th percentile of {r['papers']} papers in "
                                    f"{rates['reference_run']})"})
            n_findings += math.ceil(n * r["findings_p90"])
    if (cfg.get("validation") or {}).get("instability_test"):
        # every paper assumed to have a blocked finding, so every paper repeated
        usd = sum(n * rates["per_paper"][lv].get("a06_p90_usd", rates["per_paper"][lv]["p90_usd"])
                  for lv, n in by_level.items())
        lines.append({"stage": "A06-SV whole-paper repeat (instability test)", "basis": "MEASURED_P90",
                      "calls": len(selection), "usd": round(usd, 4),
                      "detail": "one repeat per paper (every paper assumed to have a blocked finding) at the 90th "
                                "percentile of A06 per-paper cost by level"})
    themes = max(1, math.ceil(len(selection) * rates["themes_per_paper"]))
    lines.append({"stage": "A06-SV per theme", "basis": "MEASURED_P90", "calls": themes,
                  "usd": round(themes * rates["per_theme"]["p90_usd"], 4),
                  "detail": f"{themes} themes ({rates['themes_per_paper']} per paper measured) x "
                            f"${rates['per_theme']['p90_usd']:.4f}"})
    lines += downstream(budget, route, cfg, n_findings)
    return _total(lines, budget, {"papers": len(selection), "by_level": by_level, "findings_assumed": n_findings})


def _per_paper_remaining(run, rates: dict, in_flight: frozenset) -> tuple[list[dict], int]:
    """Extraction and validation in progress: per-paper lines for the work neither done nor `in_flight` (steps
    held by unsettled batches or about to be submitted, which are counted as reservations instead), and the
    findings to expect (actual where extracted, the 90th percentile by level where not)."""
    lines, n_findings = [], 0
    usd = {"A05-KE + A06-SV per paper": [0, 0.0], "A06-SV per paper (extracted, not validated)": [0, 0.0],
           "A06-SV whole-paper repeat (instability test)": [0, 0.0]}
    repeat_on = bool((run.cfg.get("validation") or {}).get("instability_test"))
    for rec in run.load("selected_corpus.json") or []:
        rid = rec["record_id"]
        r = rates["per_paper"][content_level(rec, run.dir)]
        a06 = r.get("a06_p90_usd", r["p90_usd"])
        ext = run.load(f"extractions/{rid}.json")
        val = run.load(f"validations/{rid}.json")
        n_findings += len(ext.get("findings", [])) if ext else math.ceil(r["findings_p90"])
        if ext is None and f"A05-KE_{rid}" not in in_flight:
            usd["A05-KE + A06-SV per paper"][0] += 1
            usd["A05-KE + A06-SV per paper"][1] += r["p90_usd"]
        elif val is None and not any(s.startswith(f"A06-SV_{rid}_v") for s in in_flight):
            usd["A06-SV per paper (extracted, not validated)"][0] += 1
            usd["A06-SV per paper (extracted, not validated)"][1] += a06
        blocked = val is None or any(str(v.get("disposition") or "").startswith("BLOCKED")
                                     for v in val.get("validations", []))
        if repeat_on and blocked and not run.data(f"validation_repeats/{rid}.json").exists() \
                and f"A06-SV_{rid}_repeat" not in in_flight:
            usd["A06-SV whole-paper repeat (instability test)"][0] += 1
            usd["A06-SV whole-paper repeat (instability test)"][1] += a06
    for stage, (n, x) in usd.items():
        if n:
            lines.append({"stage": stage, "basis": "MEASURED_P90", "calls": n, "usd": round(x, 4),
                          "detail": f"{n} papers at the 90th percentile by content level ({rates['reference_run']})"})
    if not run.data("theme_records.json").exists():
        themes = max(1, math.ceil(len(run.load("selected_corpus.json") or []) * rates["themes_per_paper"]))
        lines.append({"stage": "A06-SV per theme", "basis": "MEASURED_P90", "calls": themes,
                      "usd": round(themes * rates["per_theme"]["p90_usd"], 4),
                      "detail": f"{themes} themes ({rates['themes_per_paper']} per paper measured) x "
                                f"${rates['per_theme']['p90_usd']:.4f}"})
    return lines, n_findings


def remaining_for_run(run, rates: dict | None = None, in_flight: frozenset = frozenset()) -> dict:
    """Projection of what a run still has to spend, from its current stage: the CP2 projection up to CP2; then
    only the work not yet done (per paper while extracting and validating; every downstream agent whose last
    stage is still ahead). Stale theme records are priced from what those same theme calls cost when they last
    ran (measured), and at worst case. in_flight: steps held by unsettled batches or about to be submitted."""
    from ..orchestrator import AGENT_LAST_STAGE, STAGES
    stage = run.state().get("stage")
    at = STAGES.index(stage)
    if at <= STAGES.index("cp2"):
        rates = rates or load_rates()
        return for_selection(rates, run.load("selected_corpus.json") or [], run.dir, run.budget, run.route, run.cfg)
    lines = []
    n_findings = len(run.load("validated_findings.json") or [])
    if at <= STAGES.index("validate"):
        per_paper, n_findings = _per_paper_remaining(run, rates or load_rates(), frozenset(in_flight))
        lines += per_paper
    stale = run.load("theme_records_stale.json", []) or []
    if stale:
        entries = run.budget.entries()
        slug = {th: "A06-SV_theme_" + re.sub(r"[^A-Za-z0-9]+", "_", th)[:40] for th in stale}
        last = [next((e["cost_usd"] or 0 for e in reversed(entries) if e["step"] == s), None) for s in slug.values()]
        known = [x for x in last if x is not None]
        mean = sum(known) / max(len(known), 1)
        lines.append({"stage": "A06-SV theme rebuild (revalidate --themes)", "basis": "MEASURED",
                      "calls": len(stale), "usd": round(sum(x if x is not None else mean for x in last), 4),
                      "detail": f"{len(stale)} stale themes at the cost of their last call "
                                f"({len(known)} found in the cost log)"})
        worst = _worst(run.budget, run.route, "A06-SV", len(stale), 60000)
        usd = worst.pop("usd")
        lines.append({**worst, "stage": "A06-SV theme rebuild, worst case (not added to the total)", "usd_not_added": usd})
    done = 0
    if stage == "synthesize":   # turns of the current job already committed are not paid again
        from ..synthesis_job import Ledger
        jobs = sorted(run.dir.glob("data/synthesis_job_*/ledger.jsonl"), key=lambda p: p.stat().st_mtime)
        done = len(Ledger(jobs[-1]).state()["committed"]) if jobs else 0
    # every downstream agent whose last stage is still ahead (A10 verifies through finalize)
    lines += [x for x in downstream(run.budget, run.route, run.cfg, n_findings, a07_done=done)
              if STAGES.index(AGENT_LAST_STAGE[x["stage"]]) >= at]
    return _total(lines, run.budget, {"stage": stage, "findings": n_findings})


def batch_gate(run, agent_id: str, steps: list[str], reserve_usd: float, limit_usd: float,
               in_flight: frozenset = frozenset()) -> dict:
    """The runtime gate before a batch is submitted: spent + committed (held by unsettled batches) + projected
    (the rest of the run, without the steps in this batch or in flight) + reserve (this batch's worst case) must
    not exceed limit_usd. The batch is counted once, at its worst case."""
    p = remaining_for_run(run, in_flight=frozenset(in_flight) | frozenset(steps))
    spent, committed = run.budget.spent(), run.budget.reserved()
    total = spent + committed + p["projected_remaining_usd"] + reserve_usd
    return {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "agent": agent_id, "items": len(steps),
            "spent_usd": round(spent, 4), "committed_usd": round(committed, 4),
            "projected_usd": p["projected_remaining_usd"], "reserve_usd": round(reserve_usd, 4),
            "total_usd": round(total, 2), "limit_usd": limit_usd,
            "verdict": "PASS" if total <= limit_usd else "STOP",
            "projection_lines": [{k: x.get(k) for k in ("stage", "basis", "calls", "usd")} for x in p["lines"]]}


def _total(lines: list[dict], budget, basis: dict) -> dict:
    projected = round(sum(x.get("usd", 0) for x in lines), 2)
    spent = round(budget.spent(), 2)
    return {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "lines": lines, "spent_usd": spent,
            "projected_remaining_usd": projected, "projected_total_usd": round(spent + projected, 2),
            "cap_usd": budget.cap, "verdict": "WITHIN_CAP" if spent + projected <= budget.cap else "OVER_CAP",
            **basis}


def text(p: dict) -> str:
    rows = [f"  {x['stage']:52s} {x['basis']:13s} ${x.get('usd', x.get('usd_not_added', 0)):8.2f}  {x['detail']}"
            for x in p["lines"]]
    return "\n".join(rows + [f"Spent ${p['spent_usd']:.2f} + projected ${p['projected_remaining_usd']:.2f} = "
                             f"${p['projected_total_usd']:.2f} against a cap of ${p['cap_usd']:.2f}: {p['verdict']}"])
