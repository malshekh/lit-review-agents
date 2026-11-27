"""Build and seal one runtime: the code of a clean git commit plus a hash manifest of every file in it.

    python scripts/build_runtime.py --dest D:\\...\\execution-YYYYMMDD-vNN-name --from-runtime D:\\...\\execution-...-v10 \\
        --run-id 20261031-213324-r0001-writing-v1 --version stage1-vNN-name --purpose "one line"

What it does, in order (it never calls a provider and never writes outside --dest):
  1. refuses a dirty worktree: a runtime is a commit, not a commit plus whatever was lying around;
  2. exports that commit's src/, config/, prompts/, schemas/, records/, the sample launcher, the billing
     reconciliation script, pyproject.toml and requirements.txt with `git archive`;
  3. copies from the previous runtime only what is not source: its vendored third-party packages, its CLI entry point
     (cli_entry.py); bootstrap.py is built from the reviewed scripts/runtime_bootstrap.py, the model-record telemetry and its baseline, and the named run folder;
  4. writes frozen_runtime_manifest.json (SHA-256 of every file outside runs/ except the telemetry file and the
     manifest itself, the git commit, and where each copied part came from);
  5. verifies the result with litreview.runtime_integrity.verify and prints the manifest's own SHA-256, which is
     the value to pin outside the runtime (the closeout note, your lab notebook).

A runtime built this way is the only place paid commands run; development trees stay free of live state.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROM_GIT = ["src", "config", "prompts", "schemas", "records", "a07_a09_sample.py", "scripts/reconcile_billing.py",
            "scripts/continue_page1001_import.py", "scripts/dispatch_preloaded_page.py", "scripts/run_pilot7_reconciliation.py", "scripts/import_pilot7_group.py", "scripts/plan_budget.py", "scripts/runtime_bootstrap.py", "scripts/pilot_smoke_continue.py", "scripts/pilot7_control.py", "scripts/pilot7_semantics_control.py", "scripts/pilot7_discovery_control.py", "scripts/plan_a05_functional.py", "scripts/offline_guard.py", "scripts/pilot_report.py", "docs/run_spec", "docs/pilot7",
            "pyproject.toml", "requirements.txt",
            "LICENSE.md"]
FROM_RUNTIME = ["vendor", "cli_entry.py", "candidate/model_record_baseline.jsonl",
                "records/model_record.jsonl"]
TELEMETRY = "records/model_record.jsonl"
MANIFEST = "frozen_runtime_manifest.json"


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", required=True)
    ap.add_argument("--from-runtime", required=True, help="the previous runtime: vendor, launcher, telemetry and run come from it")
    ap.add_argument("--run-id", help="a run folder to carry over (copied, never moved). Omit it for a fresh runtime: "
                                     "a new scientific run starts empty, with no earlier PLAN, approval, finding or "
                                     "financial authorization")
    ap.add_argument("--version", required=True)
    ap.add_argument("--purpose", required=True)
    args = ap.parse_args(argv)
    dest, prev = Path(args.dest).resolve(), Path(args.from_runtime).resolve()
    if dest.exists():
        print(f"REFUSED: {dest} exists; a runtime is built once and never rebuilt in place")
        return 1
    dirty = git("status", "--porcelain")
    if dirty:
        print("REFUSED: the worktree has uncommitted changes; commit first:\n" + dirty[:1000])
        return 1
    commit = git("rev-parse", "HEAD")
    run_src = prev / "runs" / args.run_id if args.run_id else None
    if run_src is not None and not run_src.is_dir():
        print(f"REFUSED: {run_src} not found")
        return 1
    dest.mkdir(parents=True)
    # 2. source, exactly as committed
    archive = subprocess.run(["git", "archive", "--format=tar", commit, *FROM_GIT], cwd=ROOT, check=True,
                             capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest, filter="data")
    # 3. what is not source
    for rel in FROM_RUNTIME:
        src, dst = prev / rel, dest / rel
        if not src.exists():
            print(f"REFUSED: {src} is missing in the previous runtime")
            return 1
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    (dest / "runs").mkdir(exist_ok=True)
    if run_src is not None:
        shutil.copytree(run_src, dest / "runs" / args.run_id)
    shutil.copy2(dest / "scripts/runtime_bootstrap.py", dest / "bootstrap.py")
    # 4. manifest
    files = {p.relative_to(dest).as_posix(): sha(p) for p in sorted(dest.rglob("*"))
             if p.is_file() and p.relative_to(dest).parts[0] != "runs" and p.relative_to(dest).as_posix() != TELEMETRY}
    manifest = {"runtime_version": args.version, "purpose": args.purpose, "git_commit": commit,
                "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"), "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "source_paths_from_git": FROM_GIT,
                "copied_from_runtime": {"runtime": str(prev), "paths": FROM_RUNTIME, "run": args.run_id,
                                        "note": "engineering only: vendored packages, launcher, model-record telemetry"},
                "files": files, "mutable_telemetry": {"baseline": "candidate/model_record_baseline.jsonl"}}
    (dest / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    # 5. verify with the runtime's own verifier
    sys.path.insert(0, str(dest / "src"))
    from litreview.runtime_integrity import verify
    result = verify(dest, manifest)
    print(json.dumps({"runtime": str(dest), "git_commit": commit, **result,
                      "manifest_sha256": sha(dest / MANIFEST)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
