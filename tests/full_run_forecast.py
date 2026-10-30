"""Calibrated full-run forecast against the $150 cap and the separately approvable $200. Offline; no API calls.

    python -B tests/full_run_forecast.py

Uses src/litreview/tools/forecast.py with the scenario assumptions in pipeline.yaml -> forecast, the measured rates
in records/cost_rates.json, and the old run's content mix (11 of 28 papers full text). At 120 papers A08-A12 are
priced from the bridge's request builders on the compact 120-paper fixture (REQUEST_BOUND); other counts use the
per-finding estimate. A new run starts with nothing spent and nothing reserved. Writes
docs/integration_validation/forecast.json.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from litreview import bridge, config                          # noqa: E402
from litreview.budget import BudgetTracker                    # noqa: E402
from litreview.tools import forecast                          # noqa: E402
from bridge_fixtures import compact_package, fixture_plan     # noqa: E402

FULL_TEXT_SHARE = 11 / 28


def main():
    cfg = config.load("pipeline")
    b = BudgetTracker(Path(tempfile.mkdtemp()))
    route = lambda a, ex=frozenset(): config.agent_candidates(a)[0]
    rates = json.loads((ROOT / "records" / "cost_rates.json").read_text(encoding="utf-8"))
    fx = compact_package(120)
    table = bridge.comparative_table(fx["pkg"], fx["findings"], fx["corpus"])
    plan, ledger = fixture_plan(fx["pkg"], fx["corpus"], table)
    inputs = {"pkg": fx["pkg"], "findings": fx["findings"], "corpus": fx["corpus"], "plan": plan, "ledger": ledger}
    at120 = forecast.full_run(120, FULL_TEXT_SHARE, cfg, b, route, rates, inputs)
    by_n = {}
    for n in (20, 28, 40, 50, 60, 70, 80, 100, 120):
        r = forecast.full_run(n, FULL_TEXT_SHARE, cfg, b, route, rates)
        by_n[n] = {"findings": r["findings"], "validation": r["validation"],
                   **{s: r["scenarios"][s]["total"] for s in r["scenarios"]},
                   "baseline_with_margin": r["baseline_with_margin"]}
    fits = {f"{label} <= ${cap}": max([n for n, v in by_n.items() if v[key] <= cap], default=None)
            for cap in (150, 200) for label, key in (("baseline + margin", "baseline_with_margin"), ("baseline", "baseline"),
                                                     ("adverse", "adverse"))}
    result = {"label": "UNVALIDATED: every projection here beyond 28 papers is unvalidated until a larger cohort has run",
              "method": "calibrated planning forecast (src/litreview/tools/forecast.py); measured inputs and stated "
                        "assumptions as documented there and in pipeline.yaml -> forecast; not a bill",
              "spent_usd": 0.0, "outstanding_reservations_usd": 0.0,
              "at_120_papers": at120, "by_paper_count": by_n, "largest_paper_count_fitting": fits,
              "exposures_not_added": {
                  "A05 Opus 5 fallback after a refusal": "about 2.5x A05's share; requires `litreview approve-alternate`",
                  "unbounded failures": "a failed paid call supersedes the projection; resuming needs a new one"}}
    out = ROOT / "docs" / "integration_validation" / "forecast.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"at_120": at120["scenarios"], "with_margin": at120["baseline_with_margin"], "by_n": by_n,
                      "fits": fits}, indent=1))


if __name__ == "__main__":
    main()
