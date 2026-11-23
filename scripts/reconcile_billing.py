"""Compare a run's cost log with what the providers billed, and flag gaps over 5%.

    python scripts/reconcile_billing.py RUN_DIR --billed anthropic=12.41 openai=7.90 kimi=0.00
    python scripts/reconcile_billing.py RUN_DIR --billed-file billed.json     # {"anthropic": 12.41, "openai": 7.90}
    python scripts/reconcile_billing.py RUN_DIR --csv anthropic=usage_export.csv openai=cost_export.csv

Offline: it makes no API call and needs no key. The billed amounts are the ones you read from each provider's
console for the run's time window (printed below, in UTC and local time, so the same window can be selected):

    Anthropic   platform.claude.com -> Usage / Cost, filtered to the run's API key or workspace
    OpenAI      platform.openai.com -> Usage -> Costs, filtered to the project
    Kimi        platform.kimi.ai -> Billing

A CSV export is summed over its cost column (the first column whose header contains "cost" or "amount", in USD).

Why this exists: costs.jsonl prices each call from the token counts the API returned and config/prices.yaml. It is
wrong whenever a price changed, a tier or cache rule is misread, a call was billed but its response never arrived
(a held reservation with no logged entry), or another program used the same key. A gap over the threshold in
either direction exits with status 1 and should be explained before the next paid stage.

The report also lists what the log itself cannot settle: reservations still held (a call whose billing is
unknown), entries without a price, and batch entries (billed when the batch ends, sometimes on a later day).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

THRESHOLD = 0.05
MIN_GAP_USD = 0.05   # below this a percentage is noise (rounding to the cent on a small bill)


def load_log(run_dir: Path) -> list[dict]:
    path = Path(run_dir) / "costs.jsonl"
    if not path.exists():
        raise SystemExit(f"no cost log at {path}")
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def summarize(entries: list[dict]) -> dict:
    by = defaultdict(lambda: {"usd": 0.0, "calls": 0, "unpriced_calls": 0, "batch_calls": 0, "models": defaultdict(float)})
    for e in entries:
        p = by[e.get("provider") or "unknown"]
        p["calls"] += 1
        if e.get("cost_usd") is None:
            p["unpriced_calls"] += 1
        else:
            p["usd"] += e["cost_usd"]
            p["models"][e.get("model", "?")] += e["cost_usd"]
        p["batch_calls"] += bool(e.get("batch_id"))
    return {k: {**v, "usd": round(v["usd"], 4), "models": {m: round(c, 4) for m, c in v["models"].items()}}
            for k, v in by.items()}


def window(entries: list[dict]) -> dict | None:
    stamps = [e["started_at"] for e in entries if e.get("started_at")]
    if not stamps:
        return None
    fmt = "%Y-%m-%d %H:%M"
    return {"first_call_utc": time.strftime(fmt, time.gmtime(min(stamps))),
            "last_call_utc": time.strftime(fmt, time.gmtime(max(stamps))),
            "first_call_local": time.strftime(fmt, time.localtime(min(stamps))),
            "last_call_local": time.strftime(fmt, time.localtime(max(stamps)))}


def held(run_dir: Path) -> dict:
    path = Path(run_dir) / "reservations.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def csv_total(path: Path) -> float:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit(f"{path}: no rows")
    column = next((c for c in rows[0] if any(w in c.lower() for w in ("cost", "amount"))), None)
    if column is None:
        raise SystemExit(f"{path}: no column named like cost or amount (columns: {', '.join(rows[0])})")
    total = 0.0
    for r in rows:
        value = (r.get(column) or "").replace("$", "").replace(",", "").strip()
        if value:
            total += float(value)
    return total


def compare(logged: dict, billed: dict[str, float], threshold: float = THRESHOLD) -> list[dict]:
    rows = []
    for provider in sorted(set(logged) | set(billed)):
        log_usd = logged.get(provider, {}).get("usd", 0.0)
        bill = billed.get(provider)
        if bill is None:
            rows.append({"provider": provider, "logged_usd": log_usd, "billed_usd": None, "gap_usd": None,
                         "gap_share": None, "flag": "NO_BILLED_AMOUNT_GIVEN"})
            continue
        gap = bill - log_usd
        base = max(bill, log_usd)
        share = abs(gap) / base if base else 0.0
        flagged = share > threshold and abs(gap) >= MIN_GAP_USD
        rows.append({"provider": provider, "logged_usd": round(log_usd, 4), "billed_usd": round(bill, 4),
                     "gap_usd": round(gap, 4), "gap_share": round(share, 4),
                     "flag": ("BILLED_MORE_THAN_LOGGED" if gap > 0 else "LOGGED_MORE_THAN_BILLED") if flagged else "OK"})
    return rows


def _pairs(items: list[str], cast) -> dict:
    out = {}
    for item in items or []:
        name, _, value = item.partition("=")
        if not value:
            raise SystemExit(f"expected provider=value, got {item!r}")
        out[name.strip().lower()] = cast(value.strip())
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--billed", nargs="*", help="provider=USD, read from each provider's console")
    ap.add_argument("--billed-file", help='JSON file {"provider": USD}')
    ap.add_argument("--csv", nargs="*", help="provider=path to a console CSV export")
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    ap.add_argument("--out", help="write the report as JSON to this path (default: RUN_DIR/billing_reconciliation.json)")
    args = ap.parse_args(argv)
    run_dir = Path(args.run_dir)
    entries = load_log(run_dir)
    logged = summarize(entries)
    billed = _pairs(args.billed, float)
    if args.billed_file:
        billed.update({k.lower(): float(v) for k, v in json.loads(Path(args.billed_file).read_text(encoding="utf-8")).items()})
    billed.update({k: csv_total(Path(v)) for k, v in _pairs(args.csv, str).items()})
    rows = compare(logged, billed, args.threshold)
    reservations = held(run_dir)
    report = {"run": run_dir.name, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "threshold": args.threshold,
              "window": window(entries), "providers": rows, "logged": logged,
              "held_reservations": {k: v.get("usd") for k, v in reservations.items()},
              "notes": ["Prior spend carried into this run from an earlier run (evaluation budget) is not in this log.",
                        "Batch calls are billed when the batch ends; select the console window accordingly."]}
    w = report["window"]
    if w:
        print(f"Run {run_dir.name}: calls from {w['first_call_utc']} to {w['last_call_utc']} UTC "
              f"({w['first_call_local']} to {w['last_call_local']} local)")
    for r in rows:
        if r["billed_usd"] is None:
            print(f"  {r['provider']:10s} logged ${r['logged_usd']:.2f}; no billed amount given")
        else:
            print(f"  {r['provider']:10s} logged ${r['logged_usd']:.2f}  billed ${r['billed_usd']:.2f}  "
                  f"gap ${r['gap_usd']:+.2f} ({r['gap_share']:.1%})  {r['flag']}")
    for provider, p in logged.items():
        if p["unpriced_calls"]:
            print(f"  WARNING {provider}: {p['unpriced_calls']} logged call(s) have no price and are not in the logged total")
    if reservations:
        print(f"  WARNING {len(reservations)} reservation(s) still held: a call whose response was never logged may "
              f"have been billed ({', '.join(list(reservations)[:5])})")
    out = Path(args.out) if args.out else run_dir / "billing_reconciliation.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    flagged = [r for r in rows if r["flag"] not in ("OK", "NO_BILLED_AMOUNT_GIVEN")]
    if flagged:
        print(f"GAP over {args.threshold:.0%} for: {', '.join(r['provider'] for r in flagged)}. Explain it before the "
              "next paid stage (a changed price, a billed call with no logged response, or another user of the key).")
        return 1
    if not billed:
        print("No billed amounts given: nothing was compared. Read them from the provider consoles for the window above.")
        return 2
    print("Within the threshold for every provider compared.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
