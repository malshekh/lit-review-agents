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

    def cost(self, model: str, input_tokens: int, output_tokens: int,
             cached_input_tokens: int = 0, cache_write_tokens: int = 0) -> float | None:
        """input_tokens: uncached input only. Cached reads bill at `cached_input` and cache writes at
        `cache_write`; a missing rate falls back to `input`, so a cost is never undercounted."""
        p = self.price_of(model)
        if p is None:
            return None
        tier = self.prices.get(model) or {}
        threshold = tier.get("long_context_threshold")
        prompt = input_tokens + cached_input_tokens + cache_write_tokens
        if threshold and prompt > threshold and tier.get("long_input") is not None:
            p = (float(tier["long_input"]), float(tier["long_output"]))
        read = float(tier.get("cached_input", p[0]))
        write = float(tier.get("cache_write", p[0]))
        return (input_tokens * p[0] + output_tokens * p[1]
                + cached_input_tokens * read + cache_write_tokens * write) / 1_000_000

    def missing_cache_rates(self, model: str) -> list[str]:
        tier = self.prices.get(model) or {}
        return [k for k in ("cached_input", "cache_write") if tier.get(k) is None]

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
               cache_write_tokens: int = 0) -> dict:
        entry = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "agent": agent_id,
            "step": step,
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "cache_write_tokens": cache_write_tokens,
            "output_tokens": output_tokens,
            "cost_usd": self.cost(model, input_tokens, output_tokens, cached_input_tokens, cache_write_tokens),
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
                                                         "cost_usd": 0.0})
        unpriced = 0
        for e in self.entries():
            a = by_agent[e["agent"]]
            a["calls"] += 1
            a["input_tokens"] += e["input_tokens"]
            a["cached_input_tokens"] += e.get("cached_input_tokens", 0)
            a["cache_write_tokens"] += e.get("cache_write_tokens", 0)
            a["output_tokens"] += e["output_tokens"]
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
            cache = (f"  ({a['cached_input_tokens']:,d} cached, {a['cache_write_tokens']:,d} written)"
                     if a["cached_input_tokens"] or a["cache_write_tokens"] else "")
            lines.append(f"  {agent:8s} {a['calls']:4d} calls  {a['input_tokens']:>9,d} in  "
                         f"{a['output_tokens']:>8,d} out  ${a['cost_usd']:.2f}{cache}")
        if s["unpriced_calls"]:
            lines.append(f"  WARNING: {s['unpriced_calls']} calls had no price and are not counted.")
        return "\n".join(lines)
