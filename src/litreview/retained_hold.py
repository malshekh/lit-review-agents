"""Explicit permission to continue after a proven HTTP 400 while retaining its unknown billing hold."""
from pathlib import Path
import hashlib
import json


def blocking_holds(budget, authorization: Path | None = None) -> list[str]:
    held = budget.reservations()
    if not held or authorization is None:
        return list(held)
    auth = json.loads(Path(authorization).read_text(encoding="utf-8"))
    allowed = {_authorized_key(budget, a) for a in [auth, *auth.get("additional_authorized_holds", [])]}
    return [key for key in held if key not in allowed]


def _authorized_key(budget, auth):
    held = budget.reservations()
    if (auth.get("run_id") != budget.log_path.parent.name or not auth.get("authorized_by")
            or auth.get("decision") != "CONTINUE_WITH_UNRESOLVED_HOLD"
            or auth.get("release_hold") is not False):
        raise ValueError("invalid retained-hold authorization")
    key = auth["reservation"]
    if key not in held:
        return None
    path = budget.log_path.parent / "smoke_receipts" / (key + ".json")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != auth["receipt_sha256"] or held[key]["usd"] != auth["held_usd"]:
        raise ValueError("retained hold or receipt differs from authorization")
    receipt = json.loads(raw)
    if receipt.get("state") not in ("DISPATCHED", "ERROR_RESPONSE"):
        raise ValueError("retained receipt is not an unresolved dispatch")
    log = budget.log_path.parent / "smoke_tests.jsonl"
    matches = [r for r in map(json.loads, log.read_text(encoding="utf-8").splitlines())
               if r.get("time") == held[key]["reserved_at"]
               and r.get("schema_file") == receipt.get("target")
               and r.get("provider") == auth["provider"] and r.get("model") == auth["model"]
               and r.get("schema_sha256") == auth["rejected_schema_sha256"]
               and r.get("accepted") is False and "Error code: 400" in r.get("error", "")
               and auth["provider_request_id"] in r.get("error", "")]
    if len(matches) != 1:
        raise ValueError("no unique confirmed HTTP 400 evidence; uncertain dispatch cannot be repeated")
    from .structured import slim
    if slim(receipt["target"], auth["provider"])[1] == auth["rejected_schema_sha256"]:
        raise ValueError("rejected schema is unchanged")
    return key
