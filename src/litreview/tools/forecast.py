"""Calibrated planning forecast: what a run is expected to cost, with an explicit uncertainty margin, by scenario.

Planning only. It never authorizes a call: every call is still admitted at its own strict bound and reserved
before dispatch, and run.spend_cap_usd stays absolute. The scenario assumptions are in pipeline.yaml -> forecast;
everything below that is not an assumption is measured, with its source:

  A05/A06   per-paper cost by content level (mean, p90), per-theme cost, batch factor (0.5: the reference run's
            own A05/A06 calls repriced at batch rates, token class by token class) and the share of papers the
            instability test repeats (0.643): records/cost_rates.json, from run 20261025-100039.
  A07       provider-counted input tokens (Anthropic's free counter) of the production bounded-synthesis requests
            on 40-, 80- and 120-paper workloads (642, 1,353, 1,996 findings): docs/a07_efficiency/measurements.json.
            Fitted below and rounded up; at 1,996 findings the fit gives 4.51M input tokens against 4.30M measured.
  A10       production request byte bounds for a 5,000-word manuscript at 1,996 findings (42 LOCAL packets,
            7,914,333 bytes; 23 GLOBAL pages, 5,050,855 bytes): docs/integrated_validation/a10/measurements.json.
  A08-A12   the bridge's request builders (downstream_projection.py) and free counts in docs/bridge_validation.

Not measured anywhere (stated in the scenarios): output used as a share of each cap, retrieval and redraft
frequency, critique outcomes, failed-call rates, and GPT/Kimi bytes per token.
"""
from __future__ import annotations

import math

# --- A07: provider input tokens per finding count F (fits on the measured workloads, rounded up) -------------
A07_INPUT = {"PLAN": lambda F: 230 * F,                 # measured 146,814 / 287,743 / 416,714
             "GROUP": lambda F: 1400 * F + 140_000,     # measured 1,026,646 / 1,940,921 / 2,905,938 (all GROUP turns)
             "RECONCILE": lambda F: 0.25 * F * F,        # measured 129,014 / 410,093 / 889,123 (all pages)
             "FINAL": lambda F: 63 * F}                  # measured 40,226 / 64,963 / 92,275
A07_GROUP_CALLS = lambda F: math.ceil(0.048 * F + 16)    # measured 46 / 77 / 111
A07_PROPOSITIONS_PER_FINDING = 0.163                     # 324 / 1,996 in the integrated audit
A07_RETRIEVAL_TOKENS = 12 * 1300                         # retrieval_limit findings at the measured tokens per finding
A07_SYSTEM_TOKENS = 5_800                                # system prompt: 11,910 bytes at the smallest ratio measured (2.06)

# --- A10: bytes per request at 1,996 findings, scaled by the global index (1.449 entries per finding) --------
A10_LOCAL_CALLS = 42
A10_LOCAL_BYTES = 7_914_333 / 42
A10_PAGE_BYTES = 5_050_855 / 23
A10_INDEX_PER_FINDING = 2892 / 1996
A10_RETRIEVAL_SHARE = 0.15                               # assumption: a retrieval round adds 15% to its request


def a07(F: int, cfg: dict, budget, route, s: dict | None) -> tuple[float, int]:
    """(usd, requests) for A07 at F findings. s None: every request the configured retrieval rounds allow, full
    output caps, the system prompt written to the 1-hour cache on every call."""
    syn = cfg["synthesis"]
    m = route("A07-SYN")
    rates = budget._rates(m.model, 0)
    caps = syn["output_limits"]
    rounds = int(syn.get("max_retrieval_rounds", 2))
    groups = A07_GROUP_CALLS(F)
    pages = math.ceil(A07_PROPOSITIONS_PER_FINDING * F / int(syn.get("reconcile_page_size", 32)))
    out_share = 1.0 if s is None else float(s["output"])
    r = 1.0 if s is None else float(s["a07_retrieval"])
    extra_rounds = rounds if s is None or r >= 1.0 else 1
    usd, calls = 0.0, 0
    for mode, n in (("PLAN", 1), ("GROUP", groups), ("RECONCILE", pages), ("FINAL", 1)):
        total = A07_INPUT[mode](F)
        per = total / n
        weight = 1.0
        if mode in ("GROUP", "RECONCILE"):
            weight += r * extra_rounds
            total += r * sum(n * (per + k * A07_RETRIEVAL_TOKENS) for k in range(1, extra_rounds + 1))
            calls += n * (1 + (rounds if s is None else extra_rounds if r else 0))
        else:
            calls += n
        usd += total * rates["input"] / 1e6 + n * weight * caps[mode] * out_share * rates["output"] / 1e6
        if s is None:   # the system prompt as a 1-hour cache write on every request, not plain input
            usd += n * weight * A07_SYSTEM_TOKENS * (rates["cache_write_1h"] - rates["input"]) / 1e6
    return usd, calls


def a10(F: int, cfg: dict, budget, route, s: dict, bytes_per_token: float | None = None) -> tuple[float, int]:
    """(usd, requests) for A10 over the executions in s["a10_local_rerun"] (share of LOCAL packets rerun per
    verification; every execution reruns every GLOBAL page)."""
    vc = cfg["scientific_verification"]
    m = route("A10-RV")
    pages = math.ceil(A10_INDEX_PER_FINDING * F / int(vc["max_global_entries_per_page"]))
    bpt = bytes_per_token or float(s["bytes_per_token"])
    r = float(s["a10_retrieval"])
    rounds = int(vc.get("max_retrieval_rounds", 2))
    extra = rounds if r >= 1.0 else 1
    usd, calls = 0.0, 0
    for share in s["a10_local_rerun"]:
        for n, size, cap in ((A10_LOCAL_CALLS * share, A10_LOCAL_BYTES, vc["output_limits"]["LOCAL"]),
                             (pages, A10_PAGE_BYTES, vc["output_limits"]["GLOBAL"])):
            mult = 1 + r * sum(1 + k * A10_RETRIEVAL_SHARE for k in range(1, extra + 1))
            rates = budget._rates(m.model, int(size / bpt))
            usd += n * mult * (size / bpt * rates["input"] + cap * float(s["output"]) * rates["output"]) / 1e6
            calls += math.ceil(n) * (1 + (extra if r else 0))
    return usd, calls


def calibrated_line(stage: str, F: int, cfg: dict, budget, route, done_share: float = 0.0) -> dict:
    """The runtime projection line for A07 or A10: calibrated baseline plus the uncertainty margin as `usd`;
    every scenario; the strict adverse figure; calls = the most the configured loops allow."""
    fc = cfg.get("forecast") or {}
    scen = fc.get("scenarios") or {}
    margin = float(fc.get("uncertainty_margin", 0.30))
    fn = a07 if stage == "A07-SYN" else a10
    figures = {name: fn(F, cfg, budget, route, s)[0] for name, s in scen.items()}
    if stage == "A07-SYN":
        adverse, calls = a07(F, cfg, budget, route, None)
    else:
        adverse, calls = a10(F, cfg, budget, route, scen["adverse"], bytes_per_token=1.8)
    left = 1.0 - done_share
    baseline = figures.get("baseline", adverse) * left
    source = ("provider-counted input of the production bounded-synthesis requests (docs/a07_efficiency)"
              if stage == "A07-SYN" else "production request bounds for a 5,000-word manuscript (docs/integrated_validation/a10)")
    return {"stage": stage, "basis": "CALIBRATED_FORECAST", "calls": max(0, round(calls * left)),
            "usd": round(baseline * (1 + margin), 4), "baseline_usd": round(baseline, 4), "uncertainty_margin": margin,
            "adverse_usd": round(adverse * left, 4), "scenarios": {k: round(v * left, 4) for k, v in figures.items()},
            "detail": f"{F:,} findings; calibrated from {source}; usd = baseline x {1 + margin:.2f}; "
                      "scenario assumptions in pipeline.yaml -> forecast; every call admitted and reserved at its own bound"}


def full_run(n_papers: int, full_text_share: float, cfg: dict, budget, route, rates: dict,
             downstream_inputs: dict | None = None) -> dict:
    """Every stage of a run of n_papers, per scenario, in USD (planning; measured inputs as documented above)."""
    from .downstream_projection import lines as bridge_lines
    from .downstream_projection import requests as bridge_requests, _price, _weight
    fc = cfg["forecast"]
    pp = rates["per_paper"]
    n_ft = round(n_papers * full_text_share)
    n_ab = n_papers - n_ft
    F = round(n_ft * pp["FULL_TEXT"]["findings_mean"] + n_ab * pp["ABSTRACT"]["findings_mean"])
    batch_f = max((rates.get("batch_factor") or {"x": 1.0}).values())
    out = {}
    req = bridge_requests(route, cfg, F, downstream_inputs)
    for name, s in fc["scenarios"].items():
        stat = s["paper"]
        papers_usd = 0.0
        for level, n in (("FULL_TEXT", n_ft), ("ABSTRACT", n_ab)):
            unit = pp[level][stat]
            papers_usd += (unit + (n - 1) * unit * batch_f) if (s["batch"] and n) else n * unit
        share = rates.get("repeat_share", 1.0) if s["repeat"] == "measured" else float(s["repeat"])
        repeats = sum(round(n * share) * pp[lv]["a06_p90_usd"] for lv, n in (("FULL_TEXT", n_ft), ("ABSTRACT", n_ab)))
        repeats *= batch_f if s["batch"] else 1.0
        themes = math.ceil(n_papers * rates["themes_per_paper"]) * rates["per_theme"][s["theme"]]
        a07_usd = a07(F, cfg, budget, route, s)[0]
        a10_usd = a10(F, cfg, budget, route, s)[0]
        bridge = {a: sum(_weight(t, s) * _price(a, b, k, budget, route, cfg.get("admission") or {},
                                               cfg.get("bridge") or {}, s)[0] for b, k, t in req[a][0])
                  for a in ("A08-OL", "A09-WRI", "A11-RC", "A12-EDI")}
        models = a07_usd + a10_usd + sum(bridge.values())
        stages = {"A02-A04 (pre-CP2)": float(s["pre_cp2"]), "A05+A06 per paper": papers_usd,
                  "A06 instability repeats": repeats, "A06 per theme": themes, "A07 synthesis": a07_usd,
                  "A08 outline": bridge["A08-OL"], "A09 writing": bridge["A09-WRI"], "A10 verification": a10_usd,
                  "A11 critique": bridge["A11-RC"], "A12 editing": bridge["A12-EDI"],
                  "failed and redone calls (A07-A12)": models * float(s["retries"])}
        out[name] = {k: round(v, 2) for k, v in stages.items()} | {"total": round(sum(stages.values()), 2)}
    base = out["baseline"]["total"]
    margin = float(fc["uncertainty_margin"])
    return {"papers": n_papers, "full_text": n_ft, "abstract": n_ab, "findings": F, "scenarios": out,
            "baseline_with_margin": round(base * (1 + margin), 2), "uncertainty_margin": margin,
            "bridge_basis": req["basis"]}
