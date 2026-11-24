# Explicit retained-hold continuation, November 24, 2026

The researcher explicitly instructed: retain the unresolved $0.019586 hold, commit the changes, seal a fresh runtime, and perform the nine corrected smoke checks (estimated about $0.21) to start scope and stop at CP1. The pre-existing $1 smoke allowance and $50 combined cap include all recorded spending and reservations; spending review pauses remain $25/$48. No scientific checkpoint is approved by this instruction.

The rounded daily Sonnet amount ($0.0049) cannot establish the failed request's individual cost. The researcher reports no more precise billing export is available. No amount is assigned and the historical hold is not released or converted into a charge.

The new guard permits only the specifically authorized historical hold, bound to its exact receipt hash, amount, run ID, model, schema hash, timestamp and uniquely matching saved HTTP 400 request ID. A corrected schema must differ from the rejected schema. Any new ambiguous dispatch blocks further work. This distinguishes a known schema rejection with unknown billing from a request whose execution is unknown. Smoke execution stops after the first failed check, retaining its receipt and any hold.

`build_pilot7_continuation.py` exports a clean committed tree, retains the exact v16 financial configuration, verifies its pinned manifest, copies and verifies every run file, archives superseded derived indexes, retains the existing hash-bound receipt enrichment, and records a v17 migration inventory. Neither sealed v16 source nor its run is modified. The new authorization is itself inventoried in the new seal. The non-admin launcher preserves endpoint, runtime-integrity, budget and scientific checkpoint checks.

No rehearsal outputs or approvals enter the live run. Full-text extraction remains untested until actual retrieval and extraction execute.

The operational overlay disables automatic truncation retries, because the researcher prohibited automatically increasing limits after a failure. Financial limits, prices and model selections remain unchanged.

Email notifications are disabled in the operational overlay; checkpoint results are presented locally.

## Live adapter failure and correction

V17's first corrected A02 smoke returned `{}` with stop reason `stop`, and was correctly rejected by exact-schema validation. Its recorded cost is $0.001826; total recorded spending became $0.0611663, plus the original $0.019586 hold. No other corrected smoke was dispatched in v17.

Inspection identified `strict: false` in the OpenAI Chat Completions adapter. It now explicitly sends `strict: true`; the request-body regression requires that flag. The official Structured Outputs guide establishes this requirement: https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat . Models, output caps and scientific schema fields are unchanged. V18 migrates every v17 receipt, cost entry and authorization, preserving the rejected response and the historical unresolved hold. All five old OpenAI successes were already invalid, so no OpenAI acceptance is reused across this transport correction; the six Anthropic A07/A09 acceptances remain unchanged.

## Anthropic nullable-enum rejection

V18's A02 and A03 checks passed ($0.004586 and $0.002748). A04 received HTTP 400 `req_011ChMwemm1jBP7wi9kaej8c`: enum value PRIMARY did not match list-valued type [string, null]. Its new $0.001107 reservation remains unresolved, in addition to the original $0.019586. Recorded spending is $0.0685003; total outstanding reservations are $0.020693. Remaining checks were not dispatched.

The Anthropic schema adapter now expresses nullable string enums as explicit typed anyOf branches. Local contracts, field names, allowed strings and nullability are preserved exactly; an equivalence regression includes invalid strings, numbers, booleans, arrays and objects. The provider checker rejects an unconverted list-valued enum before dispatch. Only A04's configured submitted-schema hash changes; OpenAI schemas, A05 and the six reusable Opus schemas remain unchanged. The new A04 billing hold is not covered by the original single-request retained-hold exception; a separate researcher decision is pending.

The v19 migration audit exposed a receipt-recovery ordering defect: sorting receipt UUID filenames could let the old invalid A02 response overwrite its later valid success. Recovery now preserves an independently validated success for the identical current provider/model/schema, irrespective of filename order. Both orderings are tested; original receipts and costs are unchanged. V20 carries this correction.

The researcher subsequently explicitly replied: "Retain both holds and continue corrected checks." V20 records a separate hash-bound exception for the new A04 request. Both amounts remain reserved ($0.020693 total); this does not release either hold or authorize ignoring future unresolved requests.

## A05 internal grammar-size rejection and lossless transport

V20's corrected A04 check passed ($0.0002772). Anthropic rejected A05 with HTTP 400 `req_011ChMxNR9guXmuWRanNjcoB`, citing compiled grammar size. Its $0.037048 hold remains unresolved. Recorded spending is $0.0687775; total reservations are $0.057741. No scope call or scientific approval occurred.

The official documented union limit is not a guarantee of successful compilation: internal interactions also matter. The A05-only authored wire contract now represents its fifteen nullable strings as arrays of zero or one string. This is lossless: [] maps to canonical null, [""] to an empty string, and [text] to the exact text, including literal "null" or "NOT_REPORTED". Full wire validation rejects multiple values before decoding. Only those explicit schema positions are decoded. The raw provider response is retained and the decoded paths are logged. The complete unchanged canonical A05 schema, conditional scientific requirements, semantics, quantities and span checks run after decoding. The converted quantity null/object union remains, reducing wire union count from 16 to 1. No field, comparator, qualifier, identifier or value is dropped and no default scientific value is invented.

The repair passed 110 focused regressions, including nonempty source-grounded extraction/independent-validation handoff and reversible string/null encoding. This is offline evidence only, not live full-text extraction or a claim of provider compiler acceptance. A separate researcher decision on retaining the new A05 billing hold was requested before another paid dispatch.
