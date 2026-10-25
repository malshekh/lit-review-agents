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
    )
