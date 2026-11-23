"""Import a researcher's repair of an output that was complete but failed its schema.

One command for every agent and mode (`litreview repair-import`): the pilot needed a purpose-built importer for
one A07 PLAN, and until it existed a paid, complete answer could not be used. The import

  - requires the saved raw reply of the step (outputs/<step>.raw<N>.txt), so only a real, paid output is
    repaired, and refuses a reply that was truncated (an incomplete answer is retried, not repaired by hand);
  - validates the repaired file against the same schema the call would have been validated against;
  - never overwrites an accepted output, and refuses anything inside an archived pilot;
  - writes an audit (who, why, the hashes of the raw reply and of the repair, and every JSON path that differs)
    and records the import as a human decision in the provenance log;
  - writes a receipt marked `imported`, which the next `litreview run` binds to the request that asks for this
    step, so the call is not paid for again (Run._receipt_reuse).

The repaired output is used exactly like a model output from then on; the provenance summary and the AI-use
disclosure draft show that a person repaired it.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from . import preflight
from .agents.base import AGENTS, changed_paths, parse_json, validate


class ImportRefused(ValueError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def import_output(run, step: str, agent_id: str, repaired_file: Path, by: str, reason: str,
                  schema_file: str | None = None) -> dict:
    from .synthesis_registry import fingerprint
    if agent_id not in AGENTS:
        raise ImportRefused(f"unknown agent {agent_id}")
    if not (by or "").strip() or not (reason or "").strip():
        raise ImportRefused("an import needs the name of the person who repaired the output (--by) and why (--reason)")
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", step):
        raise ImportRefused(f"unsafe step name {step!r}")
    try:
        preflight.require_not_archived(run.dir)
    except preflight.PreflightRefused as exc:
        raise ImportRefused(str(exc)) from exc
    out_dir = run.dir / "outputs"
    target = out_dir / f"{step}.json"
    if target.exists():
        raise ImportRefused(f"{step} already has an accepted output (outputs/{step}.json); it is not overwritten")
    raws = sorted(out_dir.glob(f"{step}.raw*.txt"), key=lambda p: int(re.search(r"raw(\d+)\.txt$", p.name).group(1)))
    if not raws:
        raise ImportRefused(f"no saved reply for {step} (outputs/{step}.raw<N>.txt): there is nothing to repair")
    raw = raws[-1]
    n = re.search(r"raw(\d+)\.txt$", raw.name).group(1)
    if (out_dir / f"{step}.truncated{n}.json").exists():
        raise ImportRefused(f"the last reply for {step} was truncated at its output cap: an incomplete answer is "
                            "retried with a larger cap, not completed by hand")
    try:
        repaired = json.loads(Path(repaired_file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ImportRefused(f"cannot read the repaired file as JSON: {exc}") from exc
    try:
        validate(agent_id, repaired, schema_file)
    except Exception as exc:   # noqa: BLE001 — jsonschema raises several families; any means the repair is not valid
        raise ImportRefused(f"the repaired file still fails the schema: {str(exc)[:600]}") from exc
    try:
        original = parse_json(raw.read_text(encoding="utf-8"))
        diff = changed_paths(original, repaired)
    except ValueError:
        diff = ["(the original reply was not parseable JSON)"]
    audit = {"step": step, "agent": agent_id, "schema_file": schema_file or AGENTS[agent_id].schema_file,
             "repaired_by": by.strip(), "reason": reason.strip(), "imported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "raw_reply": raw.name, "raw_sha256": _sha(raw), "repaired_sha256": _sha(Path(repaired_file)),
             "changed_paths": diff}
    (out_dir / f"{step}.repair.audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    target.write_text(json.dumps(repaired, ensure_ascii=False, indent=2), encoding="utf-8")
    receipts = run.load("receipts.json", {})
    receipts[step] = {"imported": True, "output_sha256": fingerprint(repaired), "repaired_by": by.strip(),
                      "accepted_at": audit["imported_at"]}
    run.save("receipts.json", receipts)
    run.prov.human_decision("REPAIR_IMPORT", {k: audit[k] for k in ("step", "agent", "repaired_by", "raw_sha256",
                                                                     "repaired_sha256")}
                            | {"changed_paths": len(diff)}, reason.strip())
    return audit
