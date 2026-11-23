"""Guarded launcher for the NON-REPRESENTATIVE A07 -> A09 writing sample (src/litreview/sample_mode.py).

Every subcommand except `continue --paid` makes no model call. Inside a promoted runtime run it through
bootstrap (`python -I -S -B bootstrap.py a07_a09_sample.py <subcommand> ...`); in a development tree run it
with PYTHONPATH=src. Writes into a live runtime need --live, which only the researcher passes.

  copy-run     --source DIR                         copy a run folder into this tree's runs/ (never the reverse)
  init         --run-id ID --max-groups N --max-sections 1|2 --created-by NAME [--min-words W --max-words W] [--live]
  import-plan  --run-id ID [--live]                 repaired PLAN -> TURN_IMPORTED_REPAIR (not approved)
  approve-plan-import --run-id ID --sha SHA --by NAME [--live]     RESEARCHER ONLY
  approve-checkpoint  --run-id ID --checkpoint CP_SYN|CP3|CP_LEDGER  RESEARCHER ONLY (decision file edited first)
  dry-run      --run-id ID                          gates + next calls + reserve() amounts; no provider reachable
  request-authorization --run-id ID --stage 1|2 [--live]           writes the pending stage projection
  authorize    --run-id ID --stage 1|2 --fingerprint F --reviewer NAME [--live]   RESEARCHER ONLY
  continue     --run-id ID --max-groups N --paid [--live]          PAID: runs until the next gate or COMPLETE_SAMPLE
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def _run(run_id):
    from litreview.singlepaper_eval import WritingRun
    return WritingRun(run_id)


def _paid_guard(run):
    """Only the routes the sample uses are reachable, and only for the sample's agents; no SDK retries."""
    from litreview import preflight
    from litreview.llm import router
    from litreview.orchestrator import Pause
    preflight.require_start(run.dir)   # ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN / OPENAI_BASE_URL set: refuse
    allowed = {"A07-SYN": "anthropic", "A08-OL": "openai", "A09-WRI": "anthropic"}
    originals = dict(router._PROVIDERS)

    def wrap(provider):
        def call(**kwargs):
            trace = kwargs.get("trace") or {}
            if trace.get("run_id") != run.id or allowed.get(trace.get("agent")) != provider:
                raise Pause(f"sample launcher refused {trace.get('agent')} on {provider}")
            return originals[provider](**kwargs)
        return call
    for name in list(router._PROVIDERS):
        router._PROVIDERS[name] = wrap(name) if name in ("anthropic", "openai") else (
            lambda **k: (_ for _ in ()).throw(Pause("provider not used by the sample")))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("copy-run"); c.add_argument("--source", required=True)
    i = sub.add_parser("init"); i.add_argument("--run-id", required=True); i.add_argument("--max-groups", type=int, required=True)
    i.add_argument("--created-by", required=True); i.add_argument("--live", action="store_true")
    i.add_argument("--max-sections", type=int, required=True, choices=[1, 2])
    i.add_argument("--min-words", type=int, default=800); i.add_argument("--max-words", type=int, default=1000)
    for name in ("import-plan", "dry-run"):
        p = sub.add_parser(name); p.add_argument("--run-id", required=True); p.add_argument("--live", action="store_true")
    a = sub.add_parser("approve-plan-import"); a.add_argument("--run-id", required=True)
    a.add_argument("--sha", required=True); a.add_argument("--by", required=True); a.add_argument("--live", action="store_true")
    k = sub.add_parser("approve-checkpoint"); k.add_argument("--run-id", required=True)
    k.add_argument("--checkpoint", required=True, choices=["CP_SYN", "CP3", "CP_LEDGER"]); k.add_argument("--live", action="store_true")
    q = sub.add_parser("request-authorization"); q.add_argument("--run-id", required=True)
    q.add_argument("--stage", required=True, choices=["1", "2"]); q.add_argument("--live", action="store_true")
    z = sub.add_parser("authorize"); z.add_argument("--run-id", required=True); z.add_argument("--stage", required=True, choices=["1", "2"])
    z.add_argument("--fingerprint", required=True); z.add_argument("--reviewer", required=True); z.add_argument("--live", action="store_true")
    g = sub.add_parser("continue"); g.add_argument("--run-id", required=True); g.add_argument("--max-groups", type=int, required=True)
    g.add_argument("--paid", action="store_true"); g.add_argument("--live", action="store_true")
    args = ap.parse_args(argv)

    os.environ["LANGSMITH_TRACING"] = "false"
    from litreview import sample_mode as sm, pilot_authorization as pilot, checkpoints
    from litreview.paths import RUNS_DIR

    if args.cmd == "copy-run":
        src = Path(args.source).resolve()
        dst = RUNS_DIR / src.name
        if dst.exists():
            print(f"REFUSED: {dst} exists"); return 1
        if sm.frozen_runtime():
            print("REFUSED: copy-run is for development trees, not a live runtime"); return 1
        shutil.copytree(src, dst)
        print(f"copied to {dst}"); return 0
    if args.cmd != "dry-run":
        sm.guard_live(getattr(args, "live", False))
    if args.cmd == "init":
        r = _run(args.run_id)
        if sm.policy(r):
            print("REFUSED: sample authority already exists"); return 1
        clone, tmp = sm.scratch_clone(r)   # packet order from the production builder; the real run is not written
        try:
            full, _ = clone._synthesis_job()
            ids = sm.first_groups(full.packets, args.max_groups)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print(json.dumps(sm.write_policy(r, ids, max_sections=args.max_sections, min_words=args.min_words,
                                         max_words=args.max_words, created_by=args.created_by, live=args.live),
                         indent=2)); return 0
    r = _run(args.run_id)
    if args.cmd == "import-plan":
        out = sm.import_repaired_plan(r, live=args.live)
        print(json.dumps({"job_tag": out["job_tag"], "researcher_approved": False,
                          "repaired_sha256": out["record"]["repaired_sha256"],
                          "next": "researcher reviews plan_repair_audit.json, then approve-plan-import"}, indent=2))
        return 0
    if args.cmd == "approve-plan-import":
        print(json.dumps(sm.approve_plan_import(r, args.sha, args.by, live=args.live), indent=2)); return 0
    if args.cmd == "approve-checkpoint":
        checkpoints.approve(r.dir, args.checkpoint, r.prov); print(f"{args.checkpoint} approved"); return 0
    if args.cmd == "dry-run":
        sm.dry_run(r); return 0
    if args.cmd == "request-authorization":
        rev = pilot.request(r, pilot.STAGE_1 if args.stage == "1" else pilot.STAGE_2)
        print(json.dumps({"fingerprint": rev["fingerprint"], "projection": rev["projection"]}, indent=2, default=str)); return 0
    if args.cmd == "authorize":
        pilot.approve(r, pilot.STAGE_1 if args.stage == "1" else pilot.STAGE_2, args.fingerprint, args.reviewer)
        print("authorized"); return 0
    if args.cmd == "continue":
        if not args.paid:
            print("REFUSED: paid continuation needs --paid (run dry-run first)"); return 1
        pol = sm.policy(r)
        if not pol or len(pol["group_ids"]) != args.max_groups:
            print("REFUSED: --max-groups does not match the sample authority"); return 1
        from litreview.singlepaper_eval import disable_sdk_retries
        disable_sdk_retries()
        _paid_guard(r)
        r.continue_evaluation()
        print(json.dumps({k: r.state().get(k) for k in ("stage", "status", "sample", "sample_group_ids")}, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
