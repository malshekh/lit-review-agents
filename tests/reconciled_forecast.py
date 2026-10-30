"""The 120-paper baseline forecast ($212.56; with the 30% margin $276.33), decomposed stage by stage and reconciled
exactly. Offline; no API calls.

    python -B tests/reconciled_forecast.py [--root <checkout>]

--root: the checkout whose forecast is decomposed (default: this one). The $212.56 figure is commit bfd6634's; run
against a checkout of that commit to reconcile to it (later changes move the forecast, and are reported separately).

Every stage is recomputed from its parts (calls, input, output, rates, batch, repeats, retries) with the same
arithmetic as src/litreview/tools/forecast.py, and asserted equal to forecast.full_run's own figure, unrounded, to
1e-9 USD. Each cell carries a label:
  MEASURED      read from data: the reference run's cost ledger (20261025-100039), provider-counted A07 input, the
                production request builders' byte bounds, prices.yaml.
  EXTRAPOLATED  a measured quantity carried to 120 papers (per-paper means times papers, fits beyond their range).
  ASSUMED       a scenario assumption in pipeline.yaml -> forecast, or a structural assumption, with what it rests on.
Writes docs/integration_validation/reconciled_120.json.
"""
import argparse
import json
import math
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REFERENCE = HERE.parent / "lit-review-agents" / "runs" / "20261025-100039"
FULL_TEXT_SHARE = 11 / 28


def cell(value, label, note=""):
    return {"value": value, "label": label, **({"note": note} if note else {})}


def reference_per_paper() -> dict:
    """Per paper, by agent and content level, from the reference run's cost ledger (read only)."""
    entries = [json.loads(x) for x in (REFERENCE / "costs.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    level = {p.stem: json.loads(p.read_text(encoding="utf-8")).get("content_level") or "ABSTRACT"
             for p in (REFERENCE / "data" / "extractions").glob("*.json")}
    acc = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))     # agent -> level -> field
    for e in entries:
        m5 = re.fullmatch(r"A05-KE_(R\d+)(_reextract)?", e["step"])
        m6 = re.fullmatch(r"A06-SV_(R\d+)_v\d+", e["step"])
        m = m5 or m6
        if not m:
            continue
        a = acc["A05-KE" if m5 else "A06-SV"][level[m.group(1)]]
        a["calls"] += 1
        a["usd"] += e["cost_usd"] or 0
        a["input"] += e["input_tokens"] + e.get("cached_input_tokens", 0) + e.get("cache_write_tokens", 0) \
            + e.get("cache_write_1h_tokens", 0)
        a["cached"] += e.get("cached_input_tokens", 0)
        a["output"] += e["output_tokens"]
    papers = {lv: sum(1 for v in level.values() if v == lv) for lv in ("FULL_TEXT", "ABSTRACT")}
    out = {ag: {lv: {k: v / papers[lv] for k, v in d.items()} for lv, d in by.items()} for ag, by in acc.items()}
    theme = [e for e in entries if e["step"].startswith("A06-SV_theme_") and "_reval" not in e["step"]]
    pre = {a: [e for e in entries if e["agent"] == a] for a in ("A02-SP", "A03-LM", "A04-CQ")}
    return {"per_paper": out, "papers": papers,
            "theme": {"calls": len(theme), "input": sum(e["input_tokens"] for e in theme) / len(theme),
                      "output": sum(e["output_tokens"] for e in theme) / len(theme)},
            "pre": {a: {"calls": len(r), "input": sum(e["input_tokens"] + e.get("cached_input_tokens", 0) for e in r),
                        "output": sum(e["output_tokens"] for e in r), "usd": sum(e["cost_usd"] for e in r),
                        "models": sorted({e["model"] for e in r})} for a, r in pre.items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=HERE)
    root = ap.parse_args().root.resolve()
    sys.path[:0] = [str(root / "src"), str(root / "tests")]
    from litreview import bridge, config
    from litreview.budget import BudgetTracker
    from litreview.tools import forecast as fc
    from litreview.tools.downstream_projection import _price, _weight, requests as breq
    from bridge_fixtures import compact_package, fixture_plan

    cfg = config.load("pipeline")
    s = cfg["forecast"]["scenarios"]["baseline"]
    margin = float(cfg["forecast"]["uncertainty_margin"])
    b = BudgetTracker(Path(tempfile.mkdtemp()))
    route = lambda a, ex=frozenset(): config.agent_candidates(a)[0]
    rates = json.loads((root / "records" / "cost_rates.json").read_text(encoding="utf-8"))
    fx = compact_package(120)
    table = bridge.comparative_table(fx["pkg"], fx["findings"], fx["corpus"])
    plan, ledger = fixture_plan(fx["pkg"], fx["corpus"], table)
    inputs = {"pkg": fx["pkg"], "findings": fx["findings"], "corpus": fx["corpus"], "plan": plan, "ledger": ledger}
    official = fc.full_run(120, FULL_TEXT_SHARE, cfg, b, route, rates, inputs)
    F, n_ft, n_ab = official["findings"], official["full_text"], official["abstract"]
    ref = reference_per_paper()
    pp, bf = rates["per_paper"], max(rates["batch_factor"].values())
    rows, check = [], {}

    # ---------------------------------------------------------------- A02-A04 (one assumed figure)
    pre_usd = float(s["pre_cp2"])
    for a in ("A02-SP", "A03-LM", "A04-CQ"):
        r, m = ref["pre"][a], route(a)
        rows.append({"stage": a, "model": m.model,
                     "calls": cell(r["calls"], "MEASURED", "reference run (28 papers); scales with the search, not the selection"),
                     "input_tokens": cell(r["input"], "MEASURED", f"reference run on {', '.join(r['models'])}"),
                     "output_tokens": cell(r["output"], "MEASURED", "reference run"),
                     "reasoning_tokens": cell("in output", "MEASURED", "providers bill reasoning as output; the ledger has no separate field"),
                     "batch": cell("none", "ASSUMED", "interactive"), "cache": cell("none", "ASSUMED"),
                     "repeats": cell(0, "ASSUMED"), "retries_usd": cell(0.0, "ASSUMED", "inside the A02-A04 figure"),
                     "cost_usd": cell(None, "ASSUMED", "not forecast per agent: see the A02-A04 subtotal"),
                     "uncertainty": f"reference spend ${r['usd']:.4f} on other models"})
    rows.append({"stage": "A02-A04 subtotal", "cost_usd": cell(pre_usd, "ASSUMED",
                 f"pipeline.yaml forecast.baseline.pre_cp2; about twice the reference run's measured "
                 f"${sum(x['usd'] for x in ref['pre'].values()):.2f} (the low scenario) for a larger search on the current "
                 "routes (A02/A03 GPT-6.1, A04 Haiku 5.5); worst case on the current routes with the reference call "
                 "counts is $3.18 (pilot_projection.json)"),
                 "uncertainty": "search size for 120 selected papers is unknown until A03/A04 run"})
    check["A02-A04 (pre-CP2)"] = pre_usd

    # ---------------------------------------------------------------- A05 and A06 per paper (batched after one probe)
    level_n = {"FULL_TEXT": n_ft, "ABSTRACT": n_ab}
    level_cost = {lv: (pp[lv]["mean_usd"] + (n - 1) * pp[lv]["mean_usd"] * bf) if n else 0.0 for lv, n in level_n.items()}
    share05 = {lv: ref["per_paper"]["A05-KE"][lv]["usd"] / (ref["per_paper"]["A05-KE"][lv]["usd"] + ref["per_paper"]["A06-SV"][lv]["usd"])
               for lv in level_n}
    for agent in ("A05-KE", "A06-SV"):
        share = {lv: share05[lv] if agent == "A05-KE" else 1 - share05[lv] for lv in level_n}
        usd = sum(level_cost[lv] * share[lv] for lv in level_n)
        mp = ref["per_paper"][agent]
        rows.append({"stage": f"{agent} per paper", "model": route(agent).model,
                     "calls": cell(round(sum(mp[lv]["calls"] * n for lv, n in level_n.items()), 1), "EXTRAPOLATED",
                                   "reference calls per paper by level x 47 full texts and 73 abstracts"),
                     "input_tokens": cell(round(sum(mp[lv]["input"] * n for lv, n in level_n.items())), "EXTRAPOLATED",
                                          "reference mean per paper by level (cache reads and writes included)"),
                     "output_tokens": cell(round(sum(mp[lv]["output"] * n for lv, n in level_n.items())), "EXTRAPOLATED",
                                           "reference mean per paper by level"),
                     "reasoning_tokens": cell("in output", "MEASURED", "billed as output; not separately recorded"),
                     "batch": cell(f"first paper per level interactive, the rest at x{bf}", "ASSUMED",
                                   f"factor x{bf} MEASURED by repricing the reference calls at batch rates; that batches run "
                                   "at all (24-hour vendor window, throughput unmeasured) is assumed"),
                     "cache": cell("as measured interactively", "MEASURED" if agent == "A05-KE" else "ASSUMED",
                                   "reference A05 system-prompt cache reads are inside its per-paper mean; that batch and "
                                   "cache discounts stack is assumed" if agent == "A05-KE" else "no cache on A06"),
                     "repeats": cell(0, "ASSUMED", "see the instability repeat row"),
                     "retries_usd": cell(0.0, "ASSUMED", "the forecast adds no retry share to A05/A06 (the reference mean includes JSON repairs it paid for)"),
                     "cost_usd": cell(usd, "EXTRAPOLATED", f"reference mean A05+A06 per paper (FT ${pp['FULL_TEXT']['mean_usd']}, "
                                      f"abstract ${pp['ABSTRACT']['mean_usd']}), split by the measured {agent} share"),
                     "uncertainty": "28 reference papers; content mix assumed equal to the reference (11/28 full text); "
                                    "the reference calls include 19 re-extractions and second validations (repair loop on "
                                    "then, off now: loops.max_reextractions 0), so this mean overstates the current "
                                    "architecture"})
    papers_usd = sum(level_cost.values())
    check["A05+A06 per paper"] = papers_usd

    # ---------------------------------------------------------------- A06 instability repeats
    share = rates["repeat_share"]
    n_rep = {lv: round(n * share) for lv, n in level_n.items()}
    rep_usd = sum(n_rep[lv] * pp[lv]["a06_p90_usd"] for lv in level_n) * bf
    m6 = ref["per_paper"]["A06-SV"]
    rows.append({"stage": "A06-SV instability repeats", "model": route("A06-SV").model,
                 "calls": cell(round(sum(m6[lv]["calls"] * n_rep[lv] for lv in level_n), 1), "EXTRAPOLATED",
                               f"{sum(n_rep.values())} papers repeated ({n_rep['FULL_TEXT']} FT + {n_rep['ABSTRACT']} abstracts) "
                               "x reference A06 calls per paper"),
                 "input_tokens": cell(round(sum(m6[lv]["input"] * n_rep[lv] for lv in level_n)), "EXTRAPOLATED", "reference mean (the cost uses the 90th percentile)"),
                 "output_tokens": cell(round(sum(m6[lv]["output"] * n_rep[lv] for lv in level_n)), "EXTRAPOLATED", "reference mean"),
                 "reasoning_tokens": cell("in output", "MEASURED"),
                 "batch": cell(f"x{bf}", "ASSUMED", "repeats batched like the first pass"),
                 "cache": cell("none", "ASSUMED"),
                 "repeats": cell(sum(n_rep.values()), "EXTRAPOLATED", f"repeat share {share} MEASURED (papers with a blocked finding in the reference run); procedure unchanged, disagreement measured only"),
                 "retries_usd": cell(0.0, "ASSUMED"),
                 "cost_usd": cell(rep_usd, "EXTRAPOLATED", "reference 90th-percentile A06 cost per paper by level x repeated papers x batch factor"),
                 "uncertainty": "repeat share from 18 of 28 papers; a larger corpus may block a different share"})
    check["A06 instability repeats"] = rep_usd

    # ---------------------------------------------------------------- A06 per theme (as forecast: 279 calls)
    themes = math.ceil(120 * rates["themes_per_paper"])
    theme_usd = themes * rates["per_theme"]["mean_usd"]
    rows.append({"stage": "A06-SV per theme", "model": route("A06-SV").model,
                 "calls": cell(themes, "EXTRAPOLATED", f"{rates['themes_per_paper']} themes per paper x 120: the reference "
                               "run's 65 free-text themes. NOT the current architecture: one call per primary theme (5-8)"),
                 "input_tokens": cell(round(themes * ref["theme"]["input"]), "EXTRAPOLATED", "reference mean per theme call"),
                 "output_tokens": cell(round(themes * ref["theme"]["output"]), "EXTRAPOLATED", "reference mean per theme call"),
                 "reasoning_tokens": cell("in output", "MEASURED"),
                 "batch": cell("none", "ASSUMED", "theme calls are interactive"), "cache": cell("none", "ASSUMED"),
                 "repeats": cell(0, "ASSUMED"), "retries_usd": cell(0.0, "ASSUMED"),
                 "cost_usd": cell(theme_usd, "EXTRAPOLATED", f"{themes} x reference mean ${rates['per_theme']['mean_usd']} per theme"),
                 "uncertainty": "structurally wrong for the current architecture; see corrections"})
    check["A06 per theme"] = theme_usd

    # ---------------------------------------------------------------- A07 (calibrated, by mode)
    syn, m7 = cfg["synthesis"], route("A07-SYN")
    r7, caps = b._rates(m7.model, 0), syn["output_limits"]
    out_share, r = float(s["output"]), float(s["a07_retrieval"])
    groups, pages = fc.A07_GROUP_CALLS(F), math.ceil(fc.A07_PROPOSITIONS_PER_FINDING * F / int(syn.get("reconcile_page_size", 32)))
    a07 = {"calls": 0.0, "input": 0.0, "output": 0.0, "usd": 0.0, "by_mode": {}}
    for mode, n in (("PLAN", 1), ("GROUP", groups), ("RECONCILE", pages), ("FINAL", 1)):
        total = fc.A07_INPUT[mode](F)
        per, weight = total / n, 1.0
        if mode in ("GROUP", "RECONCILE"):
            weight += r
            total += r * n * (per + fc.A07_RETRIEVAL_TOKENS)
        out = n * weight * caps[mode] * out_share
        usd = (total * r7["input"] + out * r7["output"]) / 1e6
        a07["by_mode"][mode] = {"calls": n * weight, "input": total, "output": out, "usd": usd}
        for k, v in (("calls", n * weight), ("input", total), ("output", out), ("usd", usd)):
            a07[k] += v
    check["A07 synthesis"] = a07["usd"]

    # ---------------------------------------------------------------- A10 (calibrated, LOCAL and GLOBAL)
    vc, m10 = cfg["scientific_verification"], route("A10-RV")
    a10pages = math.ceil(fc.A10_INDEX_PER_FINDING * F / int(vc["max_global_entries_per_page"]))
    bpt, r10 = float(s["bytes_per_token"]), float(s["a10_retrieval"])
    a10 = {"calls": 0.0, "input": 0.0, "output": 0.0, "usd": 0.0}
    for sh in s["a10_local_rerun"]:
        for n, size, cap in ((fc.A10_LOCAL_CALLS * sh, fc.A10_LOCAL_BYTES, vc["output_limits"]["LOCAL"]),
                             (a10pages, fc.A10_PAGE_BYTES, vc["output_limits"]["GLOBAL"])):
            mult = 1 + r10 * (1 + fc.A10_RETRIEVAL_SHARE)
            rr = b._rates(m10.model, int(size / bpt))
            a10["calls"] += n * (1 + r10)
            a10["input"] += n * mult * size / bpt
            a10["output"] += n * mult * cap * out_share
            a10["usd"] += n * mult * (size / bpt * rr["input"] + cap * out_share * rr["output"]) / 1e6
    check["A10 verification"] = a10["usd"]

    # ---------------------------------------------------------------- A08, A09, A11, A12 (request-bound)
    req = breq(route, cfg, F, inputs)
    bridge_rows = {}
    for a in ("A08-OL", "A09-WRI", "A11-RC", "A12-EDI"):
        x = {"calls": 0.0, "max_calls": len(req[a][0]), "input": 0.0, "output": 0.0, "usd": 0.0, "long_context": 0}
        for bound, kind, tag in req[a][0]:
            w = _weight(tag, s)
            usd, used, crosses, _ = _price(a, bound, kind, b, route, cfg.get("admission") or {}, cfg.get("bridge") or {}, s)
            x["calls"] += w
            x["input"] += w * bound / bpt
            x["output"] += w * used
            x["usd"] += w * usd
            x["long_context"] += int(bool(w) and bound / bpt > ((b.prices.get(route(a).model) or {}).get("long_context_threshold") or 1e18))
        bridge_rows[a] = x
    check.update({"A08 outline": bridge_rows["A08-OL"]["usd"], "A09 writing": bridge_rows["A09-WRI"]["usd"],
                  "A11 critique": bridge_rows["A11-RC"]["usd"], "A12 editing": bridge_rows["A12-EDI"]["usd"]})
    retry = float(s["retries"])
    model_usd = a07["usd"] + a10["usd"] + sum(x["usd"] for x in bridge_rows.values())
    check["failed and redone calls (A07-A12)"] = model_usd * retry

    def model_row(stage, agent, x, calls_note, input_label, input_note, output_note, cache_note, uncertainty, extra=None):
        return {"stage": stage, "model": route(agent).model,
                "calls": cell(round(x["calls"], 1), "ASSUMED" if agent != "A08-OL" else "MEASURED", calls_note),
                "input_tokens": cell(round(x["input"]), input_label, input_note),
                "output_tokens": cell(round(x["output"]), "ASSUMED", output_note),
                "reasoning_tokens": cell("in output", "ASSUMED", "thinking/reasoning counted inside the output share"
                                         + ("; Kimi: max_tokens plus a 32,000-token reasoning reserve" if agent == "A11-RC" else "")),
                "batch": cell("none", "ASSUMED", "interactive"),
                "cache": cell("none", "ASSUMED", cache_note),
                "repeats": cell(0, "ASSUMED"),
                "retries_usd": cell(x["usd"] * retry, "ASSUMED", f"{retry:.0%} of the stage's cost (failed calls redone); unmeasured"),
                "cost_usd": cell(x["usd"] * (1 + retry), "EXTRAPOLATED" if agent in ("A07-SYN", "A10-RV") else "ASSUMED",
                                 "stage cost plus its retry share"),
                "uncertainty": uncertainty, **(extra or {})}

    rows.append(model_row("A07-SYN synthesis", "A07-SYN", a07,
                          f"{groups} GROUP + {pages} RECONCILE + PLAN + FINAL, GROUP/RECONCILE x(1 + {r}) retrieval",
                          "EXTRAPOLATED", f"provider-counted input MEASURED at 642/1,353/1,996 findings, fitted and carried to {F:,}",
                          f"{out_share:.0%} of each mode's output cap (ASSUMED, unmeasured)",
                          "system prompt priced as plain input: no 1-hour write premium (x2) and no read discount (x0.1); real cost may go either way",
                          "the largest single stage; output share and retrieval rate unmeasured",
                          {"by_mode": {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in a07["by_mode"].items()}}))
    for agent, stage in (("A08-OL", "A08-OL outline"), ("A09-WRI", "A09-WRI writing"), ("A11-RC", "A11-RC critique"), ("A12-EDI", "A12-EDI editing")):
        x = bridge_rows[agent]
        rows.append(model_row(stage, agent, x,
                              f"expected {x['calls']:.1f} of at most {x['max_calls']} the loops allow (retrieval {s['retrieval']}, redraft {s['redraft']}, "
                              f"cycles {s['cycles']}, revisions {s['revisions']}: ASSUMED)",
                              "MEASURED" if agent in ("A09-WRI", "A12-EDI") else "ASSUMED",
                              f"byte bounds MEASURED with the production builders on the compact 120-paper fixture, / {bpt} bytes per token "
                              + ("(MEASURED 1.9-2.4 on Claude)" if agent in ("A09-WRI", "A12-EDI") else "(ASSUMED: GPT/Kimi tokenization not counted)"),
                              f"{out_share:.0%} of the output reserve (ASSUMED)", "no cache savings assumed (conservative)",
                              {"A08-OL": "one call; GPT tokenization unmeasured", "A09-WRI": "retrieval and redraft frequency unmeasured",
                               "A11-RC": "Kimi tokenization and reasoning length unmeasured", "A12-EDI": "revision count unmeasured"}[agent],
                              {"long_context_calls": x["long_context"]}))
    rows.append(model_row("A10-RV verification", "A10-RV", a10,
                          f"{fc.A10_LOCAL_CALLS} LOCAL x executions {s['a10_local_rerun']} + {a10pages} GLOBAL pages per execution, x(1 + {r10}) retrieval",
                          "EXTRAPOLATED", f"production request bounds MEASURED for a 5,000-word manuscript at 1,996 findings, / {bpt} (GPT tokenization ASSUMED)",
                          f"{out_share:.0%} of each output cap (ASSUMED)", "no cache savings assumed; the A10 job's own result cache is reflected only through the re-verification shares",
                          "re-verification shares and retrieval rate unmeasured; the largest uncertainty after A07"))

    # ---------------------------------------------------------------- reconciliation
    for k, v in check.items():
        got = official["scenarios"]["baseline"][k]
        assert abs(round(v, 2) - got) < 1e-9, (k, v, got)
    total = sum(check.values())
    assert round(total, 2) == official["scenarios"]["baseline"]["total"], (total, official["scenarios"]["baseline"]["total"])
    with_margin = round(round(total, 2) * (1 + margin), 2)
    assert with_margin == official["baseline_with_margin"]
    row_sum = sum(x["cost_usd"]["value"] for x in rows if x.get("cost_usd", {}).get("value") is not None)
    assert abs(row_sum - total) < 1e-9, (row_sum, total)
    out = {"source": f"forecast.full_run at {root.name} (commit-specific); baseline scenario; 120 papers ({n_ft} full text, "
                     f"{n_ab} abstracts), {F:,} findings", "rows": rows,
           "reconciliation": {"stage_figures_unrounded": check, "total_unrounded": total,
                              "baseline_usd": round(total, 2), "margin": margin, "baseline_with_margin_usd": with_margin,
                              "gap_baseline_vs_150": round(round(total, 2) - 150, 2),
                              "gap_with_margin_vs_150": round(with_margin - 150, 2),
                              "row_costs_sum_to_total": True, "each_stage_equals_forecast_full_run": True},
           "counted": {"A06_instability_repeat": f"yes: {sum(n_rep.values())} papers, ${rep_usd:.2f}",
                       "A06_theme_pass": f"yes, as {themes} calls (${theme_usd:.2f}); the current architecture makes one call per primary theme (5-8)",
                       "batch_discount": f"yes: x{bf} on A05/A06 per-paper work after one interactive probe per level, and on the repeats; no batch elsewhere"},
           "label": "UNVALIDATED: 120-paper projection; not validated until a larger cohort has run"}
    path = HERE / "docs" / "integration_validation" / "reconciled_120.json"
    path.write_text(json.dumps(out, indent=2, default=float) + "\n", encoding="utf-8")
    (HERE / "docs" / "integration_validation" / "reconciled_120.md").write_text(markdown(out), encoding="utf-8")
    for x in rows:
        c = x.get("cost_usd", {}).get("value")
        print(f"{x['stage']:30s} {'' if c is None else f'{c:10.4f}'}")
    print(json.dumps(out["reconciliation"], indent=1, default=float))


TAG = {"MEASURED": "M", "EXTRAPOLATED": "E", "ASSUMED": "A"}


def _fmt(c, kind):
    if not c:
        return ""
    v = c["value"]
    if v is None:
        text = "in subtotal"
    elif kind == "tokens" and isinstance(v, (int, float)):
        text = f"{v / 1e6:,.2f}M"
    elif kind == "usd":
        text = f"${v:,.2f}"
    elif isinstance(v, float):
        text = f"{v:,.1f}"
    elif isinstance(v, int):
        text = f"{v:,}"
    else:
        text = str(v)
    return f"{text} ({TAG[c['label']]})"


def markdown(out: dict) -> str:
    rec = out["reconciliation"]
    lines = ["# Reconciled 120-paper forecast (UNVALIDATED)", "", out["source"], "",
             "Labels: M measured, E extrapolated, A assumed. Tokens in millions. Cost includes each stage's retry share.", "",
             "| Stage | Model | Calls | Input | Output | Reasoning | Batch | Cache | Repeats | Retries | Cost |",
             "|---|---|---:|---:|---:|---|---|---|---:|---:|---:|"]
    for r in out["rows"]:
        lines.append("| " + " | ".join([r["stage"], r.get("model", ""), _fmt(r.get("calls"), "n"),
                                         _fmt(r.get("input_tokens"), "tokens"), _fmt(r.get("output_tokens"), "tokens"),
                                         _fmt(r.get("reasoning_tokens"), "s"), _fmt(r.get("batch"), "s"),
                                         _fmt(r.get("cache"), "s"), _fmt(r.get("repeats"), "n"),
                                         _fmt(r.get("retries_usd"), "usd"), _fmt(r.get("cost_usd"), "usd")]) + " |")
    lines += [f"| **Total** | | | | | | | | | | **${rec['baseline_usd']:,.2f}** |", "",
              f"- Baseline ${rec['baseline_usd']:,.2f} (unrounded {rec['total_unrounded']:.4f}); with the "
              f"{rec['margin']:.0%} margin ${rec['baseline_with_margin_usd']:,.2f}.",
              f"- Gap to $150: ${rec['gap_baseline_vs_150']:,.2f} at baseline, ${rec['gap_with_margin_vs_150']:,.2f} with the margin.",
              "- Every stage equals forecast.full_run's own figure to 1e-9 USD; the row costs sum to the total.", "",
              "## Counted", ""] + [f"- {k.replace('_', ' ')}: {v}" for k, v in out["counted"].items()] + \
             ["", "## What each figure rests on", ""]
    for r in out["rows"]:
        notes = [f"{k.replace('_', ' ')}: {c['note']}" for k, c in r.items() if isinstance(c, dict) and c.get("note")]
        if r.get("uncertainty"):
            notes.append(f"uncertainty: {r['uncertainty']}")
        lines.append(f"- **{r['stage']}**. " + "; ".join(notes))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
