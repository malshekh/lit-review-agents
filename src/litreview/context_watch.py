"""Context utilisation per call: (input + reserved output) / the model's context window.

Measured before every model call (interactive and batch) and logged to provenance, with both figures:
  * the byte bound of the exact serialized request (admission.input_bound: never below the token count), and
  * the provider's own count of the same request where one is available (Anthropic's free messages.count_tokens,
    pipeline.yaml -> context_utilisation.provider_count). The provider count decides the level when present; the
    byte bound decides it otherwise, which is conservative (it overstates tokens about twofold).
After the call, the provider-reported input tokens give the actual utilisation, logged for calibration.

Levels against per-model thresholds (pipeline.yaml -> context_utilisation): OK; WARN (warn threshold, default
0.80): logged and notified, the call proceeds; REVIEW (review threshold, default 0.90): the run stops for the
researcher's approval of this exact request (CP_CONTEXT, recorded in provenance). The thresholds are OPERATIONAL
DEFAULTS, not reliability guarantees: quality near a window's end is not measured here. The hard admission
ceiling (admission.py, A08-A12; A07 and A10 job ceilings) is unchanged and still refuses anything over it.
A model with no recorded window is logged as WINDOW_UNKNOWN: no ratio can be computed, nothing is inferred.
"""
from __future__ import annotations

from .admission import input_bound

LABEL = "OPERATIONAL_DEFAULT (not a reliability guarantee)"


def thresholds(model_name: str, cfg: dict) -> dict:
    cu = cfg.get("context_utilisation") or {}
    base = {"warn": 0.80, "review": 0.90, **(cu.get("default") or {})}
    out = {**base, **((cu.get("models") or {}).get(model_name) or {})}
    if not 0 < float(out["warn"]) < float(out["review"]) <= 1:
        raise ValueError(f"context_utilisation thresholds for {model_name}: need 0 < warn < review <= 1, got {out}")
    return {"warn": float(out["warn"]), "review": float(out["review"]), "label": LABEL}


def output_reserve(model, adm_cfg: dict) -> tuple[int, str]:
    """max_tokens plus the provider's configured reasoning reserve (admission.reasoning_reserve_tokens)."""
    extra = (adm_cfg.get("reasoning_reserve_tokens") or {}).get(model.provider)
    if extra is None:
        return int(model.max_tokens), "max_tokens (no reasoning reserve configured for this provider)"
    return int(model.max_tokens) + int(extra), "max_tokens + reasoning_reserve_tokens"


def level(utilisation: float | None, th: dict) -> str:
    if utilisation is None:
        return "WINDOW_UNKNOWN"
    return "REVIEW" if utilisation >= th["review"] else "WARN" if utilisation >= th["warn"] else "OK"


def measure(agent_id: str, step: str, system: str, user: list[dict], payload: dict, model, cfg: dict,
            counter=None) -> dict:
    """The utilisation record for one request. counter(system, user, model) -> provider input tokens, or None;
    a counter error is recorded and the byte bound is used."""
    adm = cfg.get("admission") or {}
    bound = input_bound(system, payload)
    reserve, reserve_basis = output_reserve(model, adm)
    window = (adm.get("context_windows") or {}).get(model.model)
    counted, count_error = None, None
    if counter is not None:
        try:
            counted = counter(system, user, model)
        except Exception as exc:  # noqa: BLE001 - a failed free count never blocks a call; the bound is used
            count_error = f"{type(exc).__name__}: {str(exc)[:200]}"
    th = thresholds(model.model, cfg)
    u_bound = (bound + reserve) / window if window else None
    u_count = (counted + reserve) / window if window and counted is not None else None
    u = u_count if u_count is not None else u_bound
    return {"agent": agent_id, "step": step, "model": model.model, "provider": model.provider,
            "window": window, "output_reserve": reserve, "output_reserve_basis": reserve_basis,
            "input_byte_bound": bound, "input_counted": counted, "count_error": count_error,
            "utilisation_byte_bound": None if u_bound is None else round(u_bound, 4),
            "utilisation_counted": None if u_count is None else round(u_count, 4),
            "utilisation": None if u is None else round(u, 4),
            "basis": "PROVIDER_COUNT" if u_count is not None else "BYTE_BOUND" if u_bound is not None else "NONE",
            "level": level(u, th), "thresholds": th}


def actual(record: dict, entry: dict | None) -> dict | None:
    """Utilisation from the provider-reported usage of the completed call (input incl. cache reads and writes)."""
    if not entry or not record.get("window"):
        return None
    tokens = sum(int(entry.get(k) or 0) for k in ("input_tokens", "cached_input_tokens", "cache_write_tokens",
                                                   "cache_write_1h_tokens"))
    return {"step": record["step"], "model": record["model"], "input_tokens_actual": tokens,
            "utilisation_actual": round((tokens + record["output_reserve"]) / record["window"], 4),
            "byte_bound_over_actual": round(record["input_byte_bound"] / tokens, 3) if tokens else None,
            "counted_over_actual": round(record["input_counted"] / tokens, 3)
            if tokens and record.get("input_counted") else None}


def anthropic_counter(system: str, user: list[dict], model) -> int | None:
    """Anthropic's free input-token count for the exact request (same body as the call)."""
    if model.provider != "anthropic":
        return None
    from .llm.anthropic_client import count_tokens
    return int(count_tokens(system, user, model.model, model.cache_system, model.cache_ttl))
