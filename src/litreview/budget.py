"""Budget monitor: logs every model call and enforces the per-run spend cap.

Each call is appended to runs/<run_id>/costs.jsonl. Costs are computed from the
token counts the APIs return and the per-million-token prices in config/prices.yaml.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

from . import config


class BudgetExceeded(RuntimeError):
    pass


class UnpricedModel(RuntimeError):
    pass


class BudgetTracker:
    def __init__(self, run_dir: Path):
        pipeline = config.load("pipeline")["run"]
        self.cap = float(pipeline["spend_cap_usd"])
        self.warn_fraction = float(pipeline.get("warn_at_fraction", 0.8))
        self.allow_unpriced = bool(pipeline.get("allow_unpriced_models", False))
        self.prices = config.load("prices")
        self.log_path = Path(run_dir) / "costs.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._warned = False

    # --- pricing -------------------------------------------------------
    def price_of(self, model: str) -> tuple[float, float] | None:
        p = self.prices.get(model) or {}
        if p.get("input") is None or p.get("output") is None:
            return None
        return float(p["input"]), float(p["output"])

    def check_priced(self, model: str) -> None:
        """Call before a model is used, so an unpriced model never runs silently."""
        if self.price_of(model) is None and not self.allow_unpriced:
            raise UnpricedModel(
                f"No price for '{model}' in config/prices.yaml. Add it, or set "
                "run.allow_unpriced_models: true in config/pipeline.yaml."
            )

    def _rates(self, model: str, prompt_tokens: int) -> dict | None:
        """Per-million rates for one call. A missing cache rate never undercounts: reads and 5-minute
        writes fall back to `input`, 1-hour writes (2x input on Anthropic) to `output`."""
        p = self.price_of(model)
        if p is None:
            return None
        tier = self.prices.get(model) or {}
        pre = ""
        threshold = tier.get("long_context_threshold")
        if threshold and prompt_tokens > threshold and tier.get("long_input") is not None:
            pre, p = "long_", (float(tier["long_input"]), float(tier["long_output"]))

        def get(key: str, default: float) -> float:
            return float(tier[pre + key]) if tier.get(pre + key) is not None else default
        return {"input": p[0], "output": p[1], "cached_input": get("cached_input", p[0]),
                "cache_write": get("cache_write", p[0]), "cache_write_1h": get("cache_write_1h", p[1])}

    def cost(self, model: str, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0,
             cache_write_tokens: int = 0, cache_write_1h_tokens: int = 0) -> float | None:
        """input_tokens: uncached input only. cache_write_tokens: 5-minute writes; cache_write_1h_tokens:
        1-hour writes (counted separately, not included in cache_write_tokens)."""
        r = self._rates(model, input_tokens + cached_input_tokens + cache_write_tokens + cache_write_1h_tokens)
        if r is None:
            return None
        return (input_tokens * r["input"] + output_tokens * r["output"] + cached_input_tokens * r["cached_input"]
                + cache_write_tokens * r["cache_write"] + cache_write_1h_tokens * r["cache_write_1h"]) / 1_000_000

    def missing_cache_rates(self, model: str) -> list[str]:
        tier = self.prices.get(model) or {}
        return [k for k in ("cached_input", "cache_write") if tier.get(k) is None]

    def _seconds_since_previous(self, agent_id: str, model: str, started_at: float | None) -> float | None:
        """Start-to-start gap since the previous call by the same agent and model. A cache entry is
        refreshed when a request reads it, so whether it survives depends on the interval between request
        starts (under 5 minutes for the 5-minute cache); only a call to the same provider refreshes it."""
        now = started_at if started_at is not None else time.time()
        for e in reversed(self.entries()):
            if e["agent"] == agent_id and e["model"] == model:
                prev = e.get("started_at")
                if prev is None:
                    try:
                        prev = time.mktime(time.strptime(e["time"], "%Y-%m-%dT%H:%M:%S"))
                    except (KeyError, ValueError):
                        return None
                return round(now - prev, 1)
        return None

    # --- logging and enforcement --------------------------------------
    def entries(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        with open(self.log_path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def spent(self) -> float:
        return sum(e["cost_usd"] or 0.0 for e in self.entries())

    def ensure_headroom(self) -> None:
        """Raise before a call if the cap is already reached."""
        if self.spent() >= self.cap:
            raise BudgetExceeded(f"Spend cap ${self.cap:.2f} reached (${self.spent():.2f} spent).")

    def record(self, agent_id: str, provider: str, model: str, input_tokens: int,
               output_tokens: int, step: str = "", cached_input_tokens: int = 0,
               cache_write_tokens: int = 0, cache_write_1h_tokens: int = 0,
               started_at: float | None = None) -> dict:
        since = self._seconds_since_previous(agent_id, model, started_at)
        entry = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "agent": agent_id,
            "step": step,
            "started_at": round(started_at, 3) if started_at is not None else None,
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "cache_write_tokens": cache_write_tokens,
            "cache_write_1h_tokens": cache_write_1h_tokens,
            "output_tokens": output_tokens,
            "cost_usd": self.cost(model, input_tokens, output_tokens, cached_input_tokens,
                                  cache_write_tokens, cache_write_1h_tokens),
        }
        if cached_input_tokens or cache_write_tokens or cache_write_1h_tokens:
            prompt = input_tokens + cached_input_tokens + cache_write_tokens + cache_write_1h_tokens
            input_cost = self.cost(model, input_tokens, 0, cached_input_tokens, cache_write_tokens,
                                   cache_write_1h_tokens)
            entry["cache"] = {
                "hit": cached_input_tokens > 0,
                "seconds_since_previous_start": since,   # same agent and model, start to start
                "effective_input_rate_per_m": round(input_cost / prompt * 1e6, 4) if input_cost is not None else None,
                "list_input_rate_per_m": (self.price_of(model) or (None,))[0],
            }
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        return entry

    def should_warn(self) -> bool:
        if not self._warned and self.spent() >= self.cap * self.warn_fraction:
            self._warned = True
            return True
        return False

    # --- reporting -----------------------------------------------------
    def summary(self) -> dict:
        by_agent: dict[str, dict] = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "cached_input_tokens": 0,
                                                         "cache_write_tokens": 0, "output_tokens": 0,
                                                         "cost_usd": 0.0, "cache_calls": 0, "cache_hits": 0})
        unpriced = 0
        for e in self.entries():
            a = by_agent[e["agent"]]
            a["calls"] += 1
            a["input_tokens"] += e["input_tokens"]
            a["cached_input_tokens"] += e.get("cached_input_tokens", 0)
            a["cache_write_tokens"] += e.get("cache_write_tokens", 0) + e.get("cache_write_1h_tokens", 0)
            a["output_tokens"] += e["output_tokens"]
            if e.get("cache"):
                a["cache_calls"] += 1
                a["cache_hits"] += bool(e["cache"]["hit"])
            if e["cost_usd"] is None:
                unpriced += 1
            else:
                a["cost_usd"] += e["cost_usd"]
        return {"cap_usd": self.cap, "spent_usd": round(self.spent(), 4),
                "unpriced_calls": unpriced, "by_agent": dict(by_agent)}

    def summary_text(self) -> str:
        s = self.summary()
        lines = [f"Spent ${s['spent_usd']:.2f} of ${s['cap_usd']:.2f} cap"]
        for agent, a in sorted(s["by_agent"].items()):
            cache = (f"  (cache: {a['cache_hits']}/{a['cache_calls']} calls hit, {a['cached_input_tokens']:,d} "
                     f"tokens read, {a['cache_write_tokens']:,d} written)" if a["cache_calls"] else "")
            lines.append(f"  {agent:8s} {a['calls']:4d} calls  {a['input_tokens']:>9,d} in  "
                         f"{a['output_tokens']:>8,d} out  ${a['cost_usd']:.2f}{cache}")
        if s["unpriced_calls"]:
            lines.append(f"  WARNING: {s['unpriced_calls']} calls had no price and are not counted.")
        return "\n".join(lines)
