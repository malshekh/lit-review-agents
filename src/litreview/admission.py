"""Request admission for the downstream agents (A08 outline, A09 writing, A11 critique, A12 editing).

Before every call the exact serialized request is bounded, output capacity is reserved, and the bound is checked
against the model's context window. A request that cannot be bounded, or whose model has no configured window,
is refused (fail closed). Nothing here truncates or drops anything: a request that does not fit is subdivided by
the caller along a fixed rule (writing and editing by section) or the stage stops.

The bound is the repository's admission estimator (synthesis_registry.offline_tokens): UTF-8 bytes of the system
prompt and of the user message exactly as `agents.base.user_parts` serializes it, plus framing. A token is never
shorter than one byte, so the bound never undercounts. It typically overstates tokens about threefold, which
makes every window check, threshold check and reservation conservative. No network tokenizer is used.

Output reserve: `max_tokens` of the routed model. Thinking (Anthropic) and reasoning (OpenAI
max_completion_tokens) count within it. Providers for which that is not established get an additional reserve
(pipeline.yaml -> admission.reasoning_reserve_tokens).

Pricing threshold: a model whose price table has `long_context_threshold` (GPT-6.1: 272k input tokens) reprices
the whole request above it. A bound above the threshold is reported as `crosses_threshold`; the orchestrator
then requires the projection to have priced that call at the long-context rates, or re-projection first.
"""
from __future__ import annotations

from .agents.base import build_system_prompt, user_parts
from .synthesis_registry import offline_tokens


class AdmissionRefused(RuntimeError):
    """The request cannot be admitted: it does not fit, cannot be bounded, or the window is unknown."""


def input_bound(system: str, payload: dict) -> int:
    try:
        return offline_tokens(system) + offline_tokens(user_parts(payload))
    except (TypeError, ValueError, OverflowError) as exc:   # not serializable: it cannot be bounded
        raise AdmissionRefused(f"request cannot be serialized and bounded: {exc}") from exc


def output_reserve(model, cfg: dict) -> int:
    extra = (cfg.get("reasoning_reserve_tokens") or {}).get(model.provider)
    if extra is None:
        raise AdmissionRefused(f"no reasoning reserve configured for provider {model.provider}")
    return int(model.max_tokens) + int(extra)


def context_window(model_name: str, cfg: dict) -> int:
    w = (cfg.get("context_windows") or {}).get(model_name)
    if not w:
        raise AdmissionRefused(f"no context window recorded for {model_name} (pipeline.yaml -> admission."
                               "context_windows); admission cannot be checked, so the request is refused")
    return int(w)


def assess(agent_id: str, payload: dict, model, cfg: dict, prices: dict, system: str | None = None) -> dict:
    """The admission record for one request (raises AdmissionRefused only when it cannot be assessed)."""
    system = system if system is not None else build_system_prompt(agent_id)
    inp = input_bound(system, payload)
    out = output_reserve(model, cfg)
    win = context_window(model.model, cfg)
    margin = int(cfg.get("safety_margin_tokens", 0))
    threshold = (prices.get(model.model) or {}).get("long_context_threshold")
    return {"agent": agent_id, "model": model.model, "provider": model.provider, "input_bound": inp,
            "output_reserve": out, "window": win, "safety_margin": margin, "fits": inp + out + margin <= win,
            "long_context_threshold": threshold, "crosses_threshold": bool(threshold and inp > int(threshold)),
            "basis": "UTF-8 byte bound of the exact serialized request (never below the token count)"}
