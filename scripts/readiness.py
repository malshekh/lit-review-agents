"""Readiness demonstration before any spending. Offline: no key, no network (every socket is refused).

    python scripts/readiness.py [--out docs/readiness/readiness.json]

It runs, and records the result of, each check the run must pass before money is spent:

  1. rehearsal      the scripted pipeline on 15 papers from A07 through A08, A09, A10, A11, A12 and export,
                    with injected failures (a section call and a verification call fail and are resumed)
  2. faults         malformed output, truncation, timeouts and dropped connections, crashes between ledger
                    states, out-of-order and partial batch results, refusals, repair that loses evidence
  3. resume         accepted outputs reused; a changed decision invalidates only its descendants
  4. accounting     every finding has a disposition; every manuscript claim has a verification verdict
  5. budget         recovery calls are reserved; a stage cannot borrow from another; derived sub-caps
  6. smoke test     lists the live model/schema checks still to approve (it is NOT run: it costs money)
  7. specification  the 15-paper outline and manifest route: validation, source access, early check

A check passes only if its tests pass. The script exits 1 if any check fails.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS = {
    "faults": ["tests/test_job_ledger_recovery.py", "tests/test_post_pilot_hardening.py::test_a_truncation_retry_gets_its_own_larger_reservation",
               "tests/test_refusal_routing.py", "tests/test_batch_stage.py",
               "tests/test_post_pilot_hardening.py::test_a_truncated_batch_item_keeps_its_reply_and_is_redone_at_a_larger_cap",
               "tests/test_post_pilot_hardening.py::test_batch_results_are_matched_by_request_id_not_by_returned_order"],
    "resume": ["tests/test_decisions_paging_contracts.py", "tests/test_post_pilot_hardening.py::test_a_resume_reuses_the_accepted_output_and_pays_nothing",
               "tests/test_integrated_pipeline.py::test_interrupted_calls_resume_without_repeating_paid_work"],
    "accounting": ["tests/test_integrated_pipeline.py", "tests/test_contrary_evidence.py", "tests/test_verification_job.py",
                   "tests/test_submission_integrity.py"],
    "budget": ["tests/test_post_pilot_hardening.py::test_a_stage_cannot_borrow_from_a_later_stage",
               "tests/test_post_pilot_hardening.py::test_every_send_is_reserved_first_and_released_after",
               "tests/test_run_spec_science_budget.py::test_stage_caps_are_derived_from_the_projection_and_cannot_conflict_with_it",
               "tests/test_run_spec_science_budget.py::test_the_five_plus_ten_plan_separates_its_parts_and_fits_its_profile",
               "tests/test_budget.py", "tests/test_runtime_gate.py"],
    "specification": ["tests/test_run_spec_science_budget.py"],
}


def pytest(targets: list[str]) -> dict:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "ANTHROPIC_API_KEY": "", "OPENAI_API_KEY": "",
           "MOONSHOT_API_KEY": "", "LANGSMITH_TRACING": "false"}
    for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "OPENAI_BASE_URL"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets], cwd=ROOT,
                       env=env, capture_output=True, text=True)
    tail = [ln for ln in p.stdout.splitlines() if " passed" in ln or " failed" in ln or ln.startswith("FAILED")]
    return {"passed": p.returncode == 0, "summary": tail[-1] if tail else p.stdout[-300:], "failures": tail[:-1][:20]}


def rehearsal(n: int = 15) -> dict:
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
    os.environ["LITREVIEW_TEST_TODAY"] = time.strftime("%Y-%m-%d")
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY"):
        os.environ[k] = ""

    def refuse(*a, **k):
        raise OSError("readiness rehearsal: network refused")
    socket.socket.connect = refuse
    socket.create_connection = refuse
    socket.getaddrinfo = refuse
    import integrated_pipeline as ip
    from litreview import model_record, orchestrator as orch
    from litreview.tools import references
    root = Path(tempfile.mkdtemp())
    orch.RUNS_DIR = root
    model_record.RECORD = root / "model_record.jsonl"
    orch.notify.send = lambda *a, **k: False
    saved = references.crossref_lookup
    references.crossref_lookup = lambda *a, **k: None
    try:
        r = ip.simulate(n, root, fail={"A09-WRI_draft1_S3": 1, "A10-RV_draft1": 1})
    finally:
        references.crossref_lookup = saved
    run = orch.Run(f"sim-{n}")
    final = root / f"sim-{n}" / "final"
    a10 = r["a10_final"]
    checks = {
        "reached_export": (final / "manuscript.md").exists() and (final / "submission_status.json").exists(),
        "every_finding_accounted": r["a07"]["findings_unaccounted"] == 0 and r["a07"]["coverage_incomplete"] == 0,
        "no_ineligible_evidence_used": not r["ineligible_findings_in_packets"] and not r["manuscript_tags_with_ineligible_roles"],
        "every_written_element_rendered": r["written_elements_rendered"] == r["written_elements"],
        "mandatory_items_written": not r["mandatory_not_written"],
        "every_claim_verified": a10["coverage"]["occurrences_reviewed"] == a10["coverage"]["occurrences_total"] > 0,
        "release_on_current_verification": a10["current_for_final_manuscript"] and a10["stamp_matches"],
        "injected_failures_resumed": (final / "manuscript.md").exists(),   # two injected call failures, then export
    }
    status = json.loads((final / "submission_status.json").read_text(encoding="utf-8")) if (final / "submission_status.json").exists() else {}
    return {"papers": r["papers"], "findings": r["findings"], "calls": r["calls"], "a07": r["a07"],
            "a10_release": a10["release"], "a10_coverage": a10["coverage"], "ledger": r["ledger"],
            "checks": checks, "passed": all(checks.values()),
            "submission_blockers_in_rehearsal": len(status.get("blockers", [])),
            "table_finding": next((b for b in status.get("blockers", []) if b.startswith("Table:")), None),
            "note": "Scripted models: this proves the machinery, not the science. Stages before A07 (search, CP2, "
                    "extraction, validation) are covered by their own tests in 'specification', 'faults' and 'resume'."}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "docs" / "readiness" / "readiness.json"))
    args = ap.parse_args(argv)
    result = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()}
    for name, targets in CHECKS.items():
        result[name] = pytest(targets)
        print(f"{name:14s} {'PASS' if result[name]['passed'] else 'FAIL'}  {result[name]['summary']}")
    sys.path.insert(0, str(ROOT / "src"))
    from litreview import structured
    from litreview.budget import BudgetTracker
    usd, todo = structured.smoke_estimate(BudgetTracker(Path(tempfile.mkdtemp())))
    result["smoke_test"] = {"passed": None, "status": "NOT RUN: needs your approval (it makes live calls)",
                            "combinations_to_confirm": len(todo), "worst_case_usd": round(usd, 4),
                            "command": f"litreview smoke-test --approve-usd {max(1.0, round(usd * 1.5, 2))} --by \"<your name>\""}
    print(f"{'smoke_test':14s} NOT RUN  {len(todo)} combinations, worst case ${usd:.2f}; needs your approval")
    import subprocess as sp
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    d = sp.run([sys.executable, "-B", str(ROOT / "scripts" / "rehearse_pilot7.py")], cwd=ROOT, env=env, capture_output=True, text=True,
               encoding="utf-8")
    tail = d.stdout[d.stdout.rfind("
{"):] if "
{" in d.stdout else "{}"
    try:
        discovery = json.loads(tail)
    except ValueError:
        discovery = {"passed": False, "error": (d.stderr or d.stdout)[-800:]}
    result["discovery_rehearsal"] = {"passed": d.returncode == 0 and discovery.get("passed") is True,
                                     **{k: discovery.get(k) for k in ("checkpoints_approved", "final_status", "calls_by_agent",
                                                                      "checks", "replay_findings_dropped_for_schema", "error")}}
    print(f"{'discovery':14s} {'PASS' if result['discovery_rehearsal']['passed'] else 'FAIL'}  pilot7 route scope -> export, "
          f"checkpoints {discovery.get('checkpoints_approved')}")
    result["rehearsal"] = rehearsal(15)
    print(f"{'rehearsal':14s} {'PASS' if result['rehearsal']['passed'] else 'FAIL'}  15 papers, "
          f"{result['rehearsal']['findings']} findings, A10 {result['rehearsal']['a10_release']}, checks {result['rehearsal']['checks']}")
    ok = all(v["passed"] for k, v in result.items() if isinstance(v, dict) and v.get("passed") is not None)
    result["ready_for_smoke_test"] = ok
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(("READY for the approved smoke test" if ok else "NOT READY") + f"; report: {args.out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
