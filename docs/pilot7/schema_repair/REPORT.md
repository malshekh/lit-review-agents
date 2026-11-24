# A05 extraction contract and smoke-receipt continuation

The existing run is `20261123-214928`, sourced from sealed v15, manifest
`f0743f57587dc387c72b2b92d2ec64e05177c5126f84f68600ba3b7134dc08b2`.
This work retains the $50 combined cap, $1 smoke allowance, $25/$48 review pauses, configured models,
current non-admin account, every receipt and every scientific checkpoint. No approval is inferred.

## Contract repaired

`A05-KE.schema.json` now explicitly declares the study profile, entity identities/roles/constructs,
contexts and their nested `fields`, finding identifiers and qualifiers, verbatim spans and their locations,
premise spans/bridge, raw quantities and separately explained conversions, author-stated limitations,
in-paper conflicts and out-of-scope observations. Context fields include matrix, comparator, replication,
statistical test, reference method, data split and evaluation unit. Unknown/not-reported values remain
explicit; identifiers reserved for code normalization remain null. Figure legends and image inspection
are separate; this text route cannot claim image inspection. The extraction prompt's machine-generated
contract is regenerated from the complete schema.

The local validator retains conditional predicate requirements and every schema constraint. Additional
semantic checks reject duplicate IDs, broken subject/object/context references, empty source spans,
implicit inferences without premise spans/bridge, and inconsistent source-access levels. Gate 1 remains
the independent verbatim span, source-location and quantity/unit check. A nonempty spiked-plasma fixture
passes the full A05 schema, transformed schema, Gate 1, and real A06 preparation/batching/save path with
a scripted independent validator. This is offline machinery evidence, not live scientific validation.

## Provider compatibility

The transformer no longer invents object closure or required fields. Undefined objects, untyped arrays,
undeclared required fields (including local-only conditional branches), invalid references, unsupported
composition and provider-specific strict-output requirements are reported before reservation/dispatch.
The checker visits nested properties, array items, definitions, local references and composition branches.
Anthropic optional fields are preserved; OpenAI's all-properties-required rule is checked explicitly.
Recursive internal references are accepted for OpenAI and refused for Anthropic. Constraints omitted from
the provider subset are listed and remain enforced by full local validation.

All 15 configured strict provider/schema combinations are audited. The complete A05 contract passes the
offline provider check. The audit also exposes eight pre-existing incomplete contracts: A02, A03, A04,
A06, A08, A10 bounded verification, and both A12 variants. These are now explicit launch blockers rather
than being silently rewritten into empty or scientifically impoverished objects. They are not represented
as repaired by this A05 change. Kimi receives JSON-object mode, not a submitted strict schema; its full local
validation continues to apply.

## Smoke acceptance and previous responses

Acceptance requires a successful provider-specific stop (`end_turn` for Anthropic, `stop` for OpenAI),
strict JSON parsing, validation against the exact submitted schema and its actual hash, and matching
provider/model identity. New receipts atomically retain the submitted schema, hash, stop reason, response
identity, usage and text. HTTP errors retain status/request identifiers without assuming zero billing;
credential values are redacted. Recovery cannot reapprove truncated, refused, invalid or mismatched output.

The 14 received v15 responses were reassessed offline. Exact submitted schemas were reconstructed using
the verified v15 transformer and schema files; each reconstructed hash matches its original receipt, and
stop reasons come from the uniquely matching saved smoke-log row. Five earlier successes are invalid
against their actual submitted schema (A02, A03, A06, A08 and A10 lack required fields). Six checks qualify
for reuse unchanged: the four bounded A07 schemas and the two A09 schemas. Nine checks remain necessary
after contracts and accounting permit them; no paid recheck has been performed.

See `receipt_reassessment.json` for per-check evidence. Original receipts and old acceptance records are
preserved; incompatible approvals are not activated in the continued run.

## Accounting and migration

Recorded spending stays $0.0593403. The $0.019586 reservation associated with HTTP 400 request
`req_011ChM1MMKaDrZauPitV2pKC` stays held. Combined recorded and held exposure is $0.0789263.
The error establishes rejection of the schema, but there is no independent usage/billing receipt for that
request, no billing export in the run, and no configured current-account admin billing credential. It is
therefore a reconciliation blocker; neither zero billing nor a release is assumed. No unsettled dispatch
is repeated. Before another paid check, provider billing evidence must settle that request and all required
provider contracts must pass compatibility checks.

`scripts/pilot_smoke_continue.py` performs explicit offline migration into a new sealed runtime. It checks
both externally pinned manifest hashes, copies and hashes every original run file, preserves financial
files and original receipt bytes, archives the prior acceptance index and pin, reconstructs evidence,
and builds a new acceptance index only from validated compatible receipts. It records source/destination
commits and manifests, original-file hashes, spending, holds and reassessment. Completed migration is
idempotent; an incomplete migration fails closed rather than resetting or overwriting the run.

The pipeline remains before scope. CP1 is not ready; no scientific checkpoint was approved. Full-text
extraction remains untested until actual retrieval and extraction run. The two chapters remain targeted
at approximately 800 words each, excluding headings and references, with the eight supplied subsection
themes and source-access limitations retained.

Official requirements consulted: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

## Verification result

Stable full offline suite: **1,050 passed in 193.42 seconds**, with sockets and name lookups blocked. Focused scientific-contract, smoke and migration regressions passed. The nonempty handoff fixture is synthetic and does not establish live full-text extraction.

A read-only Anthropic cost-report request for 2026-11-24 02:58-03:15 UTC (the November 23 local smoke window) returned HTTP 401 authentication_error with the current-account key. No inference request was sent. Redacted evidence is retained privately as runs/schema-repair-billing-evidence.json and will travel into the continued run. The response does not establish the failed request's billed amount; the hold remains unchanged.

