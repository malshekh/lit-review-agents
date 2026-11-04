# Bounded A06 integration

This branch synchronizes the generally applicable bounded A06 implementation from the separately frozen v8 pilot runtime. The scientific runtime and run data are not distributed here.

A06 PER_PAPER audits use at most 15 findings per call, complete source context and a paper-wide finding index. Output allowance is 64,000 completion tokens. Accepted units have source/input/output fingerprints; only a truncated unit is retried, once. The deterministic merge rejects incomplete coverage, unknown or repeated dispositions and invalid cross-batch references. Normal scientific eligibility, independent-vendor routing, checkpoint review and budget admission remain in force. Provider Batch dispatch delegates oversized papers to the bounded path; small items retain existing behavior.

Integration points: `a06_batches.audit`, `Run.agent`, `Run.run_many`, and `_instability_test`. No run migration, replay receipt, checkpoint or financial approval is supplied by this branch. Promotion into an existing frozen run requires a separately reviewed versioned runtime, current scientific compatibility proof and fresh financial authorization. Do not patch a frozen runtime in place.

The optional forecast increment requires explicit operator-supplied calibration metadata. It is a planning estimate; each actual attempt is admitted against full configured caps. Existing prior spending must be carried exactly once.

Offline bounded regression tests: 16 passed. Mocked outputs establish accounting and enforcement behavior, not scientific correctness of a live model.
