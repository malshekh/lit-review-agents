# Bounded screening recovery

The 20-record A04 batch returned max_tokens at the existing 16,000-token cap,
with no response text. Its receipt and $0.0143374 charge are preserved. There
are no screening decisions to recover, and no new unresolved hold. All 140
independently discovered/deduplicated records and the successful query plans and
52 query results remain in the same run. CP1 remains approved; CP2 is not.

The fresh v30 runtime reduces cq_batch_size from 20 to 4 for pilot7 only. Models,
provider schemas, per-call token caps and $50/$25/$48 financial settings remain
unchanged. New batches use new counter identities after failed B001. The old
failed dispatch is never blindly repeated. Identical scope-guide copies are
removed from request specifications only when equal to the complete authoritative
guide still present at the top level. Every unique rule and selection criterion
is preserved, and the source specification/CP1 decision is never mutated.

Full offline suite: **1,160 passed** (316.68 seconds). Focused scope/discovery
recovery tests: **32 passed**. No replacement paid call was made during tests.
The approval-service usage-limit rejection affected one offline inspection; it
was retried through the same approval path after the user said Continue and
succeeded. No approval check was bypassed. The usual scientist checkpoints and
CP2-before-extraction stop remain in force.


## Effective-profile correction

V30's initial batch override was mistakenly placed under profiles.pilot7.loops,
which config.effective does not merge into runtime loops. Actual request B002
therefore still contained 20 records, although duplicate-guide removal applied.
It reached max_tokens, cost $0.0135221 and was fully accounted with no new hold.
It was not interrupted or blindly repeated. Recorded spending is $0.8813451;
the original five holds remain $0.124671. This is combined pilot spending;
smoke exposure remains $0.3785106, below its separate $1 allowance.

V31 uses profiles.pilot7.overrides.loops.cq_batch_size=4. The builder asserts the
effective merged value. The sealed authorization binds the expected batch size,
and the launcher refuses dispatch on mismatch. A new audit action reports the
actual effective size, model/token caps, spending cap and review points before
paid execution. Focused regression suite: **33 passed** after this correction;
last full suite **1,160 passed**. Models, 16,000-token A04 cap and financial limits
are unchanged. The old attempted overrides and both failed dispatches remain in
prior sealed runtimes and migrated receipts for audit.

## One-record continuation

Eleven four-record batches (B003-B013) completed and committed 44 decisions.
B014 reached the unchanged 16,000-token cap with partial text; its $0.0123253
charge is accounted and no partial decisions are accepted. Total recorded
spending is $1.0044494; all five existing holds remain $0.124671.
V32 keeps every receipt, decision, failure and CP1 approval, and lowers the
effective screening batch size to one. No model, provider contract, token cap,
financial limit or checkpoint is relaxed. Only unfinished records are dispatched
under new counter identities; paid extraction remains blocked by CP2.

V32 offline regressions: 67 passed (scope delivery, effective profiles, CP2 integrity and architecture); last full suite: 1,160 passed. No application logic or contracts changed in this continuation.
