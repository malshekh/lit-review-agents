"""Cost projection at CP2: what the rest of a run will cost for a selection, before any of it is spent.

Per-paper and per-theme stages (A05 extraction, A06 per-paper and per-theme validation) use rates measured
on a reference run (`records/cost_rates.json`, written by `litreview cost-rates RUN`): the 90th percentile
of the measured cost per paper, by content level (an abstract-only paper costs a fraction of a full text).
Stages no run has measured end to end (A07 to A12) are priced at worst case: every call at its configured
max_tokens, A07 paying a full cache write on every call, input sizes from the measured tokens per finding.
Every line says which basis it uses. The projection overstates rather than understates.

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

A07_TOKENS_PER_FINDING = 821          # run 20261025-100039 audit: A07 input per validated finding
A10_TOKENS_PER_FINDING = 700          # bound records in full (514 each) for about half, index lines (53) for the rest
FIXED_INPUT = {"A07-SYN": 20000, "A08-OL": 20000, "A09-WRI": 60000, "A10-RV": 80000, "A11-RC": 60000, "A12-EDI": 60000}


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
        out["per_paper"][level] = {"papers": len(rids), "mean_usd": round(sum(cost) / max(len(cost), 1), 4),
                                   "p90_usd": round(_pct(cost, .9), 4), "max_usd": round(max(cost or [0]), 4),
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


def downstream(budget, route, cfg: dict, n_findings: int) -> list[dict]:
    """A07 to A12 at worst case, for a corpus of n_findings validated findings."""
    loops, syn = cfg["loops"], cfg["synthesis"]
    groups = max(1, math.ceil(n_findings / int(syn["max_findings_per_group"])))
    a10_passes = 2 if loops.get("verification") == "draft_and_final" else \
        1 + int(loops["max_redrafts"]) + int(loops["max_critique_cycles"]) + 2
    cycles = int(loops["max_critique_cycles"])
    corpus = FIXED_INPUT["A07-SYN"] + n_findings * A07_TOKENS_PER_FINDING
    return [
        _worst(budget, route, "A07-SYN", groups + 2, corpus, cache_write_1h=True,
               max_tokens=int(syn["max_tokens_per_turn"])),
        _worst(budget, route, "A08-OL", 1, FIXED_INPUT["A08-OL"] + n_findings * 300),
        _worst(budget, route, "A09-WRI", 1 + int(loops["max_redrafts"]), FIXED_INPUT["A09-WRI"]),
        _worst(budget, route, "A10-RV", a10_passes * 2, FIXED_INPUT["A10-RV"] + n_findings * A10_TOKENS_PER_FINDING),
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
    themes = max(1, math.ceil(len(selection) * rates["themes_per_paper"]))
    lines.append({"stage": "A06-SV per theme", "basis": "MEASURED_P90", "calls": themes,
                  "usd": round(themes * rates["per_theme"]["p90_usd"], 4),
                  "detail": f"{themes} themes ({rates['themes_per_paper']} per paper measured) x "
                            f"${rates['per_theme']['p90_usd']:.4f}"})
    lines += downstream(budget, route, cfg, n_findings)
    return _total(lines, budget, {"papers": len(selection), "by_level": by_level, "findings_assumed": n_findings})


def remaining_for_run(run, rates: dict | None = None) -> dict:
    """Projection of what a run past CP2 still has to spend, from its current stage. Stale theme records are
    priced from what those same theme calls cost when they last ran (measured), and at worst case."""
    from ..orchestrator import STAGES
    stage = run.state().get("stage")
    lines = []
    findings = run.load("validated_findings.json") or []
    if STAGES.index(stage) <= STAGES.index("validate"):
        rates = rates or load_rates()
        return for_selection(rates, run.load("selected_corpus.json") or [], run.dir, run.budget, run.route, run.cfg)
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
    if STAGES.index(stage) <= STAGES.index("synthesize"):
        lines += downstream(run.budget, run.route, run.cfg, len(findings))
    return _total(lines, run.budget, {"stage": stage, "findings": len(findings)})


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
