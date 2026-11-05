import json
from copy import deepcopy

import pytest

from litreview.budget import BudgetTracker
from litreview.r0001_evaluation_driver import EvaluationDriver, EvaluationStopped

# Do not use the suite's default monkeypatch disabling native financial guards.
pytestmark = pytest.mark.projection_guard


class Adapter:
    def __init__(self, budget):
        self.budget = budget
        self.quote = 1
        self.actual = .2
        self.calls = 0
        self.cp3 = False
        self.approved = True
        self.valid = True
        self.fail = False
        self.receipt = True
        self.review = False
        self.complete = True

    def require(self, stage, binding):
        if not self.approved:
            raise EvaluationStopped("Not authorized")

    def require_cp3_and_manuscript_authorization(self, binding):
        if not self.cp3:
            raise EvaluationStopped("CP3 and manuscript authorization missing")

    def require_r0001_only(self, request, binding):
        if request.get("record_ids") != ["R0001"]:
            raise EvaluationStopped("Wrong corpus")

    def worst_case_usd(self, agent, request):
        return self.quote

    def require_spending_review(self, binding):
        if not self.review:
            raise EvaluationStopped("Spending review required")

    def require_native_future_projection(self, *args):
        pass

    def invoke_native(self, agent, request, step, key):
        self.calls += 1
        if self.fail:
            raise OSError("Unknown provider outcome")
        if self.receipt:
            with self.budget.log_path.open("a") as f:
                f.write(json.dumps({"reservation_key": key, "cost_usd": self.actual}) + "\n")
        return {"accepted": True}

    def validate_output(self, agent, output):
        if not self.valid:
            raise EvaluationStopped("Invalid output")

    def require_complete(self, *args):
        if not self.complete:
            raise EvaluationStopped("Incomplete scientific coverage")


@pytest.fixture
def ctx(tmp_path):
    budget = BudgetTracker.__new__(BudgetTracker)
    budget.cap = 35
    budget.log_path = tmp_path / "costs.jsonl"
    budget.reservations_path = tmp_path / "reservations.json"
    budget.log_path.write_text(json.dumps({"cost_usd": 7.3163356}) + "\n")
    binding = {k: "a" * 64 for k in ("runtime_manifest_sha256", "source_sha256",
               "extraction_sha256", "validation_sha256", "adjudication_sha256",
               "scope_sha256", "cost_authority_sha256")}
    binding.update(evaluation_id="single-paper-demo-v1", record_ids=["R0001"], pmids=["34638842"], parent_run_id="20261031-213324")
    adapter = Adapter(budget)
    driver = EvaluationDriver(tmp_path / "evaluation", budget, binding, adapter)
    return driver, adapter, budget, binding


def call(driver, step="plan"):
    return driver.call(driver.current_stage(), step, {"record_ids": ["R0001"]})


def test_resume_reuses_accepted_and_preserves_parent_spend(ctx):
    d, a, b, binding = ctx
    out = call(d)
    resumed = EvaluationDriver(d.directory, b, binding, a)
    assert call(resumed) == out and a.calls == 1
    assert b.spent() == pytest.approx(7.5163356)
    assert b.reserved() == 0


@pytest.mark.parametrize("agent", ["A05-KE", "A06-SV", "A08-OL", "A10-RV"])
def test_other_agents_and_stages_denied(ctx, agent):
    d, a, *_ = ctx
    with pytest.raises(EvaluationStopped):
        d.call(agent, "wrong", {"record_ids": ["R0001"]})
    assert a.calls == 0


def test_extra_paper_denied(ctx):
    d, a, *_ = ctx
    with pytest.raises(EvaluationStopped):
        d.call("A07-SYN", "bad", {"record_ids": ["R0001", "R0002"]})
    assert a.calls == 0


@pytest.mark.parametrize("quote", [12, float("nan"), float("inf"), -1, True])
def test_subcap_margin_and_invalid_quotes_deny_before_call(ctx, quote):
    d, a, b, _ = ctx
    a.quote = quote
    with pytest.raises(EvaluationStopped):
        call(d)
    assert a.calls == 0 and b.reserved() == 0


def test_parent_cap_counts_other_reservations(ctx):
    d, a, b, _ = ctx
    b.reserve("other", 27, "other")
    with pytest.raises(EvaluationStopped, match="cumulative"):
        call(d)
    assert a.calls == 0


def test_25_dollar_review_gate(ctx):
    d, a, b, _ = ctx
    with b.log_path.open("a") as f:
        f.write(json.dumps({"cost_usd": 17}) + "\n")
    with pytest.raises(EvaluationStopped, match="Spending review"):
        call(d)
    assert a.calls == 0


def test_failure_keeps_hold_blocks_retries_and_other_steps(ctx):
    d, a, b, _ = ctx
    a.fail = True
    with pytest.raises(OSError):
        call(d)
    assert b.reserved() == 1
    for step in ["plan", "another"]:
        with pytest.raises(EvaluationStopped):
            call(d, step)
    assert a.calls == 1


@pytest.mark.parametrize("issue", ["invalid", "missing_receipt", "over_bound"])
def test_rejected_responses_never_accepted(ctx, issue):
    d, a, *_ = ctx
    if issue == "invalid": a.valid = False
    if issue == "missing_receipt": a.receipt = False
    if issue == "over_bound": a.actual = 2
    with pytest.raises(EvaluationStopped):
        call(d)
    with pytest.raises(EvaluationStopped):
        call(d)
    assert a.calls == 1 and d._state()["calls"]
    assert all(c["status"] == "INTENT" for c in d._state()["calls"].values())


def test_new_runtime_requires_new_identity(ctx):
    d, a, b, binding = ctx
    changed = deepcopy(binding)
    changed["source_sha256"] = "b" * 64
    with pytest.raises(EvaluationStopped, match="Changed scope"):
        EvaluationDriver(d.directory, b, changed, a)


def test_cp3_required_after_synthesis(ctx):
    d, a, *_ = ctx
    call(d)
    assert d.finish_stage({"complete": True}) == "A08-OL"
    with pytest.raises(EvaluationStopped, match="CP3"):
        call(d)
    assert a.calls == 1


def test_one_cycle_only_and_no_post_edit_verified_claim(ctx):
    d, a, *_ = ctx
    a.cp3 = True
    for stage in ("A07-SYN", "A08-OL", "A09-WRI", "A10-RV", "A11-RC", "A12-EDI"):
        assert d.current_stage() == stage
        call(d, stage)
        d.finish_stage({"complete": True})
    assert d.current_stage() == "STOPPED_AFTER_A12"
    assert d._state()["post_edit_verified"] is False
    with pytest.raises(EvaluationStopped):
        d.call("A10-RV", "repeat", {"record_ids": ["R0001"]})
    assert a.calls == 6


def test_incomplete_stage_does_not_advance(ctx):
    d, a, *_ = ctx
    call(d)
    a.complete = False
    with pytest.raises(EvaluationStopped):
        d.finish_stage({})
    assert d.current_stage() == "A07-SYN"


def test_adjudication_and_financial_gate_before_dispatch(ctx):
    d, a, *_ = ctx
    a.approved = False
    with pytest.raises(EvaluationStopped):
        call(d)
    assert a.calls == 0


def test_cannot_complete_stage_without_accepted_outputs(ctx):
    d, *_ = ctx
    with pytest.raises(EvaluationStopped):
        d.finish_stage({"complete": True})


def test_accepted_output_tamper_and_changed_request_rejected(ctx):
    d, *_ = ctx
    call(d)
    with pytest.raises(EvaluationStopped, match="Changed request"):
        d.call("A07-SYN", "plan", {"record_ids": ["R0001"], "changed": 1})
    state = d._state()
    next(iter(state["calls"].values()))["output"] = {"forged": True}
    d.path.write_text(json.dumps(state))
    with pytest.raises(EvaluationStopped, match="integrity"):
        call(d)


def test_new_runtime_cannot_reset_evaluation_subcap(ctx):
    d, a, b, binding = ctx
    key = d.prefix + "previous-version"
    with b.log_path.open("a") as f:
        f.write(json.dumps({"cost_usd": 14, "reservation_key": key}) + "\n")
    changed = deepcopy(binding)
    changed["runtime_manifest_sha256"] = "c" * 64
    next_version = EvaluationDriver(d.directory.parent / "next-version", b, changed, a)
    with pytest.raises(EvaluationStopped, match="evaluation admission"):
        call(next_version)
    assert a.calls == 0


def test_native_future_projection_refusal_prevents_reservation(ctx):
    d, a, b, _ = ctx
    def refuse(*args):
        raise EvaluationStopped("Native projection stale")
    a.require_native_future_projection = refuse
    with pytest.raises(EvaluationStopped, match="Native projection"):
        call(d)
    assert not d._state()["calls"] and not b.reservations() and a.calls == 0
