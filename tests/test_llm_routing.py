import pytest

from litreview import config
from litreview.llm import openai_compatible, router
from litreview.llm.base import LLMResponse


def test_kimi_routes_through_openai_compatible_client(monkeypatch):
    seen = {}

    class FakeCompletions:
        def create(self, **kw):
            seen.update(kw)
            msg = type("M", (), {"content": '{"ok": true}'})
            choice = type("C", (), {"message": msg, "finish_reason": "stop"})
            usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 2})
            return type("R", (), {"choices": [choice], "usage": usage})

    fake = type("Client", (), {"chat": type("Chat", (), {"completions": FakeCompletions()})})
    monkeypatch.setattr(openai_compatible, "_get_client", lambda provider: fake)
    r = router.complete("kimi", system="s", user="u", model="kimi-k3", max_tokens=50, temperature=0.3)
    assert r.provider == "kimi" and r.input_tokens == 10
    assert "temperature" not in seen and seen["response_format"] == {"type": "json_object"}


def test_unknown_provider_rejected():
    with pytest.raises(ValueError):
        router.complete("other", system="s", user="u", model="m", max_tokens=1, temperature=0)


def test_every_agent_resolves_to_a_priced_model():
    prices = config.load("prices")
    for aid in config.load("pipeline")["agents"]:
        m = config.agent_model(aid)
        assert prices[m.model]["input"] is not None, aid
        assert m.provider in config.load("pipeline")["providers"]


def test_every_agent_has_a_priced_alternate():
    prices = config.load("prices")
    for aid in config.load("pipeline")["agents"]:
        alts = config.agent_candidates(aid)[1:]
        assert alts, f"{aid} has no alternate: a refusal would stop the stage"
        for m in alts:
            assert prices[m.model]["input"] is not None, (aid, m.model)
            assert m.provider in config.load("pipeline")["providers"]


def test_auditors_use_a_different_vendor_than_producers():
    """Holds for every candidate, so routing to an alternate never puts an auditor on its producer's vendor."""
    a = {aid: {m.provider for m in config.agent_candidates(aid)} for aid in config.load("pipeline")["agents"]}
    for auditor, producers in (("A06-SV", ["A05-KE"]), ("A10-RV", ["A09-WRI", "A12-EDI"]),
                               ("A11-RC", ["A09-WRI", "A12-EDI"])):
        for p in producers:
            assert not a[auditor] & a[p], (auditor, p, a[auditor] & a[p])


def test_tracing_is_a_no_op_when_disabled(monkeypatch):
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    from litreview.llm import tracing
    r = tracing.traced_call(lambda: LLMResponse("x", "anthropic", "m", 1, 1), name="n", provider="anthropic",
                            model="m", metadata={})
    assert r.text == "x"
