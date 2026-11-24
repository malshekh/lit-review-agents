"""The budget plan for one explicit corpus: N full texts and M abstracts. Offline; no key, no call.

    python scripts/plan_budget.py --full-text 5 --abstract 10 [--words 3000] [--profile corpus15]

It prints, separately (they are different things and are never added into one "estimate"):
  expected          the baseline scenario, stage by stage
  uncertainty       the margin on top (forecast.uncertainty_margin)
  recovery          the allowance for retries and repairs inside each stage sub-cap
  smoke test        the allowance for the separately approved live smoke test
  stage sub-caps    expected + uncertainty + recovery per stage group: what each stage may commit
  largest request   the most a single call can reserve (its worst case with the margin held)
  limits            the profile's review points and hard cap, and whether the plan fits them

No CORE share and no full-text availability multiplier is applied: the counts are the ones given.
Every figure is a projection from measured rates that predate the current code (records/cost_rates.json says
which); the first three papers of the run are the first real measurement.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from litreview import config                                   # noqa: E402
from litreview.budget import BudgetTracker, derive_stage_caps  # noqa: E402
from litreview.tools import forecast                           # noqa: E402

STAGE_OF = {"A02-A04 (pre-CP2)": "A02-A04", "A05+A06 per paper": "A05-A06", "A06 instability repeats": "A05-A06",
            "A06 theme pass": "A05-A06", "A07 synthesis": "A07", "A08 outline": "A08-A09", "A09 writing": "A08-A09",
            "A10 verification": "A10", "A11 critique": "A11-A12", "A12 editing": "A11-A12"}
AGENT_OF = {"A02-A04": "A02-SP", "A05-A06": "A05-KE", "A07": "A07-SYN", "A08-A09": "A08-OL", "A10": "A10-RV",
            "A11-A12": "A11-RC"}


def plan(full_text: int, abstract: int, words: int | None, profile: str) -> dict:
    cfg = config.load("pipeline")
    settings = config.run_settings(profile)
    b = BudgetTracker(Path(tempfile.mkdtemp()))
    route = lambda a, ex=frozenset(): config.agent_candidates(a)[0]   # noqa: E731
    rates = json.loads((ROOT / "records" / "cost_rates.json").read_text(encoding="utf-8"))
    explicit = {"full_text": full_text, "abstract": abstract, **({"words": words} if words else {})}
    r = forecast.full_run(full_text + abstract, 0.0, cfg, b, route, rates, explicit=explicit)
    base = r["scenarios"]["baseline"]
    margin = float(cfg["forecast"]["uncertainty_margin"])
    expected: dict[str, float] = {}
    for line, usd in base.items():
        if line in STAGE_OF:
            expected[STAGE_OF[line]] = expected.get(STAGE_OF[line], 0.0) + usd
    redo = base.get("failed and redone calls (A07-A12)", 0.0)
    with_margin = {AGENT_OF[g]: usd * (1 + margin) for g, usd in expected.items()}
    caps = derive_stage_caps(with_margin, float(settings.get("recovery_allowance", 0.15)))
    smoke = float(settings.get("smoke_test_allowance_usd", 0.0))
    # the largest single reservation: the biggest A07/A10 request at its cap, input at the cache-write rate, x 1.3
    largest = {}
    for agent, tokens, cap in (("A07-SYN", 120_000, cfg["synthesis"]["output_limits"]["RECONCILE"]),
                               ("A10-RV", int(forecast.A10_PAGE_BYTES / 1.8), cfg["scientific_verification"]["output_limits"]["GLOBAL"]),
                               ("A09-WRI", 80_000, cfg["bridge"]["output_limits"]["A09_SECTION"])):
        m = route(agent)
        usd = (b.cost(m.model, 0, cap, 0, 0, tokens) if m.provider == "anthropic" else b.cost(m.model, 0, cap, 0, tokens)) or 0
        largest[agent] = round(usd * (1 + margin), 2)
    total_caps = caps["total_usd"] + smoke
    return {"corpus": {"full_text": full_text, "abstract": abstract, "expected_findings": r["findings"],
                       "manuscript_words_assumed": words or 5000},
            "expected_usd": {**{g: round(v, 2) for g, v in sorted(expected.items())}, "total": round(sum(expected.values()), 2)},
            "expected_failed_and_redone_usd": round(redo, 2),
            "uncertainty_allowance_usd": round(sum(expected.values()) * margin, 2),
            "recovery_allowance_usd": round(caps["total_usd"] - sum(with_margin.values()), 2),
            "smoke_test_allowance_usd": smoke,
            "stage_sub_caps_usd": caps["caps_usd"], "stage_sub_caps_total_usd": caps["total_usd"],
            "largest_single_reservation_usd": largest,
            "profile": {"name": profile, "review_points_usd": settings.get("spend_review_points_usd"),
                        "hard_cap_usd": settings["spend_cap_usd"], "target_usd": settings.get("target_usd")},
            "fits": {"sub_caps_plus_smoke_within_hard_cap": total_caps <= float(settings["spend_cap_usd"]),
                     "expected_plus_uncertainty_within_target": sum(expected.values()) * (1 + margin)
                     <= float(settings.get("target_usd") or settings["spend_cap_usd"])},
            "other_scenarios_total_usd": {k: v["total"] for k, v in r["scenarios"].items() if k != "baseline"},
            "basis": "records/cost_rates.json (the October run re-priced; not current code) and "
                     "records/output_shares.json (" + str(len(r["assumed_output_cells"])) + " output sizes ASSUMED). "
                     "The A10 figure is sized for the manuscript length shown.",
            "validation": r["validation"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full-text", type=int, required=True)
    ap.add_argument("--abstract", type=int, required=True)
    ap.add_argument("--words", type=int, help="the outline's total word budget (default: 5,000, the journal limit)")
    ap.add_argument("--profile", default="corpus15")
    args = ap.parse_args(argv)
    result = plan(args.full_text, args.abstract, args.words, args.profile)
    print(json.dumps(result, indent=2))
    return 0 if all(result["fits"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
