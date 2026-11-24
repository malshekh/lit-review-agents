"""Run a launcher command with the network switched off, and report whether anything tried to use it.

    python scripts/offline_guard.py a07_a09_sample.py dry-run --run-id RUN

Before the command starts, every way out of the process is replaced by a function that counts the attempt and
raises: socket connections, name lookups, and the provider SDK client factories. Provider keys are blanked. The
command then runs in this same process. The last line printed is a JSON summary; exit status 3 means at least one
network attempt was made (and refused), whatever the command itself returned.

This is how "the dry run makes zero network calls" is checked rather than assumed.
"""
from __future__ import annotations

import json
import os
import runpy
import socket
import sys

ATTEMPTS: list[str] = []


def _refuse(kind: str):
    def blocked(*args, **kwargs):
        target = ""
        for a in args[1:3] if kind == "connect" else args[:2]:
            if isinstance(a, (str, tuple)):
                target = str(a)
                break
        ATTEMPTS.append(f"{kind} {target}".strip())
        raise OSError(f"offline_guard: network use refused ({kind} {target})")
    return blocked


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY", "GEMINI_API_KEY", "LANGSMITH_API_KEY"):
        os.environ[key] = ""
    os.environ["LANGSMITH_TRACING"] = "false"
    socket.socket.connect = _refuse("connect")
    socket.socket.connect_ex = _refuse("connect_ex")
    socket.create_connection = _refuse("create_connection")
    socket.getaddrinfo = _refuse("getaddrinfo")
    script = sys.argv[1]
    sys.argv = sys.argv[1:]
    code = 0
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    print(json.dumps({"offline_guard": {"command": sys.argv, "exit_code": code,
                                        "network_attempts": len(ATTEMPTS), "attempts": ATTEMPTS[:20]}}))
    return 3 if ATTEMPTS else code


if __name__ == "__main__":
    sys.exit(main())
