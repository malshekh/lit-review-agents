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
