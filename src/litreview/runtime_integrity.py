"""Immutable runtime inventory and narrowly authorized append-only model telemetry.

Run directories are mutable audit state, not immutable source. This verifier never
repairs or discards a mismatch. Its manifest must be pinned outside the runtime.
"""
import hashlib
import json
from pathlib import Path


class IntegrityError(ValueError):
    pass


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(root, manifest):
    root = Path(root).resolve()
    immutable = manifest["files"]
    mutable = {"records/model_record.jsonl"}
    def safe(relative):
        p = root / relative
        if p.is_symlink() or not p.resolve().is_relative_to(root):
            raise IntegrityError("Inventory path escapes runtime")
        return p
    for relative, expected in immutable.items():
        p = safe(relative)
        if not p.is_file() or sha(p) != expected:
            raise IntegrityError("Immutable file changed: " + relative)
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*")
              if p.is_file() and "runs" not in p.relative_to(root).parts[:1]}
    if actual - set(immutable) - mutable - {"frozen_runtime_manifest.json"}:
        raise IntegrityError("Unexpected runtime file")
    spec = manifest["mutable_telemetry"]
    seed = safe(spec["baseline"]).read_bytes()
    raw = safe("records/model_record.jsonl").read_bytes()
    if not raw.startswith(seed) or (raw and not raw.endswith(b"\n")):
        raise IntegrityError("Telemetry prefix changed or incomplete append")
    appended = []
    for line in raw[len(seed):].splitlines():
        try:
            e = json.loads(line)
            allowed = {"time", "model", "agent", "family", "outcome", "category", "run_id", "step", "note"}
            if set(e) - allowed or any(not isinstance(e.get(k), str) or not e[k] for k in ("time", "model", "agent", "family", "run_id", "step")):
                raise ValueError("Invalid telemetry fields")
            if e["outcome"] not in {"COMPLETED", "REFUSED", "NO_QUALIFIED_MODEL"}:
                raise ValueError("Invalid telemetry outcome")
            run = safe("runs/" + e["run_id"])
            if not run.is_dir() or run.parent != root / "runs":
                raise ValueError("Unknown telemetry run")
            state = json.loads((run / "state.json").read_text())
            if state.get("execution_mode") != "STAGED_PILOT":
                raise ValueError("Unapproved execution mode")
            ledger = [json.loads(s) for s in (run / "costs.jsonl").read_text().splitlines() if s.strip()]
            if e["outcome"] != "NO_QUALIFIED_MODEL" and not any(all(c.get(k) == e[k] for k in ("model", "agent", "step")) for c in ledger):
                raise ValueError("Telemetry requires reconciled call receipt")
        except (ValueError, KeyError, OSError, TypeError) as exc:
            raise IntegrityError("Unreconciled or unauthorized telemetry append") from exc
        appended.append(e)
    return {"immutable_files_verified": len(immutable), "telemetry_appends_verified": len(appended)}
