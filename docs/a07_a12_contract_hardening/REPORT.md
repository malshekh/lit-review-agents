# Phase 1 development hardening and v10 sample pricing

Status: DEVELOPMENT ONLY; NOT APPROVED FOR SCIENTIFIC EXECUTION. No paid/free provider requests, live financial holds, scientific ledger writes, checkpoint approvals, runtime promotion, merge or commit.

## Branch and change boundary

Branch: fix/a07-a12-contract-hardening. The starting development tree already contained uncommitted v9/v10 harness, financial, client and configuration work. These changes were preserved; the entire HEAD diff is NOT a task-only patch. No new configuration changes were made for this task. Frozen v10 immutable verification: 6,015 files, zero mismatches. Manifest SHA-256: 9c2cb648d3c38e14b0a90ae68d5237dd96346ef2cfab9d494b040ca7c3c72bc1.

Task changes: active-mode prompt contract appendices and schema-valid illustrative examples; writing_admission.py; margin-inclusive writing holds and actual-request hold checks in orchestrator.py; private full provider-response capture for Anthropic writing calls, outside external tracing; offline tests; self-contained integration simulation loop settings; documentation/pricing. No schema or validator weakened. Full raw provider responses are not stored in this report, tests, patch or Git.

## Contract audit and coverage

See prompt_gap_table.md: 664 schema-rule rows over 17 active/legacy schema files. 'In prompt' means literal presence, not proof of semantic equivalence. Active runtime prompt appendices cover A07 PLAN/GROUP/RECONCILE/FINAL; A08; A09 SECTION/FRONT_MATTER; A10 bounded LOCAL/GLOBAL; A11; A12 whole/unit. Legacy schemas remain audited, not advertised as current execution routes. Schema examples demonstrate shape only, not scientific eligibility or accepted evidence.

Local runtime safeguards remain separate: synthesis_bounded.py _science/group/reconcile/final require eligible anchors, complete per-finding/mandatory accounting and exact global focus review; bridge.py validate_plan requires complete allocation dispositions, unique sections, mandatory/contrary coverage and correct placements; check_section requires packet evidence and continuity; verification_job.py validates occurrence completeness and issues; editor binding gates and version fingerprints remain active. Explicit local limits added to prompt prose: GROUP may list at most 12 propositions, 8 ordinary gaps or 16 source-only gaps and 24 unused findings; lookup requests may name 12 IDs per round, at most two rounds; RECONCILE must review each focus ID exactly once and retrieve anchors for issues; FINAL cannot add evidence or bypass mandatory coverage. A schema-valid fixture is not proof these scientific gates pass on arbitrary content.

## Token caps (unchanged; proposals only)

- synthesis.output_limits.PLAN=32000; plan_request.thinking.type=adaptive; plan_request.effort=medium. Unchanged.
- GROUP=12000; RECONCILE=6000; FINAL=6000. No scientifically justified lower ceiling demonstrated. Other A07 modes inherit high agent effort, not PLAN's medium override.
- A08 agents.A08-OL.max_tokens=32000, proposed 8000. The schema has no token minimum, permits one or more sections and nonnegative word budgets. 8000 is structurally allowed, not demonstrated sufficient for allocation of all future elements.
- A09 default 64000; bridge.output_limits.A09_SECTION=16000, proposed 2500. At high adaptive effort, thinking shares this cap: 2500 is NOT validated as sufficient for 400-500 prose words plus claim bindings and JSON. No lower safe cap can be certified offline.
- A09_FRONT_MATTER=8000, an additional native required call. Retain and price it.
- A10 default 32000, overridden LOCAL=10000 / GLOBAL=8000; OpenAI reasoning consumes the completion allowance. Out of sample scope.
- A11 default 32000; Kimi adds the configured 32000 reasoning admission reserve. Out of sample scope.
- A12 default 64000 medium effort, overridden A12_UNIT=16000. Out of sample scope.

A ceiling cannot be certified sufficient merely because a minimal schema fixture fits. No cap was cut in development or v10 configuration.

## Per-call admission and private responses

Development Run._reserve now actually holds 30% margin for A07-A12. Per-call raw amounts use serialized byte bounds and full output reserve; Anthropic downstream calls cold-price at one-hour cache-write rates. Existing holds are checked against the actual serialized request immediately before sending. Unused holds are released after logged settlement; uncertain/unlogged API outcomes retain the hold pending reconciliation. WritingRun's fixed baseline/15-dollar operational ceiling and native parent cap remain; no cap reset or financial authorization is introduced. Existing authorization, projection, spend-review and checkpoint gates remain before dispatch. Requests with additional reasoning reserve use admission.output_reserve; Anthropic thinking is not counted twice.

Anthropic writing calls preserve model_dump(mode='json'), including all content block types, stop reason and usage, in the configured private audit directory; writing_response_audit_dir can override the existing plan_response_audit_dir. No folder was created or access permissions changed by this task. Private ACL verification remains a runtime-promotion preflight requirement. Files refuse overwrite; minimal metadata/paths may appear in receipts. No thinking/text split is inferred when the provider does not expose one. Writing calls bypass external tracing.

## Pricing and limits

See v10_sample_pricing.md and .json for every base call, token/byte basis, cache assumptions, pre-margin cost, 30% cost, cumulative total and both remaining-cap headrooms. All 11 GROUP inputs use the actual v10 registry and production packet builder. No provider tokenizer was called. Reconciliation count is not knowable exactly before GROUP: max 132 propositions / 32 per page gives up to five calls. The report prices five. Future compact-index inputs, final/gap allowances and outline/section packets are explicitly conditional size envelopes, not accepted scientific outputs or certified strict future-request bounds.

The sample prices two sections of 400-500 words. A09 conditional envelope includes all current authorized R0001 evidence to avoid assuming evidence can be omitted; actual selected packets may be much smaller. A07 future field maxima cannot all be attained simultaneously within the output-byte acceptance guard, so projections deliberately overstate input. Do not interpret totals as predicted invoices or exact funding requirements for an actual future package. Every real request must be rebuilt and re-admitted.

Only A07's system prefix is cacheable in v10: cache_system=True, cache_payload=(), cache_ttl=1h. First write and subsequent read pricing is conditional on exact prefix reuse, TTL and availability; private audit and diagnostic findings are not cached payloads. Uncached evidence is priced at ordinary input in that scenario. Actual admission must assume a cold write per call. There is no guarantee the sequential requests hit a cache, and a later version with hardened prompts has a different prefix and needs re-pricing.

The reported cache and cold totals are conservative serialized-byte pricing, not provider-measured token costs. No $582 context-ceiling proxy or full-review A10/writing proxy is used. Admission sums are not simultaneous holds: actual cost is recorded and unused reserve released after each call.

## Harness blockers / commands / PLAN acceptance

No verified GROUP command exists in this frozen v10. continue_stage1.py explicitly allows exactly one PLAN attempt, its marker is consumed, and its financial request is stale after failure. It must not be rerun or bypassed using generic litreview run.

May can approve the proposed repair by explicitly identifying repaired SHA-256 958ea8e00eabb8fafe93bd31a2f6758cc829b0113d107c945d10feac467f32db and the linked-part / unresolved-relocation representation changes, with scientific caveats resolved. Approval is not ledger insertion. Frozen v10 has no supported command to import a researcher-repaired PLAN with separate code-authored provenance; direct copying into outputs or writing TURN_ACCEPTED would misrepresent origin. A narrowly versioned, tested import/continuation path would be needed after approval, preserving the original provider response/receipt and binding the repair, registry, prompt/schema and runtime hashes. This task does not implement or invoke that path.

Even after PLAN acceptance, CP_SYN must be independently approved, then GROUP / RECONCILE / FINAL finish, then CP3 and a separate sample writing authorization; A08 allocation-ledger approval CP_LEDGER and contrary-evidence gates precede A09.

loops.max_redrafts=0 is enforced in the native writer and WritingRun. loops.max_critique_cycles=0 is not supported by WritingRun, whose constructor requires exactly one critique and whose continuation state advances from writing to verification. The generic runner also performs integration/verification/final editing outside critique loops, so setting zero does NOT authorize an A09-only stop. No stage-by-stage paid command can safely implement this sample in existing v10.

## Proposed sample configuration (NOT applied)

- loops.max_critique_cycles: 0; loops.max_redrafts: 0 (requires a separately verified guarded stop-after-A09 evaluation path; not a config-only change).
- loops.max_json_repair_attempts: 0; bridge.max_retrieval_rounds: 0 and synthesis.max_retrieval_rounds: 0 for the agreed no-extra-call base path. NEEDS_EVIDENCE must stop, not force a conclusion.
- agents.A08-OL.max_tokens: 8000; bridge.output_limits.A09_SECTION: 2500 only conditionally. Do not cut scientifically necessary response space merely to satisfy a budget.
- Preserve synthesis.output_limits and PLAN adaptive/medium. Keep A09_FRONT_MATTER priced.
- journal_scirev.limits.main_text_max_words: 1000 alone will not work for enabled pilot: pilot.journal currently overrides to 1500. There is no existing verified sample key enforcing 800-1000 words or 1-2 sections. A scoped, version-bound sample profile must be proposed and validated, not invented as an existing configuration setting.

Cheapest scientifically safe measures: first obtain exact free token counts for actual future requests under the isolated account when authorized; price one section only if allocation/contrary gates genuinely fit, not by dropping mandatory evidence; reuse the exact system prefix; omit A10-A12 as explicitly requested; stop on evidence needs instead of paying for unapproved retrieval. Do not drop GROUP packets, reconciliation pages or mandatory evidence. No lower GROUP ceiling is demonstrated safe. A nonrepresentative subset would require a separately labelled protocol and approval.

## Quality boundary

An 800-1000 word R0001 sample is a single-paper, unverified demonstration. It does not establish multi-paper synthesis quality, scientific verification, editorial acceptance or readiness for publication. No A10-A12 means errors and interpretive inflation can remain. Preserve source citations, A06 eligibility/dispositions, access limitations, contrary findings and all unresolved issues. Never label it a validated manuscript or full literature review.

## Conditional totals

- cache_scenario_total_with_margin_usd: 30.8136205
- cold_admission_sum_with_margin_usd: 55.66258100000001
- cold_excess_over_5_usd: 50.66258100000001
- cold_topup_over_remaining_subcap_usd: 41.47147600000001
- one_section_cold_total_usd: 46.99891300000001

Remaining writing $14.191105; parent $26.8747694. Both modeled full-path envelopes exceed both remaining allowances. Top-ups are arithmetic differences for these conditional envelopes, not recommended new authorizations. No top-up is applied.

## Final tests and review artifact

Full suite: 818 passed, 3 skipped (177.31s); no errors after isolating the integration simulation from the pre-existing one-cycle config. Skips: two unavailable run-20261025-100039 tests and one unavailable live probe. Final focused run after completing mode examples: 91 passed (4.13s). Production validators are unchanged. phase1_task_only.patch isolates this task from inherited dirty-tree work; task_change_inventory.json lists both. No PR opened, commit made or push performed.

Ledger reconciliation: local costs.jsonl totals $8.0280092 plus prior incident cost-only authority $0.0972214 = $8.1252306 cumulative. A07 evaluation costs $0.808895; no reservations. Live synthesis ledger still contains JOB_STARTED / TURN_REJECTED only. Original and proposed repaired PLAN hashes remain unchanged.
