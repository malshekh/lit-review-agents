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

    def cost_parts(self, model: str, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0,
                   cache_write_tokens: int = 0, cache_write_1h_tokens: int = 0) -> dict[str, float] | None:
        """USD per token class: ordinary input, cache writes (5-minute and 1-hour), cache reads, output.
        input_tokens: uncached input only. cache_write_tokens: 5-minute writes; cache_write_1h_tokens:
        1-hour writes (counted separately, not included in cache_write_tokens)."""
        r = self._rates(model, input_tokens + cached_input_tokens + cache_write_tokens + cache_write_1h_tokens)
        if r is None:
            return None
        return {"input": input_tokens * r["input"] / 1e6,
                "cache_write": (cache_write_tokens * r["cache_write"] + cache_write_1h_tokens * r["cache_write_1h"]) / 1e6,
                "cache_read": cached_input_tokens * r["cached_input"] / 1e6,
                "output": output_tokens * r["output"] / 1e6}

    def cost(self, model: str, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0,
             cache_write_tokens: int = 0, cache_write_1h_tokens: int = 0) -> float | None:
        parts = self.cost_parts(model, input_tokens, output_tokens, cached_input_tokens, cache_write_tokens,
                                cache_write_1h_tokens)
        return None if parts is None else sum(parts.values())

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
               started_at: float | None = None, cache_requested: bool = False) -> dict:
        """cache_requested: the request carried cache_control marks. A requested cache that neither read
        nor wrote (a prefix changed by a byte, or below the provider's minimum) is logged as a miss."""
        since = self._seconds_since_previous(agent_id, model, started_at)
        parts = self.cost_parts(model, input_tokens, output_tokens, cached_input_tokens, cache_write_tokens,
                                cache_write_1h_tokens)
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
            "cost_usd": None if parts is None else sum(parts.values()),
            "cost_parts_usd": None if parts is None else {k: round(v, 6) for k, v in parts.items()},
        }
        wrote = bool(cache_write_tokens or cache_write_1h_tokens)
        if cache_requested or cached_input_tokens or wrote:
            prompt = input_tokens + cached_input_tokens + cache_write_tokens + cache_write_1h_tokens
            input_cost = None if parts is None else parts["input"] + parts["cache_write"] + parts["cache_read"]
            entry["cache"] = {
                "requested": cache_requested,
                "hit": cached_input_tokens > 0,
                "wrote": wrote,   # requested, no hit and no write: the cache did nothing (silent failure)
                "seconds_since_previous_start": since,   # same agent and model, start to start
                "effective_input_rate_per_m": (round(input_cost / prompt * 1e6, 4)
                                               if input_cost is not None and prompt else None),
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
        """`cost_parts_usd` sums the per-entry split; calls logged before the split existed (2026-10-27)
        carry only a total and are counted in `calls_without_cost_parts` instead of being re-priced."""
        def parts() -> dict:
            return {"input": 0.0, "cache_write": 0.0, "cache_read": 0.0, "output": 0.0}
        by_agent: dict[str, dict] = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "cached_input_tokens": 0,
                                                         "cache_write_tokens": 0, "output_tokens": 0,
                                                         "cost_usd": 0.0, "cost_parts_usd": parts(),
                                                         "calls_without_cost_parts": 0, "cache_calls": 0,
                                                         "cache_hits": 0, "cache_no_effect": 0})
        total = parts()
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
                a["cache_no_effect"] += e["cache"].get("requested", False) and not e["cache"]["hit"] \
                    and not e["cache"].get("wrote", True)
            if e["cost_usd"] is None:
                unpriced += 1
            else:
                a["cost_usd"] += e["cost_usd"]
            if e.get("cost_parts_usd"):
                for k, v in e["cost_parts_usd"].items():
                    a["cost_parts_usd"][k] += v
                    total[k] += v
            elif e["cost_usd"] is not None:
                a["calls_without_cost_parts"] += 1
        return {"cap_usd": self.cap, "spent_usd": round(self.spent(), 4),
                "cost_parts_usd": {k: round(v, 4) for k, v in total.items()},
                "calls_without_cost_parts": sum(a["calls_without_cost_parts"] for a in by_agent.values()),
                "unpriced_calls": unpriced, "by_agent": dict(by_agent)}

    def summary_text(self) -> str:
        s = self.summary()
        def split(p: dict) -> str:
            return (f"input ${p['input']:.2f}, cache write ${p['cache_write']:.2f}, "
                    f"cache read ${p['cache_read']:.2f}, output ${p['output']:.2f}")
        lines = [f"Spent ${s['spent_usd']:.2f} of ${s['cap_usd']:.2f} cap"]
        if any(s["cost_parts_usd"].values()):
            lines.append(f"  split: {split(s['cost_parts_usd'])}"
                         + (f"  (+{s['calls_without_cost_parts']} earlier calls logged as totals only)"
                            if s["calls_without_cost_parts"] else ""))
        for agent, a in sorted(s["by_agent"].items()):
            cache = (f"  (cache: {a['cache_hits']}/{a['cache_calls']} calls hit, {a['cached_input_tokens']:,d} "
                     f"tokens read, {a['cache_write_tokens']:,d} written"
                     + (f"; {a['cache_no_effect']} requested but neither read nor wrote" if a["cache_no_effect"] else "")
                     + ")" if a["cache_calls"] else "")
            parts = f"  [{split(a['cost_parts_usd'])}]" if any(a["cost_parts_usd"].values()) else ""
            lines.append(f"  {agent:8s} {a['calls']:4d} calls  {a['input_tokens']:>9,d} in  "
                         f"{a['output_tokens']:>8,d} out  ${a['cost_usd']:.2f}{parts}{cache}")
        if s["unpriced_calls"]:
            lines.append(f"  WARNING: {s['unpriced_calls']} calls had no price and are not counted.")
        return "\n".join(lines)
