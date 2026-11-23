"""Load YAML configuration and resolve per-agent model settings."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml

from .paths import CONFIG_DIR


@lru_cache(maxsize=None)
def load(name: str) -> dict[str, Any]:
    """Load config/<name>.yaml."""
    with open(CONFIG_DIR / f"{name}.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


STAGE_GROUPS = {"A02-A04": ("A02-SP", "A03-LM", "A04-CQ"), "A05-A06": ("A05-KE", "A06-SV"), "A07": ("A07-SYN",),
                "A08-A09": ("A08-OL", "A09-WRI"), "A10": ("A10-RV",), "A11-A12": ("A11-RC", "A12-EDI")}


def profile_name(recorded: str | None = None) -> str:
    """The active spend profile: the one a run was created under, else LITREVIEW_PROFILE, else run.profile."""
    return recorded or os.environ.get("LITREVIEW_PROFILE") or (load("pipeline").get("run") or {}).get("profile") or "pilot"


def run_settings(recorded: str | None = None) -> dict:
    """run.* merged with the active profile (pipeline.yaml -> profiles). An unknown profile is an error, never a
    silent fall back to another cap. With no `profiles` section the run block is used as it stands."""
    cfg = load("pipeline")
    run = dict(cfg.get("run") or {})
    profiles = cfg.get("profiles")
    if not profiles:
        return run
    name = profile_name(recorded)
    if name not in profiles:
        raise ValueError(f"Unknown spend profile '{name}'. Profiles in config/pipeline.yaml: {', '.join(profiles)}.")
    prof = profiles[name] or {}
    points = [float(x) for x in prof.get("spend_review_points_usd") or []]
    return {**run, **prof, "profile": name, "spend_review_points_usd": points,
            "spend_review_usd": points[0] if points else None}


def stage_group(agent_id: str) -> str | None:
    return next((g for g, agents in STAGE_GROUPS.items() if agent_id in agents), None)


@dataclass(frozen=True)
class AgentModel:
    agent_id: str
    provider: str
    model: str
    max_tokens: int
    temperature: float
    effort: str | None = None   # Claude reasoning effort: low | medium | high | xhigh | max
    cache_system: bool = False  # Claude prompt caching: cache the system prompt (reused across calls)
    cache_payload: tuple[str, ...] = ()   # payload keys sent first and cached (e.g. the paper), for repairs
    cache_ttl: str = "5m"       # Anthropic cache lifetime: 5m (write 1.25x input) or 1h (write 2x input)


def agent_model(agent_id: str) -> AgentModel:
    """Resolve an agent's provider and concrete model ID from pipeline.yaml."""
    cfg = load("pipeline")
    entry = cfg["agents"][agent_id]
    alias = entry["model"]
    model_id = cfg["models"].get(alias, alias)
    if model_id in (None, "", "SET_ME"):
        raise ValueError(
            f"{agent_id}: model alias '{alias}' is not set in config/pipeline.yaml (models section)."
        )
    return AgentModel(
        agent_id=agent_id,
        provider=entry["provider"],
        model=model_id,
        max_tokens=int(entry.get("max_tokens", 8000)),
        temperature=float(entry.get("temperature", 0.0)),   # provenance only: no request carries it
        effort=entry.get("effort"),
        cache_system=bool(entry.get("cache_system", False)),
        cache_payload=tuple(entry.get("cache_payload") or ()),
        cache_ttl=str(entry.get("cache_ttl", "5m")),
    )


def level_cap(agent_id: str, payload: dict | None, default: int) -> int:
    """The output cap for one request of an agent that sizes its cap by content level (A05: a full-text paper
    yields far more findings than an abstract). pipeline.yaml -> agents.<id>.max_tokens_by_level."""
    by_level = (load("pipeline")["agents"].get(agent_id) or {}).get("max_tokens_by_level") or {}
    level = (payload or {}).get("content_level")
    return int(by_level.get(level, default))


def _effort_for(provider: str, effort: str | None) -> str | None:
    """An alternate on another vendor inherits the agent's effort only if that vendor accepts the value;
    otherwise it takes the vendor's configured default (Kimi has no `medium`)."""
    setting = ((load("pipeline").get("providers") or {}).get(provider) or {}).get("reasoning_effort") or {}
    allowed = setting.get("allowed")
    if not allowed or effort in allowed:
        return effort
    return setting.get("default") or allowed[0]


def agent_candidates(agent_id: str) -> list[AgentModel]:
    """The agent's configured model, then its alternates (pipeline.yaml -> routing.alternates), in order.
    An alternate gives provider and model; other settings come from the agent unless it overrides them."""
    cfg = load("pipeline")
    primary = agent_model(agent_id)
    out = [primary]
    for alt in ((cfg.get("routing") or {}).get("alternates") or {}).get(agent_id) or []:
        out.append(AgentModel(agent_id=agent_id, provider=alt["provider"],
                              model=cfg["models"].get(alt["model"], alt["model"]),
                              max_tokens=int(alt.get("max_tokens", primary.max_tokens)),
                              temperature=primary.temperature,
                              effort=alt.get("effort") or _effort_for(alt["provider"], primary.effort),
                              cache_system=primary.cache_system, cache_payload=primary.cache_payload,
                              cache_ttl=primary.cache_ttl))
    return out
