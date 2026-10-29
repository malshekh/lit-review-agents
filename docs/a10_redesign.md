# A10 scientific verification redesign and validation

**Verdict: CONDITIONAL PASS for structural capacity and enforcement.** Live scientific accuracy and
full-pipeline affordability are not established. No paid API calls, research execution, historical-run
changes, A07 redesign, A05/A06 rule changes or commits were made. The 5,000-word input below is a
deliberately repetitive in-memory evaluation fixture, not a generated literature review or publication.

## Root causes established before implementation

- The previous `Run._verify` scoped detailed findings but still sent the **entire synthesis package**
  and complete manuscript/plan every time; a detail request repeated that large input and replaced
  the initial report. Scoping findings alone did not bound request size.
- `evidence.verification_bindings` deduplicated by `(tags, section_id)`, so later sentences with the
  same tags escaped their own role/appraisal checks. It inspected section text only.
- `tags.bindings` treated text between tags as one unit. Untagged scientific assertions could be
  combined with tagged text; a deterministic warning sampled only 50 untagged items. The old output
  schema did not require one verdict per occurrence or exact global coverage.
- `_maybe_verify` could pass an explicitly stale report after edits under draft_and_final mode.
  A11 did not check manuscript/evidence identity before accepting it. Final export itself lacked a
  current-report gate, so direct finalization could bypass verification.
- A10 lacked request-level context admission and dedicated cost reservations. The old projection's
  four-call bound is incompatible with a bounded multi-call verifier.

## Implemented behavior and interfaces

`VerificationJob` uses A07's existing `EvidenceRegistry`, `details`, `retrieve`, explicit study identity
and compact indexes. It creates **verification state and result caches**, not another evidence database.
Production loads the approved A07 registry snapshot by fingerprint and rejects changed A06 findings,
contexts, citation metadata or molecular source attributes. Legacy artifacts use an in-memory view of
their validated records; no historical run was migrated or rewritten.

The deterministic inventory covers title, abstract, sections/headings (including introduction and
conclusion), explicit introduction/conclusion fields, keywords, captions, legends, tables and built
display items. Every nonempty candidate sentence/cell is reviewed, including uncited/untagged content.
Path, ordinal and exact text distinguish identical repeated sentences. Exact offsets remain recorded.
Table cells inherit the row's citations, bindings, column labels and complete row context.
Sentence/cell units may contain multiple assertions: all must be supportable for VERIFIED. This is a
conservative review inventory, not a proven linguistic decomposition into atomic scientific claims.

LOCAL packets contain exact occurrences; bound A07 propositions and source limitations; full relevant
findings, source spans, entities, quantities, contexts, eligibility and roles; source citation identity;
appraisal bindings and prior corrections. Unrelated findings from a cited paper are not automatically
resent when precise finding bindings already exist. Citation-only assertions receive that paper's
findings, subject to admission. Unknown citations/bindings and forbidden roles become code findings.

Strict responses require exactly one verdict per occurrence: VERIFIED, DEFECT, UNRESOLVED or
NON_SCIENTIFIC, with rationale. Scientific verdicts require all ten verification dimensions: source,
numbers/units, mechanism/causality, certainty, chemical identity, model/GBM applicability, clinical
reach, counterevidence, attribution/independence and citation. Every appraisal binding needs its own
preservation judgment. Missing judgments stop the job; appraisal promotion and ineligible evidence
block approval. A VERIFIED claim must identify visible evidence or an authorized source unit; missing
source passages and unbacked verification block release. Classification and entailment remain model
judgments: a valid citation, checked dimension list or structural PASS is not proof of scientific truth.

GLOBAL pages each receive the complete manuscript/table, exact occurrence-to-text verdict index,
prior corrections and global independence summary. Pages collectively expose **every registry finding,
A07 proposition, gap and reconciliation issue**, regardless of citation. Full evidence can be retrieved
outside the page or local packet. Each page must acknowledge the exact inventory and every index ID.
Evidence-based global issues require retrieved detailed finding IDs. Internal contradictions can be
reported using occurrence IDs without inventing evidence anchors. No majority vote resolves science.

Retrieval supports existing A07 finding-ID/AND-query operations and bounded references to existing
A07 source items/propositions: at most 12 units per round, two additional rounds. Missing evidence,
overbroad queries, oversized single units, incomplete responses and truncation stop safely; evidence is
never truncated to obtain approval. Such stops can require human narrowing/re-projection.

Every request is admitted using system + serialized user UTF-8 byte upper bounds with framing and
its output allowance. The **240,000 input-plus-output ceiling** conservatively stays below the 272K
input pricing threshold. LOCAL/GLOBAL output allowances are **10K/8K**, including reasoning. These
allowances are structural settings, not live-model adequacy measurements. Global pages also cap at
128 entries to bound acknowledgment output. Real-model truncation rates still need calibration.

### Version integrity and handoffs

Verification binds the complete manuscript object, plan, approved synthesis, registry digest and built
tables. Policy identity also hashes A10 implementation, prompt, strict schema and settings; execution
identity includes routed model and prices. Revised prose/evidence cannot inherit an old approval.
Atomic, hashed result caches preserve valid work across interruption. Local cache reuse requires
unchanged exact text, bindings, evidence and policy; changed character offsets alone do not make an
otherwise identical claim scientifically new. Fixed outer packet boundaries prevent one longer edited
sentence from repacking the entire document. Global results may be reused only for identical complete
global payloads; changed reader-facing text triggers fresh global review.

`_maybe_verify` reuses an exact current report or runs the bounded job; the previous skip-stale behavior
is removed. A11 rechecks freshness before critique and cannot ACCEPT over unresolved BLOCKING A10
defects. It receives a concise current report rather than the whole machine inventory. A12 correction
findings include exact text, path and offsets, not opaque IDs alone. Prior findings and version links
remain in the internal correction trace. Finalization independently rejects missing/stale/incomplete
approval and any MAJOR/BLOCKING findings, even if the release label says APPROVED.

Each dispatch reserves uncached worst-case input at the configured cache-write price plus full output
allowance before payment. Reserved calls disable automatic JSON repairs. Known billed failures release
their reservation after cost recording; unknown billing remains held and blocks duplicate dispatch.
The old A10 four-call WORST_CASE projection is replaced by a clearly labeled ESTIMATED_ENVELOPE
including revisions/retrieval. It is a conservative scenario, not a guarantee that arbitrary future
manuscripts fit. Exact reservations and the absolute spending cap remain authoritative.

## Exact implementation changes

| File/functions | Change |
|---|---|
| `src/litreview/verification_job.py:29`, `inventory`; `:98`, `VerificationJob`; `local`, `global_pages`, `run` | Inventory, bounded builders, retrieval, strict acceptance, cache/resume, policy/version binding and report assembly |
| `src/litreview/orchestrator.py:1456`, `_verify`; `_verification_registry`, `_verification_current`, `_maybe_verify` | Registry handoff, reservations, provenance and current-version checks |
| `src/litreview/orchestrator.py`, `stage_review_loop`, `stage_finalize` | Fresh A11 handoff, actionable A12 locations and final release gate |
| `src/litreview/evidence.py:468`, `verification_bindings` | A10-only surface coverage and repeated-occurrence handling; A06 rules unchanged |
| `src/litreview/agents/registry.py:24` | A10 defaults to strict bounded response schema |
| `schemas/A10-RV.bounded.schema.json`; `prompts/agents/A10-RV_Verification.md` | Version 2.0 bounded LOCAL/GLOBAL contract and scientific checks |
| `config/pipeline.yaml`, `scientific_verification` | Admission, packet/page limits, retrieval and output allowances |
| `src/litreview/tools/cost_projection.py:132` | Replace obsolete A10 full-corpus four-call forecast with estimated bounded-job scenario |
| `tests/test_verification_job.py`; existing eligibility/scope/finalization/revision tests | New adversarial/regression cases and updated A10 interfaces |
| `tests/a10_capacity_simulation.py`, `tests/a10_cost_summary.py` | Offline production-builder capacity and financial scenarios |

## Structural capacity results

Artifacts: [a10_capacity/measurements.json](a10_capacity/measurements.json), compressed exact Chat
Completions requests, cost scenarios and the prior complete system prompt. These are internal software
validation artifacts. No generation endpoint was called. **All input figures below are conservative
UTF-8 byte token upper estimates, not provider-counted tokens**. Output allowances are modeled maximum
completion tokens; mocked response lengths do not predict live output or reasoning usage.

| Measure | Previous A10, same fixture | Redesigned first pass | One-sentence edited version |
|---|---:|---:|---:|
| Main input words / registry papers | 5,000 / 120 | 5,000 / 120 | 5,000 / 120 |
| LOCAL calls | One monolithic first call | 38 | 1 |
| GLOBAL calls | No separately accounted global pages | 23 | 23 |
| Total calls | 1, optionally 1 detail repeat | 61 | 24 |
| Largest input upper bound | 6,563,415 | 229,601 | Below 240K with output |
| Largest input + output allowance | 6,595,415 | 239,601 | 237,404 |
| Aggregate input upper bound | 6,563,415 for initial call | 10,866,535 | 5,275,224 |
| Aggregate output allowance | 32,000, optionally repeated | 564,000 | 194,000 |
| Explicit candidate verdict coverage | Not occurrence-enforced | 257/257 | 257/257 |
| Built table candidates | Not independently enforced | 53 | 53 |
| Global registry finding coverage | No exact acknowledgment | 1,996/1,996 | 1,996/1,996 |
| Total global index entries acknowledged | Not enforced | 2,892 | 2,892 |

The largest first-pass request has 399 upper-bound units below configured admission and at least
42,399 below the 272K input-pricing threshold. Its maximum output allowance is already included.
The largest mocked response is 6,600 byte-bound units and fits its mode's allowance. Requests near the
admission ceiling are split; a single unbounded claim or global manuscript base can still halt safely.

This redesign reduces **maximum request size by about 96.5%**, not total uncached first-pass input.
Aggregate first-pass byte input rises about 65.6% because independent occurrences and complete global
review are now explicit. Do not claim measured total-token or paid-cost savings versus a valid prior
run: the legacy request does not pass the new admission policy, and its true tokenizer count is unknown.
The previous separate 120-paper projection of 1,477,200 input tokens per A10 call was itself an estimate.

## Costs and complete-pipeline implications

Configured rates match the official [GPT-6.1 Sol model page](https://developers.openai.com/api/docs/models/gpt-6.1-sol):
$2/M input, $10/M output, $0.10/M cached input, $2.50/M writes; prompts above 272K input use higher
rates. The strict byte ceiling avoids that tier for tested primary-model requests. Reasoning is billed
as output and shares completion limits; see [reasoning guidance](https://developers.openai.com/api/docs/guides/reasoning).
No output/reasoning consumption or cache behavior was measured with a live model.

| Scenario | First pass | Small edited version |
|---|---:|---:|
| Planning: 3 bytes/input token, 25% output-cap use | $8.65 | $4.00 |
| Same, 50% output-cap use | $10.06 | $4.49 |
| Ideal within-pass GLOBAL prefix caching, 25% output | $6.38 | $1.73 |
| Finite adverse: 50% output, +30% retrieval and +10% paid retries, proportional approximation | $14.09 plus retrieved detail | $6.28 plus retrieved detail |
| All input byte bounds charged as ordinary input, all output caps | $27.37 | $12.49 |
| All input byte bounds charged as writes, all output caps | $32.81 | $15.13 |

The 3:1 conversion and 25–50% output use are **uncalibrated scenarios**, not a credible measured live
cost distribution. Allowing 2–4 bytes/input token and 25–50% output use broadens the sensitivity band
to **$6.84–$13.69** for the first pass and **$3.12–$6.25** for the small edit, before retrieval/retries.
The common GLOBAL prefix is about 165KB per request: it includes the full manuscript
and compact verdict index. The ideal cache scenario assumes one write followed by hits for 23 global
calls and gives about $2.28 saving per version. No hit rate, cache boundary, TTL or write usage was
observed. No cache discount is assumed in reservations. Fallback providers need separate qualification.

Compared with the old **$25.56 projected A10 budget line**, two complete bounded first-pass equivalents
would be about $17.31–$20.13 at modeled 25–50% output use. A first pass plus the measured small-edit
pattern is about $12.66–$14.55. These are forecast comparisons, not observed savings on equivalent paid
runs. Major revisions, new bindings or changed evidence invalidate more local caches and cost more.
Metadata-only changes with identical scientific payloads can reuse both local/global results while
binding a new immutable manuscript version. Unresolved scientific changes never inherit approval.

Using the prior other-stage scenario, excluding A07/A10, leaves **$99.80** for A02–A06 and A08–A12
other than A10. Adding current A07 $30–$39 gives these illustrative totals at 25% A10 output use:

- Two full A10 checks: **$147.11–$156.11**.
- First check plus a small-edit revalidation: **$142.46–$151.46**.
- First check plus five small edited versions: **$158.46–$167.46**, before cache savings/retries.

The $150 objective is more plausible in limited-edit/cache-favorable scenarios, **not established**.
Other agents' context limits and future costs remain unvalidated. The generic pre-manuscript A10
envelope intentionally includes dense packets, all configured edit versions, full output caps and
retrieval; it can reject the $150 gate even when a cheaper measured workload would fit. Re-project
from representative usage before spending. The actual run cap remains $35; no cap was raised.

## Tests, remaining risks and acceptance

Regression coverage includes repeated and identical evidence tags; uncited assertions; source-bound
table cells; numerical/unit, mechanism and misattribution adversarial inputs with scripted defect
verdicts; distant-section supplied conflicts; uncited source retrieval; blocked roles; appraisal
omission/promotion handling; stale manuscript/evidence/synthesis/table/policy rejection; A11 freshness;
release blocking; incomplete local/global responses; exhausted retrieval; cache tampering; interruption;
selective reuse; and budget refusal/unknown-billing reservation retention. The semantic verdicts in
these tests are supplied by fixtures. They prove enforcement and preservation, **not independent
detection of those scientific errors**. The full suite passed **292 tests**; `litreview check` (without
live pings) and `git diff --check` passed. No paid health checks ran.

Remaining acceptance conditions: scientist-adjudicated live tests must assess actual entailment,
numerical/unit conversion, disulfiram/Cu/metabolite identity, mechanistic overreach, model specificity,
clinical extrapolation, attribution/appraisal, contradiction recall, unsupported-claim classification,
omitted contrary evidence, table interpretation and study dependence. Include blinded errors and
negative controls; measure false positives, omissions, valid completion, reasoning/output usage,
retrieval quality and billed cost. The 10K/8K caps need live calibration; official reasoning guidance
recommends generous initial experimentation. No scientific check should be removed to fit a forecast.

The replicated corpus still has the previously documented partial-cycle thematic-record inflation;
it is not 120 independently adjudicated scientific papers. Cached judgments cannot exceed extraction
recall or A06 validity. Sentence/cell inventory and model NON_SCIENTIFIC judgments need an independent
coverage audit. Very long indivisible claims, oversized global bases and unresolved source requests
stop rather than silently pass. Only the configured primary model's bounded serialization was tested.

**Recommendation:** keep A07 frozen. A10 is structurally implemented and ready for a separately
authorized small scientific evaluation, with the current-version and final-release gates enabled.
Do not certify scientific accuracy, publication readiness or $150 affordability from mocked success.

Reproduce with `python -B tests/a10_capacity_simulation.py`, then `python -B tests/a10_cost_summary.py`.
The prior system prompt is retained for the same-fixture comparison. All simulation text remains
evaluation-only input inside compressed request artifacts, not a reader-facing manuscript.
