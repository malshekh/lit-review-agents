"""Command line interface.

  litreview check [--ping] [--apis]        check config, keys; optionally test live connections
  litreview new --topic topic.md [--notes notes.md] [--seeds seeds.txt] [--family NAME]
  litreview run <run_id> [--until STAGE]   run or resume until the next checkpoint, the end, or STAGE
  litreview status <run_id>                current stage, status and spend
  litreview approve <run_id> CP1|CP2|CP3|CP_LEDGER|CP_CONTRARY|CP_CONTEXT|CP_SPEND   record a decision
  litreview revise <run_id> CP1|CP3 --feedback feedback.md   send the stage back with your corrections
  litreview costs <run_id>                 per-agent cost breakdown
  litreview repair-import <run_id> <step> --agent A0X --file fixed.json --by NAME --reason TEXT
                                           use your repair of an output that failed its schema (no second payment)
  litreview submission-check <run_id>      recompute the submission checklist after editing final/declarations
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
    run_id = new_run(_read(args.topic), _read(args.notes), seeds, args.family, budget_authority=args.budget_authority, corpus_mode=args.corpus_mode,
                     scope_configuration=json.loads(_read(args.scope_configuration)) if args.scope_configuration else None,
                     profile=args.profile)
    print(f"Created run {run_id}. Next: litreview run {run_id}")
    print(f"Created run {run_id}. Start it with:  litreview run {run_id}")
    return 0


def cmd_run(args) -> int:
    status = Run(args.run_id).run(until=args.until)
    print(status)
    return 0


def cmd_repair_import(args) -> int:
    from .repair_import import ImportRefused, import_output
    try:
        audit = import_output(Run(args.run_id), args.step, args.agent, Path(args.file), args.by, args.reason, args.schema)
    except ImportRefused as e:
        print(f"REFUSED: {e}")
        return 1
    print(f"Imported outputs/{args.step}.json ({len(audit['changed_paths'])} JSON path(s) differ from the saved reply; "
          f"audit in outputs/{args.step}.repair.audit.json). The next `litreview run {args.run_id}` uses it without "
          "paying for the call again.")
    return 0


def cmd_output_shares(args) -> int:
    from .tools import output_shares
    try:
        measured = output_shares.measure(RUNS_DIR / args.run_id)
    except output_shares.NotRepresentative as e:
        print(f"REFUSED: {e}")
        return 1
    print(json.dumps(measured, indent=2))
    if args.write:
        written = output_shares.write(measured)
        print(f"records/output_shares.json: {len(written)} cell(s) now MEASURED: {', '.join(written) or 'none'} "
              f"(a cell needs at least {output_shares.MIN_CALLS} completed calls)")
    return 0


def cmd_clear_refusal(args) -> int:
    from . import model_record
    if args.model not in model_record.refused(args.family):
        print(f"{args.model} has no standing refusal in topic family '{args.family}'")
        return 1
    model_record.clear(args.model, args.family, args.by, args.reason)
    print(f"Recorded: refusals of {args.model} in '{args.family}' before now no longer disqualify it. "
          "A new refusal disqualifies it again.")
    return 0


def cmd_submission_check(args) -> int:
    try:
        ready = Run(args.run_id).submission_check()
    except ValueError as e:
        print(e)
        return 1
    if ready["submission_ready"]:
        print("Submission checklist: all items pass. Re-run `litreview run` to write the final declarations into "
              "the manuscript files if you edited them after the export.")
        return 0
    print(f"NOT submission-ready: {len(ready['blockers'])} blocker(s)")
    for b in ready["blockers"]:
        print(f"  - {b}")
    return 1


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


def cmd_renormalize(args) -> int:
    rep = Run(args.run_id).renormalize()
    print(f"Identity changes in {len(rep['identity_changes'])} papers. Eligibility now: {rep['eligibility']}")
    est = rep["revalidation_cost_estimate_usd"]
    print(f"Papers needing A06 revalidation: {len(rep['papers_needing_revalidation'])} "
          f"({', '.join(rep['papers_needing_revalidation'])}); last A06 calls for them cost ${est['total']:.2f}")
    print("Details: data/renormalization/report.json. Nothing was sent to a model.")
    return 0


def cmd_revalidate(args) -> int:
    run = Run(args.run_id)
    if args.themes:
        print("Rebuilt theme records:", ", ".join(run.rebuild_stale_themes()) or "none stale")
        return 0
    ids = [r.strip() for r in (args.records or "").split(",") if r.strip()]
    if args.all_needed:
        ids = run.load("renormalization/report.json", {}).get("papers_needing_revalidation", [])
    if not ids:
        print("Name the papers (--records R0045,R0190) or use --all-needed after `litreview renormalize`.")
        return 1
    out = run.revalidate(ids)
    print(f"Revalidated {len(ids)} papers. Eligibility now: {out['eligibility']}. "
          f"{len(out['themes_stale'])} theme records are stale: rebuild with --themes before synthesis.")
    return 0


def cmd_gate2_report(args) -> int:
    from .tools import gate2_report
    data = RUNS_DIR / args.run_id / "data"
    rep = gate2_report.build(data)
    (data / "renormalization").mkdir(parents=True, exist_ok=True)
    (data / "renormalization" / "gate2_regression.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False),
                                                                    encoding="utf-8")
    print(gate2_report.text(rep))
    print("Details: data/renormalization/gate2_regression.json")
    return 0


def cmd_review_validation(args) -> int:
    run = Run(args.run_id)
    if args.rescan:
        items = run.review_revalidations()
        print(f"{len(items)} changed dispositions; {sum(i['action'] == 'QUARANTINED' for i in items)} quarantined.")
    if args.finding_id:
        decision = "KEEP_OLD" if args.keep_old else "ACCEPT_NEW" if args.accept_new else \
            "KEEP_QUARANTINED" if args.hold else None
        if not args.note or not (decision or args.cause):
            print("Give --cause and/or one of --keep-old, --accept-new, --hold, with --note saying what you checked "
                  "(the source, the extraction and both A06 readings).")
            return 1
        try:
            item = (run.decide_review(args.finding_id, decision, args.note, args.cause) if decision
                    else run.classify_review(args.finding_id, args.cause, args.note))
        except ValueError as e:
            print(e)
            return 1
        print(f"{args.finding_id}: {item.get('decision') or 'undecided'}, cause {item.get('cause')}; recorded as your decision.")
    items = run.load("validation_review.json", [])
    pending = [i for i in items if i["action"] == "QUARANTINED" and not i.get("decision")]
    for i in pending:
        print(f"  QUARANTINED {i['finding_id']:10s} {i['old_disposition']} -> {i['new_disposition']} ({i['direction']})"
              f"  cause: {i.get('cause') or 'unclassified'}" + (f"  note: {i['reviewer_note']}" if i.get("reviewer_note") else ""))
    print(f"{len(pending)} awaiting your decision.")
    from .evidence import review_by_cause
    print("Quarantined, by cause: " + json.dumps(review_by_cause([i for i in items if i["action"] == "QUARANTINED"])))
    return 0


def cmd_cost_rates(args) -> int:
    from .tools import cost_projection, output_shares
    if output_shares.is_sample(RUNS_DIR / args.run_id):
        print(f"REFUSED: {args.run_id} is a NON-REPRESENTATIVE sample run; its costs never enter the rates or the forecast")
        return 1
    rates = cost_projection.measured_rates(RUNS_DIR / args.run_id)
    cost_projection.rates_path().write_text(json.dumps(rates, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(rates, indent=1))
    print(f"Saved {cost_projection.rates_path()}")
    return 0


def cmd_calibration_report(args) -> int:
    from .tools import calibration_report
    print(json.dumps(calibration_report.report(RUNS_DIR / args.run_id), indent=1))
    return 0


def cmd_project(args) -> int:
    from .tools import cost_projection
    run = Run(args.run_id)
    from . import pilot_authorization as pilot
    if pilot.enabled(run):
        scope=pilot.STAGE_2 if getattr(args,'stage',None)=='2' else pilot.STAGE_1
        try: review=pilot.request(run,scope)
        except pilot.AuthorizationRequired as exc:print(str(exc));return 2
        print(json.dumps(review,indent=2))
        return 0 if review['projection']['verdict']=='WITHIN_CAP' else 2
    proj = cost_projection.remaining_for_run(run)
    run.save("cost_projection.json", proj)
    print(cost_projection.text(proj))
    return 0 if proj["verdict"] == "WITHIN_CAP" else 2


def cmd_pilot_reference(args) -> int:
    from . import pilot_authorization as pilot
    try:pilot.record_key(Run(args.run_id),json.loads(_read(args.metadata)))
    except (ValueError,OSError) as exc:print(str(exc));return 2
    print('Human reference-key metadata recorded; key contents never enter research payloads.')
    return 0


def cmd_authorize_stage(args) -> int:
    from . import pilot_authorization as pilot
    scope=pilot.STAGE_1 if args.stage=='1' else pilot.STAGE_2
    try:pilot.approve(Run(args.run_id),scope,args.fingerprint,args.reviewer)
    except ValueError as exc:print(str(exc));return 2
    print(scope+' recorded; all scientific checkpoints still apply.')
    return 0


def cmd_mark_evaluation_only(args) -> int:
    Run(args.run_id).mark_evaluation_only(args.reason)
    print(f"Run {args.run_id} is evaluation-only: its synthesis is stamped and refused by every publication stage.")
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
    n.add_argument("--scope-configuration", help="human scope configuration with parent CP1 hash; does not approve new checkpoints")
    n.add_argument("--budget-authority", help="reviewed cumulative evaluation-cost metadata; required for fixed pilot")
    n.add_argument("--corpus-mode", choices=["FIXED_CORPUS", "OPEN_CORPUS"], default="FIXED_CORPUS")
    n.add_argument("--profile", help="spend profile from config/pipeline.yaml -> profiles (pilot, sample, manuscript); "
                                     "recorded with the run, so its cap travels with it")
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
    a.add_argument("checkpoint", choices=["CP1", "CP2", "CP_SYN", "CP3", "CP_LEDGER", "CP_CONTRARY",
                                         "CP_CONTEXT", "CP_SPEND", "CP_AGENT_REVIEW"])
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
    rn = sub.add_parser("renormalize", help="re-run entity normalization with the current rules (no model calls)")
    rn.add_argument("run_id")
    rn.set_defaults(fn=cmd_renormalize)
    rv = sub.add_parser("revalidate", help="fresh A06 validation of named papers (paid), or rebuild stale themes")
    rv.add_argument("run_id")
    rv.add_argument("--records", help="comma-separated record IDs")
    rv.add_argument("--all-needed", action="store_true", help="every paper renormalize listed as needing it")
    rv.add_argument("--themes", action="store_true", help="rebuild theme records made stale by a revalidation")
    rv.set_defaults(fn=cmd_revalidate)
    g2 = sub.add_parser("gate2-report", help="recovery and new error after a normalization correction")
    g2.add_argument("run_id")
    g2.set_defaults(fn=cmd_gate2_report)
    rq = sub.add_parser("review-validation", help="list or decide revalidation changes held for human review")
    rq.add_argument("run_id")
    rq.add_argument("finding_id", nargs="?")
    rq.add_argument("--keep-old", action="store_true")
    rq.add_argument("--accept-new", action="store_true")
    rq.add_argument("--hold", action="store_true", help="KEEP_QUARANTINED: neither reading is confirmed")
    rq.add_argument("--cause", choices=["BIOLOGICAL_INTERPRETATION", "EXTRACTION_ERROR", "CHANGED_CONTEXT",
                                        "UNEXPLAINED_MODEL_VARIANCE"], help="why the two readings disagree")
    rq.add_argument("--note")
    rq.add_argument("--rescan", action="store_true", help="apply the review rule to this run's revalidations")
    rq.set_defaults(fn=cmd_review_validation)
    cr = sub.add_parser("cost-rates", help="measure per-paper and per-theme costs from a run (records/cost_rates.json)")
    cr.add_argument("run_id")
    cr.set_defaults(fn=cmd_cost_rates)
    cb = sub.add_parser("calibration-report", help="report what a run measured for calibration (read only)")
    cb.add_argument("run_id")
    cb.set_defaults(fn=cmd_calibration_report)
    pj = sub.add_parser("project", help="project what a run still has to spend; required before spend after CP2")
    pj.add_argument("run_id")
    pj.add_argument('--stage',choices=['1','2'],default='1',help='staged pilot financial scope; no authorization is granted by projection')
    pj.set_defaults(fn=cmd_project)
    pr=sub.add_parser('pilot-reference',help='record a human-approved external reference-key version/hash, not its contents')
    pr.add_argument('run_id');pr.add_argument('--metadata',required=True);pr.set_defaults(fn=cmd_pilot_reference)
    au=sub.add_parser('authorize-stage',help='explicit human financial approval of the exact pending stage projection')
    au.add_argument('run_id');au.add_argument('stage',choices=['1','2'])
    au.add_argument('--fingerprint',required=True);au.add_argument('--reviewer',required=True);au.set_defaults(fn=cmd_authorize_stage)
    ri = sub.add_parser("repair-import", help="import your repair of a complete output that failed its schema (free)")
    ri.add_argument("run_id")
    ri.add_argument("step", help="the step name, as in outputs/<step>.raw0.txt")
    ri.add_argument("--agent", required=True, help="e.g. A07-SYN")
    ri.add_argument("--file", required=True, help="the repaired JSON file")
    ri.add_argument("--schema", help="schema file name when the step used a mode schema, e.g. A07-SYN.bounded-group.schema.json")
    ri.add_argument("--by", required=True, help="your name")
    ri.add_argument("--reason", required=True, help="what was wrong and what you changed")
    ri.set_defaults(fn=cmd_repair_import)
    os_ = sub.add_parser("output-shares", help="measured output tokens per call from a run (never a sample run)")
    os_.add_argument("run_id")
    os_.add_argument("--write", action="store_true", help="replace the measured cells of records/output_shares.json")
    os_.set_defaults(fn=cmd_output_shares)
    cl = sub.add_parser("clear-refusal", help="record that a model's earlier refusals in a topic family no longer disqualify it")
    cl.add_argument("model")
    cl.add_argument("--family", required=True)
    cl.add_argument("--by", required=True, help="your name")
    cl.add_argument("--reason", required=True, help="why, e.g. the result of a one-mode retest")
    cl.set_defaults(fn=cmd_clear_refusal)
    sc = sub.add_parser("submission-check", help="recompute the submission checklist after editing final/declarations")
    sc.add_argument("run_id")
    sc.set_defaults(fn=cmd_submission_check)
    me = sub.add_parser("mark-evaluation-only", help="stamp a run's synthesis so no publication stage accepts it")
    me.add_argument("run_id")
    me.add_argument("--reason", required=True)
    me.set_defaults(fn=cmd_mark_evaluation_only)
    args = p.parse_args(argv)
    from .preflight import PreflightRefused, require_clean_endpoints
    try:
        if args.cmd not in ("check", "status", "costs"):   # reading is always allowed; nothing else starts
            require_clean_endpoints()
        return args.fn(args)
    except PreflightRefused as exc:
        print(f"REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
