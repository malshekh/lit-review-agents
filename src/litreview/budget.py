"""Budget monitor: logs every model call and enforces the per-run spend cap.

Each call is appended to runs/<run_id>/costs.jsonl. Costs are computed from the
token counts the APIs return and the per-million-token prices in config/prices.yaml.
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

from . import config


class BudgetExceeded(RuntimeError):
    pass


class BatchGateRefused(BudgetExceeded):
    """The runtime gate (batch.gate_usd) stopped a batch before submission: spent + committed + projected +
    the batch's worst case would exceed it. The stage stops; it does not wait for room."""


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
        self.reservations_path = Path(run_dir) / "reservations.json"
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

    def _rates(self, model: str, prompt_tokens: int, batch: bool = False) -> dict | None:
        """Per-million rates for one call. A missing cache rate never undercounts: reads and 5-minute
        writes fall back to `input`, 1-hour writes (2x input on Anthropic) to `output`. A batched call uses
        the `<model>-batch` entry when there is one (else the standard rates, an overstatement); the
        long-context tier applies within whichever table is used, so batching halves the cliff, not removes it."""
        if batch and self.price_of(f"{model}-batch") is not None:
            model = f"{model}-batch"
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
                   cache_write_tokens: int = 0, cache_write_1h_tokens: int = 0,
                   batch: bool = False) -> dict[str, float] | None:
        """USD per token class: ordinary input, cache writes (5-minute and 1-hour), cache reads, output.
        input_tokens: uncached input only. cache_write_tokens: 5-minute writes; cache_write_1h_tokens:
        1-hour writes (counted separately, not included in cache_write_tokens)."""
        r = self._rates(model, input_tokens + cached_input_tokens + cache_write_tokens + cache_write_1h_tokens, batch)
        if r is None:
            return None
        return {"input": input_tokens * r["input"] / 1e6,
                "cache_write": (cache_write_tokens * r["cache_write"] + cache_write_1h_tokens * r["cache_write_1h"]) / 1e6,
                "cache_read": cached_input_tokens * r["cached_input"] / 1e6,
                "output": output_tokens * r["output"] / 1e6}

    def cost(self, model: str, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0,
             cache_write_tokens: int = 0, cache_write_1h_tokens: int = 0, batch: bool = False) -> float | None:
        parts = self.cost_parts(model, input_tokens, output_tokens, cached_input_tokens, cache_write_tokens,
                                cache_write_1h_tokens, batch)
        return None if parts is None else sum(parts.values())

    def alternate_cost_multiple(self, agent_id: str, primary: str, alternate: str) -> dict | None:
        """How much more the agent's work would cost on `alternate` than on `primary`. Priced from this run's
        calls by the agent on the primary (each call re-priced at both models' rates, so tiers apply per call);
        with no such calls, the largest ratio between the two models' rates, an upper bound. None if either
        model is unpriced."""
        if self.price_of(primary) is None or self.price_of(alternate) is None:
            return None
        keys = ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens", "cache_write_1h_tokens")
        rows = [e for e in self.entries() if e["agent"] == agent_id and e["model"] == primary]
        if rows:
            a = sum(self.cost(primary, *(e.get(k, 0) for k in keys), batch=bool(e.get("batch_id"))) for e in rows)
            b = sum(self.cost(alternate, *(e.get(k, 0) for k in keys), batch=bool(e.get("batch_id"))) for e in rows)
            if a > 0:
                return {"multiple": round(b / a, 2), "basis": f"this run's {len(rows)} {agent_id} calls on {primary}",
                        "per_call_primary_usd": round(a / len(rows), 4), "per_call_alternate_usd": round(b / len(rows), 4)}
        # no history: the larger of the input and output ratios. Cache rates are left out: they are a small
        # share of any call, and a cache-read ratio alone (Kimi 0.20 vs GPT-6.1 0.10) would flag an
        # alternate that costs the same.
        ra, rb = self._rates(primary, 0), self._rates(alternate, 0)
        multiple = max(rb[k] / ra[k] for k in ("input", "output"))
        return {"multiple": round(multiple, 2),
                "basis": "largest rate ratio, input or output (no calls on the primary in this run)",
                "per_call_primary_usd": None, "per_call_alternate_usd": None}

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

    def ensure_headroom(self, reservation_key: str | None = None) -> None:
        """Raise before a call if the cap is already reached, counting spend reserved by unsettled batches."""
        held = self.reserved()
        if reservation_key:
            own = self.reservations().get(reservation_key)
            if own is None:
                raise BudgetExceeded("pre-call reservation missing")
            held -= own["usd"]
        if self.spent() + held >= self.cap:
            raise BudgetExceeded(f"Spend cap ${self.cap:.2f} reached (${self.spent():.2f} spent"
                                 + (f", ${held:.2f} reserved by unsettled batches" if held else "") + ").")

    # --- reservations ----------------------------------------------------
    # A batch commits its whole cost at submission and cannot be stopped, so its worst-case cost is reserved
    # before submission and held until the batch settles. The check and the reservation happen under one
    # lock, so two submissions cannot both pass the same remaining-cap check. A held reservation shrinks
    # as its batch's actual costs are logged (never below zero), so nothing is counted twice.
    @contextmanager
    def _lock(self, timeout: float = 120.0, stale_after: float = 600.0):
        lock = self.log_path.with_name("budget.lock")
        start = time.time()
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except (FileExistsError, PermissionError):   # Windows: PermissionError while the holder deletes it
                try:
                    if time.time() - lock.stat().st_mtime > stale_after:   # left by a crashed holder
                        lock.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.time() - start > timeout:
                    raise BudgetExceeded(f"budget lock {lock} held for over {timeout:.0f}s; nothing reserved")
                time.sleep(0.2)
        try:
            yield
        finally:
            os.close(fd)
            lock.unlink(missing_ok=True)

    def reservations(self) -> dict:
        if not self.reservations_path.exists():
            return {}
        return json.loads(self.reservations_path.read_text(encoding="utf-8"))

    def _write_reservations(self, res: dict) -> None:
        tmp = self.reservations_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(res, indent=1), encoding="utf-8")
        os.replace(tmp, self.reservations_path)

    def reserved(self) -> float:
        """Spend held by unsettled batches: each reservation less the costs its batch has already logged."""
        res = self.reservations()
        if not res:
            return 0.0
        logged: dict[str, float] = defaultdict(float)
        for e in self.entries():
            if e.get("batch_id"):
                logged[e["batch_id"]] += e["cost_usd"] or 0.0
        for e in self.entries():
            if e.get("reservation_key"):logged[e["reservation_key"]] += e["cost_usd"] or 0.0
        return sum(max(0.0, r["usd"] - (logged[r["batch_id"]] if r.get("batch_id") else logged[k])) for k,r in res.items())

    def reserve(self, key: str, usd: float, agent_id: str, note: str = "") -> tuple[bool, float]:
        """Hold `usd` under `key` if it fits under the cap after spend and every other reservation.
        Returns (reserved, what was available before this reservation)."""
        with self._lock():
            available = self.cap - self.spent() - self.reserved()
            if usd > available:
                return False, available
            res = self.reservations()
            res[key] = {"usd": round(usd, 6), "agent": agent_id, "batch_id": None, "note": note,
                        "reserved_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "reserved_epoch": time.time()}
            self._write_reservations(res)
            return True, available

    def attach_reservation(self, key: str, batch_id: str) -> None:
        with self._lock():
            res = self.reservations()
            if key in res:
                res[key]["batch_id"] = batch_id
                self._write_reservations(res)

    def release(self, key: str) -> None:
        with self._lock():
            res = self.reservations()
            if res.pop(key, None) is not None:
                self._write_reservations(res)

    def record(self, agent_id: str, provider: str, model: str, input_tokens: int,
               output_tokens: int, step: str = "", cached_input_tokens: int = 0,
               cache_write_tokens: int = 0, cache_write_1h_tokens: int = 0,
               started_at: float | None = None, cache_requested: bool = False, batch_id: str | None = None,
               prompt_chars: int | None = None, reservation_key: str | None = None) -> dict:
        """cache_requested: the request carried cache_control marks. A requested cache that neither read
        nor wrote (a prefix changed by a byte, or below the provider's minimum) is logged as a miss.
        batch_id: the call ran inside that batch and is billed at batch rates. prompt_chars: characters sent
        (system + user), so a batch's input can be projected from this run's own tokens-per-character ratio."""
        since = self._seconds_since_previous(agent_id, model, started_at) if not batch_id else None
        parts = self.cost_parts(model, input_tokens, output_tokens, cached_input_tokens, cache_write_tokens,
                                cache_write_1h_tokens, batch=bool(batch_id))
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
        if reservation_key:entry["reservation_key"]=reservation_key
        if batch_id:
            entry["batch_id"] = batch_id
        if prompt_chars:
            entry["prompt_chars"] = prompt_chars
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
    _TOKENS = ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens", "cache_write_1h_tokens")

    def savings(self, e: dict) -> dict | None:
        """What caching and batching changed for one logged call, kept apart so each can be judged on its own.
        cache_read_saved: cached tokens x (input rate - cache-read rate). cache_write_premium (5-minute) and
        cache_write_1h_premium: written tokens x (write rate - input rate). All three at the rates of the table
        the call was billed at (batch or standard). batch_discount: the same call, same token mix, at standard
        rates, minus what it cost. None if the model is unpriced."""
        t = [e.get(k, 0) for k in self._TOKENS]
        batched = bool(e.get("batch_id"))
        r = self._rates(e["model"], t[0] + t[2] + t[3] + t[4], batched)
        actual = self.cost(e["model"], *t, batch=batched)
        if r is None or actual is None:
            return None
        return {"cache_read_saved": t[2] * (r["input"] - r["cached_input"]) / 1e6,
                "cache_write_premium": t[3] * (r["cache_write"] - r["input"]) / 1e6,
                "cache_write_1h_premium": t[4] * (r["cache_write_1h"] - r["input"]) / 1e6,
                "batch_discount": (self.cost(e["model"], *t) - actual) if batched else 0.0}

    def summary(self) -> dict:
        """`cost_parts_usd` sums the per-entry split; calls logged before the split existed (2026-10-27)
        carry only a total and are counted in `calls_without_cost_parts` instead of being re-priced."""
        def parts() -> dict:
            return {"input": 0.0, "cache_write": 0.0, "cache_read": 0.0, "output": 0.0}

        def saved() -> dict:
            return {"cache_read_saved": 0.0, "cache_write_premium": 0.0, "cache_write_1h_premium": 0.0,
                    "batch_discount": 0.0}
        by_agent: dict[str, dict] = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "cached_input_tokens": 0,
                                                         "cache_write_tokens": 0, "output_tokens": 0,
                                                         "cost_usd": 0.0, "cost_parts_usd": parts(),
                                                         "calls_without_cost_parts": 0, "cache_calls": 0,
                                                         "cache_hits": 0, "cache_no_effect": 0,
                                                         "batched_calls": 0, "savings_usd": saved()})
        total, total_saved = parts(), saved()
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
            a["batched_calls"] += bool(e.get("batch_id"))
            for k, v in (self.savings(e) or {}).items():
                a["savings_usd"][k] += v
                total_saved[k] += v
        net = total_saved["cache_read_saved"] - total_saved["cache_write_premium"] - total_saved["cache_write_1h_premium"]
        return {"cap_usd": self.cap, "spent_usd": round(self.spent(), 4), "reserved_usd": round(self.reserved(), 4),
                "savings_usd": {**{k: round(v, 4) for k, v in total_saved.items()}, "cache_net": round(net, 4)},
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
        if s["reserved_usd"]:
            lines.append(f"  reserved by unsettled batches: ${s['reserved_usd']:.2f}")
        v = s["savings_usd"]
        if any(v.values()):
            lines.append(f"  cache: reads saved ${v['cache_read_saved']:.2f}; writes cost ${v['cache_write_premium']:.2f} "
                         f"(5-minute) + ${v['cache_write_1h_premium']:.2f} (1-hour) over the input price; net "
                         f"${v['cache_net']:.2f}.  Batch discount, separately: ${v['batch_discount']:.2f}")
        for agent, a in sorted(s["by_agent"].items()):
            cache = (f"  (cache: {a['cache_hits']}/{a['cache_calls']} calls hit, {a['cached_input_tokens']:,d} "
                     f"tokens read, {a['cache_write_tokens']:,d} written"
                     + (f"; {a['cache_no_effect']} requested but neither read nor wrote" if a["cache_no_effect"] else "")
                     + ")" if a["cache_calls"] else "")
            parts = f"  [{split(a['cost_parts_usd'])}]" if any(a["cost_parts_usd"].values()) else ""
            av = a["savings_usd"]
            if a["batched_calls"] or av["cache_read_saved"] or av["cache_write_premium"] or av["cache_write_1h_premium"]:
                net = av["cache_read_saved"] - av["cache_write_premium"] - av["cache_write_1h_premium"]
                parts += (f"  [cache net ${net:.2f}"
                          + (f"; {a['batched_calls']} batched, discount ${av['batch_discount']:.2f}"
                             if a["batched_calls"] else "") + "]")
            lines.append(f"  {agent:8s} {a['calls']:4d} calls  {a['input_tokens']:>9,d} in  "
                         f"{a['output_tokens']:>8,d} out  ${a['cost_usd']:.2f}{parts}{cache}")
        if s["unpriced_calls"]:
            lines.append(f"  WARNING: {s['unpriced_calls']} calls had no price and are not counted.")
        return "\n".join(lines)
