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

## Authored Anthropic A05 wire contract and final checks

The official Anthropic limits also cap optional parameters at 24 and union-typed parameters at 16.
`A05-KE.anthropic.schema.json` is an explicit A05-only provider contract, not a generic rewrite of arbitrary
schemas. It retains every scientific property path in the complete local schema, with zero optional wire
parameters and 16 unions. Unreported context dimensions and the few non-nullable metadata locations use
the documented `NOT_REPORTED`/`NOT_APPLICABLE` representations; no missing experiment details are inferred.
Nullable object identifiers, quantitative uncertainty, attribution and bridging remain available. All local
constraints and scientific semantic checks still run. The provider prompt describes these representations.

The recursive compatibility checker enforces the documented resource limits before dispatch. Definition
and scientific property names such as `if` or `then` are preserved as names, rather than stripped as schema
keywords. A dedicated regression validates a referenced definition with those names.

The full suite with the complexity guards passed **1,052 tests in 192.02 seconds**. After the final
definition-name preservation edge case, **41 focused contract/migration/receipt tests passed**. No live
schema-compilation success is claimed; corrected paid smoke checks remain blocked by reconciliation and
the other incomplete provider contracts. Source receipts still permit exactly six unchanged checks to be
reused after offline validation, and nine checks need eventual correction/retesting. No paid call was added.

## Remaining provider contracts completed (2026-11-24)

The eight blockers above are now complete, closed contracts. `structured.schema_inventory()` reports no
problem for any of the 15 configured provider/schema pairs, and each repaired schema also passes the check
for the other provider.

| Schema | Provider | What changed |
|---|---|---|
| A02-SP | OpenAI | Readiness, scope, perspective options, selection criteria, themes and search seeds fully typed; every field required, unknowns `null`. `synonyms` is a list of `{concept, synonyms}` (strict output has no free-form maps). `researcher_decision` left the model's output: code records it at CP1. |
| A03-LM | OpenAI | Concept blocks, query families (with the outline's `section_ids`), filters, repairs and seed recall typed. `compiled` is a list of `{source, query}`; `orchestrator.compiled_queries` reads it and still reads plans saved as a map, and refuses a source compiled twice. |
| A04-CQ | Anthropic | Qualifications, review queue, theme suggestions and criteria defects typed and closed; 7 nullable fields (limit 16), no optional fields. |
| A06-SV | OpenAI | One shape for both modes: every PER_PAPER and PER_THEME field is always present, the other mode's lists empty and identifiers `null`; the local schema enforces that separation per mode. Validation rows, dimensions, defects, normalization conflicts, source inconsistencies, conflicts, independence, evidence reach and the paging fields are typed. Batch merges produce the same complete shape. |
| A08-OL | OpenAI | `budget_summary` typed, `title.word_count` and `reserved_human_items` required, root closed. |
| A10-RV bounded | OpenAI | Each retrieval request carries all four fields (unused lists `[]`, unused query `null`). |
| A12-EDI, A12-EDI.unit | Anthropic | Sections, change log, queries, escalations, consistency register typed and closed. Keywords, table captions and figure legends are no longer editable by A12. In the unit contract `title`/`abstract` are `null` for a section unit, and a `null` never overwrites the front matter. |

The prompts (A02 0.4, A03 0.6, A04 0.6, A06 0.9, A08 0.7, A12 0.3) document the same contracts and say that
every field is always present; generated contract lines were regenerated.

**Smoke hold.** `litreview settle-smoke-hold <run_id>` lists held smoke reservations with their receipts.
With `--reservation`, `--billed-usd`, `--evidence` and `--by` it settles one uncertain dispatch on the
researcher's attestation of what the provider billed: the amount is logged as a cost entry (zero included),
the receipt records the settlement and evidence, provenance records the human decision, and only then is the
reservation released. Nothing is assumed free; a received reply, a mismatched request ID or a second
settlement is refused. The $0.019586 hold for `req_011ChM1MMKaDrZauPitV2pKC` is **not** settled: that needs
the billed amount from the Anthropic console (or an admin-key cost report) for 2026-11-24 02:58-03:15 UTC.

**Smoke retests.** The six reusable Opus checks (four A07, two A09) are unchanged. Nine checks need a paid
retest under the new contracts (A02, A03, A04, A05, A06, A08, A10, A12, A12 unit), worst case about $0.21.
None was run.

**Verification.** Full suite 1,077 passed (python-docx and matplotlib, both in `requirements.txt`, installed). The discovery rehearsal passes all nine route checks;
October replay outputs are now projected onto today's A05 contract and every projection is counted in its
output. `scripts/readiness.py` passes every offline check.
