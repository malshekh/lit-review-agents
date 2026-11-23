"""Actual-request cold-cache quotes; no network, forecast envelope or credential access."""
from decimal import Decimal
from .admission import output_reserve, AdmissionRefused
from .synthesis_registry import offline_tokens


def quote_call(system, message, model, cfg, budget):
    inp = offline_tokens(system) + offline_tokens(message)
    out = output_reserve(model, cfg)  # Anthropic thinking already shares max_tokens.
    cost = (budget.cost(model.model, 0, out, 0, 0, inp) if model.provider == "anthropic"
            else budget.cost(model.model, inp, out))
    if cost is None:
        raise AdmissionRefused("Unpriced writing request")
    return float(Decimal(str(cost)) * Decimal("1.30"))


def require_hold(budget, key, required):
    held = budget.reservations().get(key)
    if not held or Decimal(str(held['usd'])) + Decimal('0.000001') < Decimal(str(required)):
        raise AdmissionRefused("Actual writing request exceeds its margin-inclusive reservation; reproject before send")
