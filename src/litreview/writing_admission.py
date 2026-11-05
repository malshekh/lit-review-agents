"""Actual-request cold-cache quotes; no network, forecast envelope or credential access."""
from decimal import Decimal
from .admission import output_reserve, AdmissionRefused
from .synthesis_registry import offline_tokens


def worst_case_usd(budget, model, input_tokens, output_tokens):
    """Cold worst case: every input token at the cache-WRITE rate, every output token at the output rate.
    Anthropic: the 1-hour write (2x input). OpenAI and others: the cache-write rate (GPT-6.1: $2.50 vs $2.00
    input; long-context tier by input size), which prices.yaml defaults to `input` when a model has none.
    Pricing input at the plain rate would under-reserve any call whose prefix is written to the cache."""
    if model.provider == "anthropic":
        return budget.cost(model.model, 0, output_tokens, 0, 0, input_tokens)
    return budget.cost(model.model, 0, output_tokens, 0, input_tokens)


def quote_call(system, message, model, cfg, budget):
    inp = offline_tokens(system) + offline_tokens(message)
    out = output_reserve(model, cfg)  # Anthropic thinking already shares max_tokens.
    cost = worst_case_usd(budget, model, inp, out)
    if cost is None:
        raise AdmissionRefused("Unpriced writing request")
    return float(Decimal(str(cost)) * Decimal("1.30"))


def require_hold(budget, key, required):
    held = budget.reservations().get(key)
    if not held or Decimal(str(held['usd'])) + Decimal('0.000001') < Decimal(str(required)):
        raise AdmissionRefused("Actual writing request exceeds its margin-inclusive reservation; reproject before send")
