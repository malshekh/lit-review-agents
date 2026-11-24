"""Checks that run before the pipeline starts. Each one refuses to start; none of them makes a network call.

1. Provider endpoints. The Anthropic and OpenAI SDKs read ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN and
   OPENAI_BASE_URL from the environment. A shell set up to run Claude Code on another vendor (Kimi's
   Anthropic-compatible endpoint is the usual case) exports exactly those variables, and every "Anthropic" call
   of the pipeline would then be sent to, billed by and answered by that vendor while the cost log, the
   provenance log and the AI disclosure all say Claude. Vendor separation between extraction and audit would
   silently be lost as well. The clients also pass their endpoint explicitly (pipeline.yaml -> providers), so
   this check is the second of two defences.
2. Prices. A model whose prices.yaml entry lacks a source or a check date, or was checked more than
   run.price_max_age_days ago, is listed; BudgetTracker.check_priced refuses it at call time.
3. Archive. Nothing under an archived pilot folder (marker file ARCHIVED_PILOT.json in any parent) is a valid
   run directory, runtime or input for a new run.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import config

REDIRECTING_ENV = {
    "ANTHROPIC_BASE_URL": "redirects every Anthropic SDK call to another endpoint",
    "ANTHROPIC_AUTH_TOKEN": "replaces the Anthropic API key with a bearer token for another gateway",
    "OPENAI_BASE_URL": "redirects every OpenAI SDK call to another endpoint",
}
ARCHIVE_MARKER = "ARCHIVED_PILOT.json"


class PreflightRefused(RuntimeError):
    """The pipeline must not start in this environment."""


def endpoint_problems(env: dict | None = None) -> list[str]:
    env = os.environ if env is None else env
    return [f"{name} is set ({why})" for name, why in REDIRECTING_ENV.items() if (env.get(name) or "").strip()]


def require_clean_endpoints(env: dict | None = None) -> None:
    problems = endpoint_problems(env)
    if problems:
        raise PreflightRefused(
            "The pipeline will not start: " + "; ".join(problems) + ". These variables are how Claude Code is "
            "pointed at another vendor (for example Kimi); with them set, calls logged as Anthropic or OpenAI "
            "would be served and billed elsewhere. Open a new shell without them, or clear them:\n"
            "  PowerShell:  Remove-Item Env:ANTHROPIC_BASE_URL, Env:ANTHROPIC_AUTH_TOKEN, Env:OPENAI_BASE_URL "
            "-ErrorAction SilentlyContinue\n"
            "  bash:        unset ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN OPENAI_BASE_URL")


def price_problems(models: list[str] | None = None) -> list[str]:
    """Stale or unsourced price entries for the given models (default: every configured agent and alternate)."""
    from .budget import price_problem
    prices = config.load("prices")
    limit = (config.load("pipeline").get("run") or {}).get("price_max_age_days")
    if models is None:
        from .agents.registry import AGENTS
        models = sorted({m.model for a in AGENTS for m in config.agent_candidates(a)})
    return [p for p in (price_problem(prices, m, limit) for m in models) if p]


def archived_root(path: Path) -> Path | None:
    """The archived pilot folder that contains `path`, if any."""
    path = Path(path).resolve()
    for parent in (path, *path.parents):
        if (parent / ARCHIVE_MARKER).is_file():
            return parent
    return None


def require_not_archived(path: Path, what: str = "run") -> None:
    root = archived_root(path)
    if root is not None:
        try:
            note = json.loads((root / ARCHIVE_MARKER).read_text(encoding="utf-8")).get("closeout", "PILOT_CLOSEOUT.md")
        except (OSError, ValueError):
            note = "PILOT_CLOSEOUT.md"
        raise PreflightRefused(
            f"{what} {path} is inside the archived pilot {root}. Archived pilot material is read-only evidence: it "
            f"is never resumed, promoted or used as input automatically (see {note}). To reuse a file from it, "
            "copy it out by hand and record why.")


def require_start(run_dir: Path | None = None) -> None:
    """Everything that must hold before a run may spend: clean endpoints and a run that is not archived."""
    require_clean_endpoints()
    if run_dir is not None:
        require_not_archived(run_dir)
