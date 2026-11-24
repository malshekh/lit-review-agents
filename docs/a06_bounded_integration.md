# Bounded A06 integration

This branch synchronizes the generally applicable bounded A06 implementation from the separately frozen v8 pilot runtime. The scientific runtime and run data are not distributed here.

A06 PER_PAPER audits use at most 15 findings per call, complete source context and a paper-wide finding index. Output allowance is 64,000 completion tokens. Accepted units have source/input/output fingerprints; only a truncated unit is retried, once. The deterministic merge rejects incomplete coverage, unknown or repeated dispositions and invalid cross-batch references. Normal scientific eligibility, independent-vendor routing, checkpoint review and budget admission remain in force. Provider Batch dispatch delegates oversized papers to the bounded path; small items retain existing behavior.

Integration points: `a06_batches.audit`, `Run.agent`, `Run.run_many`, and `_instability_test`. No run migration, replay receipt, checkpoint or financial approval is supplied by this branch. Promotion into an existing frozen run requires a separately reviewed versioned runtime, current scientific compatibility proof and fresh financial authorization. Do not patch a frozen runtime in place.

The optional forecast increment requires explicit operator-supplied calibration metadata. It is a planning estimate; each actual attempt is admitted against full configured caps. Existing prior spending must be carried exactly once.

Offline bounded regression tests: 16 passed. Mocked outputs establish accounting and enforcement behavior, not scientific correctness of a live model.

## Shared-prefix optimization

Development configuration enables `validation.shared_prefix`. The same full authorized source and scientific instructions are retained. `a06_request.shared_prefix` canonicalizes approved scope, source, global finding index, paper/access identity and the fixed A06 output schema once per paper. `agents.base.user_parts` sends the shared block before all variable findings/context and unit metadata. `openai_compatible.chat_params` marks the shared block with an explicit cache boundary and uses current Chat Completions `prompt_cache_options` (30m). Kimi receives ordered text without OpenAI-only parameters. Other agents retain existing requests. OpenAI SDK 3.32+ is required.

Optional OpenAI provider configuration `a06_cache: {mode: off, ttl: 30m}` selects the no-cache control; `mode: explicit` is the default for marked shared-prefix units. `mode: implicit` is available for controlled comparison. Unsupported TTLs/models fail before dispatch. The existing Anthropic path uses its own block-cache mechanism and its own TTL; this patch does not implement Anthropic diagnostics or change routing. Chat Completions request-level 12h retention is deliberately rejected; no endpoint migration is included.

This branch is not the frozen scientific runtime. It intentionally excludes unrelated uncommitted A03/A05 recovery and Task 7 diagnostics. Integration into the working pilot code must preserve those existing repairs, accepted A05 merge-producer proofs and versioned continuation checks. Use the two A06 commits as a focused source diff; do not replace the full integration tree or copy live data into Git. Existing checkpoints and accepted work need explicit compatibility verification under the final promoted version. New prompt/schema/source hashes invalidate old *pending request* identities; do not rerun accepted scientific work to test caching.

Before promotion: resolve integration duplicates against `a06_batches.py`, run the complete suite in the target integration, rebuild a new sanitized runtime, verify it under the actual isolated account, refresh required authorization fingerprints and obtain approval. No such promotion or authorization is performed by this development branch.
