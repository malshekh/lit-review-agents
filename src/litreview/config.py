"""Load YAML configuration and resolve per-agent model settings."""
from __future__ import annotations

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
        temperature=float(entry.get("temperature", 0.0)),
        effort=entry.get("effort"),
        cache_system=bool(entry.get("cache_system", False)),
        cache_payload=tuple(entry.get("cache_payload") or ()),
    )


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
                              temperature=primary.temperature, effort=alt.get("effort", primary.effort),
                              cache_system=primary.cache_system, cache_payload=primary.cache_payload))
    return out
