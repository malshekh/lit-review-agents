"""Command line interface.

  litreview check                          check config: models set, prices present, keys loaded
  litreview new --topic topic.md [--notes notes.md] [--seeds seeds.txt]
  litreview run <run_id>                   run or resume until the next checkpoint or the end
  litreview status <run_id>                current stage, status and spend
  litreview approve <run_id> CP1|CP2|CP3   record your checkpoint decision
  litreview revise <run_id> CP1|CP3 --feedback feedback.md   send the stage back with your corrections
  litreview costs <run_id>                 per-agent cost breakdown
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import checkpoints, config
from .agents import AGENTS
from .budget import BudgetTracker
from .orchestrator import Run, new_run
from .paths import REPO_ROOT, RUNS_DIR


def _read(path: str | None) -> str:
    return Path(path).read_text(encoding="utf-8") if path else ""


def cmd_check(_args) -> int:
    ok = True
    prices = config.load("prices")
    allow = config.load("pipeline")["run"].get("allow_unpriced_models", False)
    for aid in AGENTS:
        try:
            m = config.agent_model(aid)
        except ValueError as e:
            print(f"  ✗ {e}")
            ok = False
            continue
        priced = (prices.get(m.model) or {}).get("input") is not None
        print(f"  {'✓' if priced or allow else '✗'} {aid:8s} {m.provider:9s} {m.model}"
              f"{'' if priced else '   (no price in config/prices.yaml)'}")
        ok &= priced or allow
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        print(f"  {'✓' if os.environ.get(key) else '✗'} {key} {'set' if os.environ.get(key) else 'missing in .env'}")
        ok &= bool(os.environ.get(key))
    print("Config OK" if ok else "Fix the items marked ✗ before running.")
    return 0 if ok else 1


def cmd_new(args) -> int:
    seeds = [s for s in _read(args.seeds).splitlines() if s.strip()]
    run_id = new_run(_read(args.topic), _read(args.notes), seeds)
    print(f"Created run {run_id}. Start it with:  litreview run {run_id}")
    return 0


def cmd_run(args) -> int:
    status = Run(args.run_id).run()
    print(status)
    return 0


def cmd_status(args) -> int:
    r = Run(args.run_id)
    st = r.state()
    print(f"Run {args.run_id}\n  stage:  {st['stage']}\n  status: {st['status']}")
    print("  " + r.budget.summary_text().replace("\n", "\n  "))
    return 0


def cmd_approve(args) -> int:
    r = Run(args.run_id)
    try:
        checkpoints.approve(r.dir, args.checkpoint, r.prov)
    except checkpoints.DecisionIncomplete as e:
        print(f"Not approved: {e}")
        return 1
    print(f"{args.checkpoint} approved and logged. Continue with:  litreview run {args.run_id}")
    return 0


def cmd_revise(args) -> int:
    back = {"CP1": ("scope", "cp1_feedback.json"), "CP3": ("synthesize", "cp3_feedback.json")}
    if args.checkpoint not in back:
        print("Revise is available for CP1 and CP3. For CP2, edit CP2_records.csv and approve.")
        return 1
    r = Run(args.run_id)
    stage, fname = back[args.checkpoint]
    r.save(fname, {"feedback": _read(args.feedback)})
    r.prov.human_decision(args.checkpoint, {"action": "REVISE"}, _read(args.feedback))
    st = r.state()
    st.update(stage=stage, status="READY")
    r.save_state(st)
    print(f"Sent back to {stage}. Run:  litreview run {args.run_id}")
    return 0


def cmd_costs(args) -> int:
    print(BudgetTracker(RUNS_DIR / args.run_id).summary_text())
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / ".env")
    p = argparse.ArgumentParser(prog="litreview", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    n = sub.add_parser("new")
    n.add_argument("--topic", required=True)
    n.add_argument("--notes")
    n.add_argument("--seeds")
    n.set_defaults(fn=cmd_new)
    for name, fn in (("run", cmd_run), ("status", cmd_status), ("costs", cmd_costs)):
        s = sub.add_parser(name)
        s.add_argument("run_id")
        s.set_defaults(fn=fn)
    a = sub.add_parser("approve")
    a.add_argument("run_id")
    a.add_argument("checkpoint", choices=["CP1", "CP2", "CP3"])
    a.set_defaults(fn=cmd_approve)
    v = sub.add_parser("revise")
    v.add_argument("run_id")
    v.add_argument("checkpoint", choices=["CP1", "CP3"])
    v.add_argument("--feedback", required=True)
    v.set_defaults(fn=cmd_revise)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
