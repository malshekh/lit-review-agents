"""The job ledger: one append-only line per state change of every provider call, and the run lock.

A call moves through explicit states, each written to runs/<id>/data/job_ledger.jsonl before the next step starts:

    PREPARED        the request is built
    RESERVED        its worst-case cost is held
    DISPATCHED      it is about to be sent (written BEFORE the send)
    RESPONSE_SAVED  the provider's reply and usage are on disk (written BEFORE accounting)
    ACCOUNTED       the cost is in costs.jsonl and the hold is settled
    VALIDATED       the reply passed its schema and checks
    COMMITTED       the accepted output is written and has a receipt
or ends in a named failure: REFUSED, TRUNCATED, INVALID, REPAIR_REJECTED, API_ERROR.

What the order buys on a restart (Ledger.recovery):
  - last state RESPONSE_SAVED: the reply arrived and was saved but the process died before accounting. The saved
    reply is accounted and used; nothing is sent again and nothing paid for is lost.
  - last state DISPATCHED: the process died, or the connection dropped, with the request in flight. Whether the
    provider completed and billed it is unknown. The call is NOT resent; the run stops until the provider's
    usage page has been checked (`litreview resolve-dispatch`).
  - anything earlier: nothing was sent; the call starts again.

The run lock (runs/<id>/run.lock) stops two processes from dispatching for the same run at once.
"""
from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

STATES = ("PREPARED", "RESERVED", "DISPATCHED", "RESPONSE_SAVED", "ACCOUNTED", "VALIDATED", "COMMITTED")
FAILURES = ("REFUSED", "TRUNCATED", "INVALID", "REPAIR_REJECTED", "API_ERROR", "RESOLVED_NOT_BILLED", "RESOLVED_BILLED")


class AmbiguousDispatch(RuntimeError):
    """A request was in flight when the previous process stopped: it may have completed and been billed."""


class RunLocked(RuntimeError):
    """Another live process holds this run."""


class Ledger:
    def __init__(self, run_dir: Path):
        self.path = Path(run_dir) / "data" / "job_ledger.jsonl"
        self.out_dir = Path(run_dir) / "outputs"

    def record(self, step: str, attempt: int, state: str, **detail) -> None:
        if state not in STATES and state not in FAILURES:
            raise ValueError(f"unknown job state {state}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "step": step, "attempt": attempt,
                           "state": state, **detail}, ensure_ascii=False)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def events(self, step: str | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        rows = [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines() if x.strip()]
        return [r for r in rows if step is None or r["step"] == step]

    def last(self, step: str) -> dict | None:
        rows = self.events(step)
        return rows[-1] if rows else None

    # --- the saved reply: written before accounting, so a crash between the two loses nothing ---------------
    def response_file(self, step: str, attempt: int) -> Path:
        return self.out_dir / f"{step}.response{attempt}.json"

    def save_response(self, step: str, attempt: int, resp, request: dict) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        doc = {"text": resp.text, "provider": resp.provider, "model": resp.model, "stop_reason": resp.stop_reason,
               "refusal_category": resp.refusal_category, "input_tokens": resp.input_tokens,
               "output_tokens": resp.output_tokens, "cached_input_tokens": resp.cached_input_tokens,
               "cache_write_tokens": resp.cache_write_tokens, "cache_write_1h_tokens": resp.cache_write_1h_tokens,
               "request": request}
        target = self.response_file(step, attempt)
        tmp = target.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
        self.record(step, attempt, "RESPONSE_SAVED", output_tokens=resp.output_tokens)

    def load_response(self, step: str, attempt: int) -> dict | None:
        p = self.response_file(step, attempt)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def recovery(self, step: str) -> tuple[str, dict | None]:
        """What the step's last recorded call left behind:
        ("NONE", None)             nothing to recover
        ("AMBIGUOUS", event)       sent, no reply saved: completion unknown
        ("RESUME_SAVED", event)    reply saved, cost not yet logged
        ("RESUME_ACCOUNTED", event) reply saved and cost logged, output not yet committed with a receipt"""
        last = self.last(step)
        if last is None:
            return "NONE", None
        if last["state"] == "DISPATCHED":
            return "AMBIGUOUS", last
        if self.load_response(step, last["attempt"]) is None:
            return "NONE", None
        if last["state"] == "RESPONSE_SAVED":
            return "RESUME_SAVED", last
        if last["state"] in ("ACCOUNTED", "VALIDATED", "COMMITTED"):
            return "RESUME_ACCOUNTED", last
        return "NONE", None

    def ambiguous(self) -> list[dict]:
        latest: dict[str, dict] = {}
        for e in self.events():
            latest[e["step"]] = e
        return [e for e in latest.values() if e["state"] == "DISPATCHED"]

    def resolve(self, step: str, billed: bool, by: str, note: str) -> dict:
        """A person's finding, from the provider's usage page, about a request that was in flight."""
        last = self.last(step)
        if last is None or last["state"] != "DISPATCHED":
            raise ValueError(f"{step} has no request in flight to resolve")
        if not (by or "").strip() or not (note or "").strip():
            raise ValueError("resolving a dispatch needs who checked the provider's usage and what they found")
        self.record(step, last["attempt"], "RESOLVED_BILLED" if billed else "RESOLVED_NOT_BILLED", by=by.strip(),
                    note=note.strip(), reservation=last.get("reservation"))
        return self.last(step)


# ---------------------------------------------------------------------------------------------- run lock
def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = k32.OpenProcess(0x1000, False, pid)                       # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5                            # access denied: it exists, owned by another user
        code = wintypes.DWORD()
        ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return bool(ok) and code.value == 259                              # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class RunLock:
    """with RunLock(run_dir): only one live process on this machine works on the run. A lock left by a process
    that no longer exists is taken over, and the takeover is reported."""

    def __init__(self, run_dir: Path):
        self.path = Path(run_dir) / "run.lock"
        self.took_over: dict | None = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        me = {"pid": os.getpid(), "host": socket.gethostname(), "since": time.strftime("%Y-%m-%dT%H:%M:%S")}
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    holder = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    holder = {}
                same_host = holder.get("host") == me["host"]
                if holder.get("pid") == me["pid"] and same_host:
                    self.reentrant = True
                    return self
                if same_host and not _alive(int(holder.get("pid") or 0)):
                    self.took_over = holder
                    self.path.unlink(missing_ok=True)
                    continue
                raise RunLocked(f"run is in use by process {holder.get('pid')} on {holder.get('host')} since "
                                f"{holder.get('since')}. Two processes must never dispatch for one run. If that "
                                f"process is gone, delete {self.path}.")
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(me, fh)
                self.reentrant = False
                return self
        raise RunLocked(f"could not take the run lock {self.path}")

    def __exit__(self, *exc):
        if not getattr(self, "reentrant", False):
            self.path.unlink(missing_ok=True)
        return False
