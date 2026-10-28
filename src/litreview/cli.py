"""Command line interface.

  litreview check [--ping] [--apis]        check config, keys; optionally test live connections
  litreview new --topic topic.md [--notes notes.md] [--seeds seeds.txt] [--family NAME]
  litreview run <run_id> [--until STAGE]   run or resume until the next checkpoint, the end, or STAGE
  litreview status <run_id>                current stage, status and spend
  litreview approve <run_id> CP1|CP2|CP3   record your checkpoint decision
  litreview revise <run_id> CP1|CP3 --feedback feedback.md   send the stage back with your corrections
  litreview costs <run_id>                 per-agent cost breakdown
  litreview verify <run_id> <record_id> --statement TEXT [--matches TEXT]
                                           record that you verified an inconsistency inside a paper
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import checkpoints
from .budget import BudgetTracker
from .orchestrator import Run, new_run
from .paths import REPO_ROOT, RUNS_DIR


def _read(path: str | None) -> str:
    return Path(path).read_text(encoding="utf-8") if path else ""


def cmd_check(args) -> int:
    from .tools import healthcheck as hc
    print("Models and prices")
    lines, ok_cfg, providers = hc.config_lines()
    print("\n".join(lines))
    print("\nAPI keys (.env)")
    klines, ok_keys = hc.key_lines(providers)
    print("\n".join(klines))
    ok = ok_cfg and ok_keys
    if args.ping and ok:
        print("\nLive model check (one tiny call per provider)")
        l, good = hc.ping_llms(providers)
        print("\n".join(l))
        ok &= good
    if args.apis:
        print("\nLiterature and lookup APIs")
        l, good = hc.ping_sources()
        print("\n".join(l))
        ok &= good
    print("\n" + ("All checks passed." if ok else "Fix the items marked ✗ before running."))
    if ok and not (args.ping and args.apis):
        print("Tip: `litreview check --ping --apis` also tests live connections.")
    return 0 if ok else 1


def cmd_new(args) -> int:
    seeds = [s for s in _read(args.seeds).splitlines() if s.strip()]
    run_id = new_run(_read(args.topic), _read(args.notes), seeds, args.family)
    print(f"Created run {run_id}. Start it with:  litreview run {run_id}")
    return 0


def cmd_run(args) -> int:
    status = Run(args.run_id).run(until=args.until)
    print(status)
    return 0


def cmd_verify(args) -> int:
    try:
        Run(args.run_id).verify_source_inconsistency(args.record_id, args.statement, args.matches)
    except ValueError as e:
        print(e)
        return 1
    print(f"Verification for {args.record_id} recorded and logged as your decision. It reaches synthesis "
          "through the coverage manifest (re-run synthesis if it has already run).")
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


def cmd_approve_alternate(args) -> int:
    r = Run(args.run_id)
    try:
        p = r.approve_alternate(args.agent)
    except ValueError as e:
        print(e)
        return 1
    est = p["estimate"] or {}
    print(f"{args.agent} may use {p['alternate']} for this run"
          + (f" ({est['multiple']}x the cost of {p['primary']})" if est else "")
          + f". Logged as your decision. Continue with:  litreview run {args.run_id}")
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
    from .provenance import ProvenanceLog
    from .tools import verification_scope
    budget = BudgetTracker(RUNS_DIR / args.run_id)
    print(budget.summary_text())
    report = verification_scope.detail_report(ProvenanceLog(RUNS_DIR / args.run_id).events(), budget.entries())
    if report:
        print(verification_scope.detail_report_text(report))
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / ".env")
    for stream in (sys.stdout, sys.stderr):   # piped output on Windows may be cp1252: never crash on ✓/✗
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    p = argparse.ArgumentParser(prog="litreview", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--ping", action="store_true", help="make one tiny call to each LLM provider")
    c.add_argument("--apis", action="store_true", help="test literature and identifier APIs")
    c.set_defaults(fn=cmd_check)
    n = sub.add_parser("new")
    n.add_argument("--topic", required=True)
    n.add_argument("--notes")
    n.add_argument("--seeds")
    n.add_argument("--family", default="unspecified",
                   help="topic family for refusal routing, e.g. oncology-drug-repurposing (see records/model_record.jsonl)")
    n.set_defaults(fn=cmd_new)
    for name, fn in (("run", cmd_run), ("status", cmd_status), ("costs", cmd_costs)):
        s = sub.add_parser(name)
        s.add_argument("run_id")
        if name == "run":
            s.add_argument("--until", help="stop before this stage (e.g. synthesize), to review before paying for it")
        s.set_defaults(fn=fn)
    vf = sub.add_parser("verify")
    vf.add_argument("run_id")
    vf.add_argument("record_id")
    vf.add_argument("--statement", required=True, help="what you checked in the paper and what you found")
    vf.add_argument("--matches", help="text from the agent's description of the same inconsistency, to link to it")
    vf.set_defaults(fn=cmd_verify)
    a = sub.add_parser("approve")
    a.add_argument("run_id")
    a.add_argument("checkpoint", choices=["CP1", "CP2", "CP3"])
    a.set_defaults(fn=cmd_approve)
    aa = sub.add_parser("approve-alternate", help="accept a costlier alternate model after a refusal (this run only)")
    aa.add_argument("run_id")
    aa.add_argument("agent", help="e.g. A05-KE")
    aa.set_defaults(fn=cmd_approve_alternate)
    v = sub.add_parser("revise")
    v.add_argument("run_id")
    v.add_argument("checkpoint", choices=["CP1", "CP3"])
    v.add_argument("--feedback", required=True)
    v.set_defaults(fn=cmd_revise)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
