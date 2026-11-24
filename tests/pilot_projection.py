"""Fresh pilot projection on the current architecture, for the selections in docs/pilot_acceptance_criteria.md.
Offline; no API calls.

    python -B tests/pilot_projection.py

Part 1, the gate as it stands: each selection is priced by the CP2 code path itself (cost_projection.for_selection: measured per-paper rates at
the 90th percentile, every paper repeated by the instability test, themes per paper, and A07-A12 lines at their
calibrated baseline plus the 30% margin). Pre-CP2 spend (A02-A04) is priced at worst case on the current routes:
every call at max_tokens, with the reference run's call counts and input sizes. The pilot runs through A12 (it is
also the scientific evaluation), so A08-A12 are included; before a package exists their lines are
ESTIMATED_ENVELOPE (bridge sizes per finding).

Part 2, at pilot scale: the calibrated A07/A10 lines are extrapolations below 642 findings, so they are replaced by
the production builders measured at pilot scale (tests/pilot_scale_measure.py), priced with the same baseline
assumptions and the same 30% margin; A08, A09, A11 and A12 come from the bridge envelope with the manuscript length
set to each option (A09, A10 and A12 cost follows the manuscript's length, not the paper count). The length options
are a scope decision for the researcher; nothing here changes the configuration.

Writes docs/integration_validation/pilot_projection.json.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]
from litreview import config                                   # noqa: E402
from litreview.budget import BudgetTracker                     # noqa: E402
from litreview.tools import cost_projection                    # noqa: E402
from litreview.tools import downstream_projection              # noqa: E402
sys.path.insert(0, str(ROOT / "tests"))
import pilot_scale_measure                                     # noqa: E402

REFERENCE = ROOT.parent / "lit-review-agents" / "runs" / "20261025-100039" / "costs.jsonl"
PAPERS = {"34638842": "FULL_TEXT", "29211715": "FULL_TEXT", "30771200": "ABSTRACT", "27006494": "ABSTRACT",
          "26254539": "ABSTRACT"}
WORDS = (5000, 3000, 2000, 1500)
STAND_IN = {"2 full texts + 3 abstracts": "2 full texts + 3 abstracts", "2 full texts + 2 abstracts": "2 full texts + 2 abstracts",
            "2 full texts + 1 abstract (trial)": "2 full texts + 1 abstract", "1 full text + 2 abstracts": "1 full text + 2 abstracts",
            "1 full text + 1 abstract (trial)": "1 full text + 1 abstract"}
SELECTIONS = {"2 full texts + 3 abstracts": ["34638842", "29211715", "30771200", "27006494", "26254539"],
              "2 full texts + 2 abstracts": ["34638842", "29211715", "30771200", "27006494"],
              "2 full texts + 1 abstract (trial)": ["34638842", "29211715", "30771200"],
              "1 full text + 2 abstracts": ["34638842", "30771200", "27006494"],
              "1 full text + 1 abstract (trial)": ["34638842", "30771200"]}


def pre_cp2(budget, route) -> dict:
    """A02-A04 at worst case on the current routes: the reference run's calls and input tokens, every call at
    its current max_tokens."""
    entries = [json.loads(x) for x in REFERENCE.read_text(encoding="utf-8").splitlines() if x.strip()]
    out = {}
    for agent in ("A02-SP", "A03-LM", "A04-CQ"):
        rows = [e for e in entries if e["agent"] == agent]
        m = route(agent)
        inp = sum(e["input_tokens"] + e.get("cached_input_tokens", 0) for e in rows)
        usd = sum(budget.cost(m.model, e["input_tokens"] + e.get("cached_input_tokens", 0), m.max_tokens) or 0
                  for e in rows)
        out[agent] = {"model": m.model, "calls": len(rows), "input_tokens": inp, "output_tokens_each": m.max_tokens,
                      "usd": round(usd, 4), "reference_usd": round(sum(e["cost_usd"] for e in rows), 4)}
    return out


def main():
    cfg = config.load("pipeline")
    rates = cost_projection.load_rates()
    tmp = Path(tempfile.mkdtemp())
    budget = BudgetTracker(tmp)
    route = lambda a, ex=frozenset(): config.agent_candidates(a)[0]
    pre = pre_cp2(budget, route)
    pre_usd = round(sum(x["usd"] for x in pre.values()), 2)
    cap, review = float(cfg["run"]["spend_cap_usd"]), float(cfg["run"]["spend_review_usd"])
    results = {}
    for name, pmids in SELECTIONS.items():
        selection = [{"record_id": f"R{i + 1:04d}", "pmid": p, "pmcid": "PMC1" if PAPERS[p] == "FULL_TEXT" else None}
                     for i, p in enumerate(pmids)]
        proj = cost_projection.for_selection(rates, selection, tmp, budget, route, cfg)
        total = round(proj["projected_remaining_usd"] + pre_usd, 2)
        results[name] = {"pmids": pmids, "findings_assumed": proj["findings_assumed"],
                         "after_cp2_usd": proj["projected_remaining_usd"], "pre_cp2_worst_usd": pre_usd,
                         "total_usd": total, "within_cap": total <= cap, "passes_review_point": total > review,
                         "lines": [{k: x.get(k) for k in ("stage", "basis", "calls", "usd", "baseline_usd", "adverse_usd")}
                                   for x in proj["lines"]]}
    margin = float(cfg["forecast"]["uncertainty_margin"])
    scale = {}
    for name, pmids in SELECTIONS.items():
        first = pilot_scale_measure.STAND_INS[STAND_IN[name]]
        with tempfile.TemporaryDirectory(prefix="pilot-scale-") as t:
            m = pilot_scale_measure.measure(first, Path(t), WORDS)
        per_paper = sum(x["usd"] for x in results[name]["lines"] if x["stage"].startswith("A05") or x["stage"].startswith("A06"))
        rows = {}
        for w in WORDS:
            priced = pilot_scale_measure.price({**m, "a10": m["by_words"][w]["a10"]}, cfg)
            journal = config.load("journal_scirev")
            journal = {**journal, "limits": {**journal["limits"], "main_text_max_words": w}}
            bl = {x["stage"]: x for x in downstream_projection.lines(budget, route, cfg, m["findings"], {"journal": journal})}
            base = {"A07-SYN": priced["A07-SYN"]["baseline_usd"], "A10-RV": priced["A10-RV"]["baseline_usd"],
                    **{a: bl[a]["baseline_usd"] for a in ("A08-OL", "A09-WRI", "A11-RC", "A12-EDI")}}
            model_base = sum(base.values())
            total_base = pre_usd + per_paper + model_base
            total_margin = pre_usd + per_paper + model_base * (1 + margin)
            rows[w] = {"words": w, "a10_occurrences": m["by_words"][w]["a10_occurrences"],
                       "a10_calls_first_pass": {k: v["calls"] for k, v in m["by_words"][w]["a10"].items()},
                       "baseline_by_agent": {k: round(v, 2) for k, v in base.items()},
                       "per_paper_p90_usd": round(per_paper, 2), "pre_cp2_worst_usd": pre_usd,
                       "total_baseline_usd": round(total_base, 2), "total_with_margin_usd": round(total_margin, 2),
                       "within_cap_with_margin": total_margin <= cap, "within_cap_baseline": total_base <= cap}
        scale[name] = {"stand_in_records": first, "findings": m["findings"], "by_words": rows}
    out = {"method": "Part 1: cost_projection.for_selection (the CP2 code path) + pre-CP2 worst case. Part 2: pilot-scale "
                     "A07/A10 measured with the production builders, bridge envelope by manuscript length. Planning, "
                     "not a bill; 2026-10-30 architecture", "cap_usd": cap, "review_point_usd": review,
           "uncertainty_margin": margin, "pre_cp2": pre, "selections": results, "pilot_scale": scale}
    path = ROOT / "docs" / "integration_validation" / "pilot_projection.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    for name, r in results.items():
        print(f"{name:36s} findings {r['findings_assumed']:4d}  after CP2 ${r['after_cp2_usd']:6.2f}  "
              f"total ${r['total_usd']:6.2f}  {'WITHIN' if r['within_cap'] else 'OVER'} ${cap:.0f}")
    print("pre-CP2", json.dumps(pre))
    for name, sc in scale.items():
        for w, r in sc["by_words"].items():
            print(f"{name:36s} {w:5d} words  base ${r['total_baseline_usd']:6.2f}  +margin ${r['total_with_margin_usd']:6.2f}"
                  f"  {r['baseline_by_agent']}")


if __name__ == "__main__":
    main()
