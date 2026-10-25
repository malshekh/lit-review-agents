from types import SimpleNamespace as NS

import pytest

from litreview.agents import base as agent_base
from litreview.llm import anthropic_client as ac
from litreview.llm.base import LLMResponse


def _resp(stop, text="", iterations=None, category=None):
    return NS(content=[NS(type="thinking", thinking="")] + ([NS(type="text", text=text)] if text else []),
              stop_reason=stop, stop_details=NS(category=category) if category else None,
              usage=NS(input_tokens=999, output_tokens=999, iterations=iterations))


def test_fallback_request_and_per_model_usage(monkeypatch):
    sent = {}

    def create(**kw):
        sent.update(kw)
        return _resp("end_turn", '{"ok": true}', iterations=[
            NS(type="message", model=None, input_tokens=6000, output_tokens=1000),
            NS(type="fallback_message", model="claude-opus-5", input_tokens=6000, output_tokens=2000)])
    monkeypatch.setattr(ac, "_get_client", lambda: NS(beta=NS(messages=NS(create=create))))
    r = ac.complete(system="s", user="u", model="claude-opus-5-5", max_tokens=100, temperature=0)
    assert sent["fallbacks"] == "default" and sent["betas"] == [ac.FALLBACK_BETA] and "temperature" not in sent
    assert r.model == "claude-opus-5" and r.text == '{"ok": true}'
    assert r.usage_parts == [("claude-opus-5-5", 6000, 1000), ("claude-opus-5", 6000, 2000)]


def test_refusal_category_is_reported(monkeypatch):
    monkeypatch.setattr(ac, "_get_client", lambda: NS(beta=NS(messages=NS(
        create=lambda **kw: _resp("refusal", category="bio")))))
    r = ac.complete(system="s", user="u", model="claude-opus-5-5", max_tokens=100, temperature=0)
    assert r.stop_reason == "refusal" and r.refusal_category == "bio" and r.text == ""
    assert r.usage_parts == [("claude-opus-5-5", 999, 999)]


def test_refusal_fails_fast_without_json_retry(monkeypatch, tmp_path):
    calls = []

    def fake_complete(provider, **kw):
        calls.append(1)
        return LLMResponse("", "anthropic", "claude-opus-5-5", 10, 10, "refusal", "bio",
                           [("claude-opus-5-5", 10, 10)])
    monkeypatch.setattr(agent_base, "complete", fake_complete)
    from litreview.budget import BudgetTracker
    from litreview.provenance import ProvenanceLog
    with pytest.raises(agent_base.AgentError, match="category: bio"):
        agent_base.run_agent("A02-SP", {"x": 1}, tmp_path, "s1", BudgetTracker(tmp_path), ProvenanceLog(tmp_path))
    assert len(calls) == 1
