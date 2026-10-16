import pytest

from litreview import budget as budget_mod
from litreview.budget import BudgetExceeded, BudgetTracker, UnpricedModel


def _tracker(tmp_path, monkeypatch, cap=1.0, prices=None):
    def fake_load(name):
        if name == "pipeline":
            return {"run": {"spend_cap_usd": cap, "warn_at_fraction": 0.8, "allow_unpriced_models": False}}
        return prices or {"m": {"input": 3.0, "output": 15.0}}
    monkeypatch.setattr(budget_mod.config, "load", fake_load)
    return BudgetTracker(tmp_path)


def test_cost_and_cap(tmp_path, monkeypatch):
    t = _tracker(tmp_path, monkeypatch, cap=0.02)
    e = t.record("A02-SP", "anthropic", "m", 1000, 1000)
    assert e["cost_usd"] == pytest.approx(0.018)
    t.ensure_headroom()
    t.record("A02-SP", "anthropic", "m", 1000, 1000)
    with pytest.raises(BudgetExceeded):
        t.ensure_headroom()


def test_unpriced_model_refused(tmp_path, monkeypatch):
    t = _tracker(tmp_path, monkeypatch, prices={"m": {"input": None, "output": None}})
    with pytest.raises(UnpricedModel):
        t.check_priced("m")


def test_summary_by_agent(tmp_path, monkeypatch):
    t = _tracker(tmp_path, monkeypatch)
    t.record("A05-KE", "anthropic", "m", 2000, 500)
    t.record("A05-KE", "anthropic", "m", 2000, 500)
    s = t.summary()
    assert s["by_agent"]["A05-KE"]["calls"] == 2
