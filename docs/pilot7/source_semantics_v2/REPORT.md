# Offline replay for run 20261123-214928

A05 remains `ordinary_json_local_v1`, canonical contract `A05-KE-canonical-0.9`.
The functional evaluator is version 2; production interpretation is
`source-semantics-2`. Its version now enters the generation/run identity and
functional fingerprint. No model or spending limit changed. No runtime was
modified or resealed; live dispatch and scope remain paused.

## Replay verdict and scientific defects

**All three expected observations pass the revised finding-level checks, with no
expected finding omitted. The original extraction fails the entity-label audit.**
A source-neutral derived record passes the local deterministic/schema checks; it is
not a newly independently validated record. It requires an A06-only check before
being counted as a completed functional success. A new A05 call is unnecessary.

The original gate incorrectly used C1's shared `plasma and tumors` matrix rather
than each finding's object link, and required NONE_REPORTED even for descriptive
detection. The source adapter preserves C1 and resolves F1/E2/plasma and
F2/E3/tumors separately. It records NOT_APPLICABLE for descriptive detection,
while the dose context retains NONE_REPORTED. Genuine comparative or quantitative
detection experiments retain their reported comparator and quantities for A06;
they are never automatically recoded to descriptive detection.

F2's raw NULL label is an extraction representation defect, not evidence that
its source interpretation was wrong. Only a DETECTED_IN finding with a matching
specimen-bound source passage and compatible polarity can be mapped to NEGATIVE
plus `NOT_DETECTED_UNDER_REPORTED_CONDITIONS`. An explicit warrant retains the
reported-conditions limit. A statistically null comparison, untested specimen,
biological absence and missing detection limits are distinct. Unsupported or
ambiguous mappings stop rather than invent an interpretation.

E1's ENDOGENOUS_METABOLITE and E4's APPROVED_DRUG are unsupported scientific
attributes in the supplied excerpt. The derived record replaces them with
MOLECULE and DRUG_STATUS_UNVERIFIED and preserves each original claim/reason in
its audit. No unsupported approval flag may bypass this gate. Supporting evidence
must bind the entity and label to an exact source quotation or a locally archived,
hash-checked lookup response inside the run; an arbitrary status_source URL is
insufficient. No lookup was performed in this replay. The archived A06 response
correctly qualified all three observations but failed to flag these attributes.
Its updated prompt explicitly audits both attributes and the deterministic adapter.

## Source and findings

The source is the three already cached abstract sentences for PMID 38768767,
DOI 10.1016/j.ijrobp.2024.05.009. The complete supplied excerpt, exact quotations,
locations, quantities and all historical A06 reasoning/constraints are in
[raw_validated/report.json](raw_validated/report.json); the original preparation and expectations
remain in [source_and_expectations.json](../a05_functional/source_and_expectations.json).
No source was discovered, substituted or added to the pilot corpus.

| Finding | Corrected interpretation | Supporting quotation | Archived independent A06 |
| --- | --- | --- | --- |
| F1 | Proposed metabolite detected in sampled plasma; E2 is the specimen | Full exact detection sentence in report.json | SUPPORTED_WITH_CONSTRAINTS: no numerical concentration, detection frequency or biological activity established |
| F2 | Tested and not detected in sampled tumors under reported conditions; E3 is the specimen | Same exact sentence, specimen-specific negative clause | SUPPORTED_WITH_CONSTRAINTS: not biological absence, failed penetration or inactivity; detection limit, timing and sample count unavailable |
| F3 | Maximum tolerated DSF dose 375 mg/d with RT and TMZ | Exact maximum-tolerated-dose sentence in report.json | SUPPORTED_WITH_CONSTRAINTS: combination context only; not monotherapy, general safety or a recommended dose |

The comparison distinguishes an evaluator defect from unsupported extraction
attributes and A06's missed attribute audit. It does not erase the original failed
functional verdict or treat a saved A06 response as a new independent reading.
Full-text extraction remains untested.

## Negative controls and production handoff

| Control | Outcome | Reason |
| --- | --- | --- |
| Swap E2 and E3 while keeping the same quotation and shared C1 | Rejected | Finding-specific specimen/polarity contradicts the source |
| Turn non-detection into biological absence | Rejected | Source supports non-detection, not absence |
| Recast 375 mg/d as a concentration | Rejected | MTD quantity is DOSE, with combination context preserved |
| Introduce ENDOGENOUS_METABOLITE without evidence | Rejected | Entity-bound source/lookup evidence is missing |
| Return an empty findings list | Rejected | Expected nonempty finding coverage is missing |

Interactive and batch validation both use Run._prepare_validation. A05 raw
outputs stay intact; corrected working extractions get an archived original and
versioned source audit. The exact A06 input includes that audit. Writer projection
carries specimen, non-detection outcome and per-finding comparator semantics;
bridge packet serialization preserves them. Old finding fingerprints no longer
match after the entity/polarity corrections, so the historical dispositions cannot
silently authorize the corrected record. Offline tests exercise the actual A06
handoff and writer packet using a saved response only as plumbing data, with no
provider call or claim of fresh independent validation.

## Accounting, receipts and smallest live verification

New paid dispatches/spending: **0 / $0**. All **149 original run files** were
hash-checked unchanged, including the original failed result, raw A05/A06,
**25 strict receipts**, costs and reservations. See
[raw_validated/preservation.json](raw_validated/preservation.json) and
[raw_validated/original_artifact_hashes.json](raw_validated/original_artifact_hashes.json).

Recorded spending remains **$0.1762446**. All five unresolved holds remain
**$0.124671** (0.019586 + 0.001107 + 0.037048 + 0.041668 + 0.025262).
Exposure is **$0.3009156**, leaving **$0.6990844** under the cumulative $1 smoke
allowance. The $50 combined cap and $25/$48 review pauses remain unchanged.
No hold is released, settled, assumed free or retried.

Seven strict successes remain exact provider/model/submitted-schema matches:
A04, four A07 bounded variants, and two A09 variants. Receipt names, hashes and
response-validation assessments are in raw_validated/report.json. The pending strict
checks remain A02, A03, A06, A08, A10 bounded, A12 and A12 unit: **$0.180645** worst
case at the existing 1,500-token output limit.

Smallest next independent task: the exact corrected A06 schema check
(**$0.034475** worst case), then an **A06-only** corrected-record check
(**$0.370000** including at most one format repair). Total **$0.404475**, bringing
maximum smoke exposure to **$0.7053906**, leaving **$0.2946094**. A06 remains
OpenAI gpt-6.1-sol, independent of Anthropic Sonnet's saved extraction.

Completing all seven strict checks plus that A06-only check costs at most
**$0.550645**, bringing exposure to **$0.8515606**, leaving **$0.1484394**.
No fresh A05 extraction is included or needed. A06 is bounded at 64,000 input
bytes/tokens conservatively (including schema/framing), 2,500 output tokens per
attempt, no truncation retry or model switch. Prepared input is 47,636 bounded
bytes. The ceiling uses the maximum configured input/cache-read/cache-write price,
including implicit OpenAI cache writes; configured prices were checked 2026-11-23.
A repair must fit the same hard bound. The complete prepared payload and its hash
are in raw_validated/prepared_a06_payload.json and raw_validated/report.json.

These are offline forecasts, not authorization or paid results. A future sealed
runtime/migration must preserve this run and its accounting, import the archived
A05 explicitly, and keep the original artifacts and incompatible approvals intact.
Any new unresolved hold or permitted-repair failure retains the stop rule. Scope
and all scientific approvals remain untouched; CP1 has not been created.

## Verification

Focused scientific regressions and the real handoff pass. Full-suite result is
recorded after completion in VALIDATION.md. Reproduce the versioned replay with
PYTHONPATH=src and `python -m litreview.functional_replay --run-dir <existing-run>
--output-dir <fresh-output-directory>`; replay refuses an existing destination.
