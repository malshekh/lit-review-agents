# A07 targeted efficiency optimization

**Verdict: CONDITIONAL PASS.** Freeze the A07 package/interface provisionally for the A10 redesign.
The tested structural workload scales to 120 papers with fewer calls and unchanged scientific inputs.
Production scientific reliability, live output sufficiency and full-pipeline affordability remain unproven.
No paid generation, research execution, other-agent changes, historical-run edits or commits occurred.

## Root causes and changes

The previous 49 finding-empty GROUP packets held **391 mandatory records: 239 EVIDENCE_REACH,
136 SYSTEM_GAP and 16 CONFLICT**. Their source themes often did not match synthetic T1–T8 in the
replicated fixture, or their source text contained no in-registry finding IDs. Some conflicts refer to
the partial-cycle papers outside the selected corpus, a known benchmark defect. These are not 49
scientifically dispensable calls: reach summaries, constraints, proposed resolutions and gaps need
interpretation. Absence of a finding is not evidence of biological absence.

Implemented three small changes:

1. Check **all eligible candidate packets** for room, rather than overflowing when only the first
   candidate is full. This also accommodates paper items in another packet containing that paper's
   findings, removing a redundant overflow packet and its duplicated finding anchors.
2. Pack source-only overflow items in batches of **16**, keeping finding-bearing packets at **8**
   mandatory items and 24 findings. Source-only packets remain explicitly administrative UNMAPPED
   collections; every source retains its own theme_record/affected-theme identities and mandatory
   binding. Paper items needing usable finding anchors are excluded from source-only packing.
   No source interpretation is computed automatically or omitted. The GROUP schema permits 16 gaps;
   runtime still enforces 8 in ordinary packets and 16 in source-only packets.
3. Serialize SYSTEM_GAP source content once, in its full item, instead of duplicating it as item and
   source. Remove original_item_id from model-facing item metadata. Full original IDs, occurrence
   lists, source content and alias reversal remain in the registry and assembled package.

Output allowances remain **PLAN 4K / GROUP 12K / RECONCILE 6K / FINAL 6K**, including thinking.
Source-only packets contain no initial finding-proposition or unused-finding output. This permits
more source analyses under the same cap; it does not prove that a live model can finish every dense
packet. Oversized, invalid, truncated or incomplete responses still stop atomically. No scientific
analysis was replaced with a generated template. Deterministic work is confined to ownership,
packing, aliases, provenance copying and accounting.

### Exact modified implementation

| File/function | Change |
|---|---|
| `src/litreview/synthesis_registry.py:115`, `EvidenceRegistry.packets` | All-candidate placement; segregated, bounded source-only consolidation |
| `src/litreview/synthesis_registry.py:201`, `packet_payload` | Deduplicate source serialization; retain original registry/package contract |
| `src/litreview/synthesis_bounded.py:46`, `_packets`; `:219`, `group` | Pass source-only bound; enforce packet-specific gap bound before staging |
| `config/pipeline.yaml:114` | New max_items_per_source_group=16; no reduction of output allowances or increase in spend cap |
| `schemas/A07-SYN.bounded-group.schema.json:201` | Internal GROUP gap maximum 16; regular-packet maximum enforced in code |
| `prompts/agents/A07-SYN_Synthesis.md:65` | Explain source-only limits, separate thematic bindings and deduplicated source format |
| `tests/test_a07_efficiency.py` | New packing, coverage, reconciliation, bounds and resume regressions |
| `tests/a07_validation_audit.py:39` | Optional output directory to preserve the prior audit |
| `tests/a07_efficiency_report.py` | Reproducible before/after measurements, source equality assertions and cache-prefix calibration |

The existing registry-wide independence logic, A05/A06 scientific rules, routing, A10 interface,
checkpoint authorization, journal/commit mechanics and runtime context admission are unchanged.
Changed prompt/settings/schema fingerprints require a new synthesis identity and CP_SYN approval;
old accepted turns cannot silently resume under these settings.

## Before and after: actual production request builders

Anthropic's free counter successfully counted **262 optimized baseline requests** plus **20** explicit
two-round retrieval-fixture requests. Two further free counts calibrated the system prefix. No
generation was performed. The previous **340** meant **320 unique test requests across 40/80/120
workloads plus 20 on a separate four-paper retrieval fixture**, not 340 expected generation calls at
120 papers. Before and after baseline simulations have no requested retrieval. Real A07 calls can
increase with retrieval and paid failed attempts.

| Papers | Calls before → after | GROUP calls before → after | PLAN / RECONCILE / FINAL after | Finding-empty groups before → after | Total provider input before → after | Aggregate output allowance before → after |
|---|---:|---:|---|---:|---:|---:|
| 40 | 68 → 52 | 62 → 46 | 1 / 4 / 1 | 31 → 16 | 1,474,363 → 1,342,700 | 778,000 → 586,000 |
| 80 | 103 → 86 | 94 → 77 | 1 / 7 / 1 | 34 → 18 | 2,859,623 → 2,703,720 | 1,180,000 → 976,000 |
| 120 | 149 → 124 | 136 → 111 | 1 / 11 / 1 | 49 → 25 | 4,539,414 → 4,304,050 | 1,708,000 → 1,408,000 |

At 120 papers: **16.8% fewer calls**, **5.2% less aggregate input**, **17.6% less aggregate output
allowance**. Scientific output need is not assumed to shrink in proportion to allowances. Mechanical
proposition count falls 325→324 because the repeated paper-anchor proposition disappears; distinct
findings remain 1,996, mandatory units 688. The source-only packets now hold 397 units, including six
previously beside the displaced repeated paper anchors. Every unit still has exactly one owner.

| 120-paper operation | Calls before → after | Provider input before → after | Largest optimized input | Output allowance per call |
|---|---:|---:|---:|---:|
| PLAN | 1 → 1 | 416,539 → 416,714 | 416,714 | 4,000 |
| GROUP | 136 → 111 | 3,141,588 → 2,905,938 | 42,284 | 12,000 |
| RECONCILE | 11 → 11 | 889,034 → 889,123 | 81,316 | 6,000 |
| FINAL | 1 → 1 | 92,253 → 92,275 | 92,275 | 6,000 |

The slightly larger PLAN/RECONCILE/FINAL requests reflect clearer shared instructions. Global
reconciliation and its full compact proposition index were retained; cutting that visibility to save
input was rejected. PLAN remains the largest request. Optimized provider input plus output allowance
is **420,714**, leaving **479,286** under 900K. The conservative runtime byte-bound equivalent is
**863,546**, leaving **36,454**. Optimized 40/80 PLAN sums are 150,814/291,743 provider tokens and
317,774/603,266 byte-bound units. All fit admission and the documented 1M model window.

At 120 papers GROUP input ranges **9,766–42,284**, median **28,631**. Finding counts: 79 groups of 24,
two of 23, one of 20, one of 15, one of 7, two of 6, and 25 of zero. Mandatory-item counts: two groups
of 0; eight of 1; sixteen of 2; twenty-four of 3; seventeen of 4; twelve of 5; two of 6; one of 7;
four of 8; one of 13; twenty-four of 16. Larger median inputs are expected when empty calls are
consolidated. The largest mocked response is 5,935 byte-bound units, below its configured allowance.

## Costs and the $150 pipeline constraint

Provider input is measured. Generated output, reasoning, cache behavior and retries remain modeled.
Thinking shares max_tokens; no extra thinking allowance is added on top of full output caps. Prices
are the unchanged configured Opus 5 rates: $5/M input, $25/M output, $10/M 1h writes, $0.50/M reads.
A07 is interactive and receives no batch discount. All values below are estimates, not billed cost.

| A07 scenario, ordinary uncached input | 40 before → after | 80 before → after | 120 before → after |
|---|---:|---:|---:|
| Baseline: 25% aggregate output allowance | $12.23 → $10.38 | $21.67 → $19.62 | $33.37 → $30.32 |
| Planning: 50% aggregate output allowance | $17.10 → $14.04 | $29.05 → $25.72 | $44.05 → $39.12 |
| Every output allowance consumed | $26.82 → $21.36 | $43.80 → $37.92 | $65.40 → $56.72 |

The old fixture-visible-output/3 plus thinking at 25% of caps formula falls **$37.90→$34.59** at
120. That sensitivity keeps similar per-source visible content; it does not infer that needed
scientific analysis falls simply because there are fewer calls. The apparent 25–50% utilization band
is **not a live-calibrated realistic range**. Model high-effort thinking and dense source analysis
could consume more, or halt before JSON completion.

Free-counter prefix calibration gives approximately **3,956 cacheable system tokens** (the input-count
difference with/without system, not an actual cache-usage measurement). At 124 calls, no cache gives
$30.32–$39.12. Assuming each call writes that prefix afresh at 1h rates gives **$32.77–$41.57**;
assuming one 1h write followed by 123 hits gives **$28.15–$36.95**. Cache boundaries, actual hit rate,
TTL refreshes and token accounting can differ in generation. Payloads are not cache-marked; no
discount applies to all 4.30M input tokens.

A finite adverse operating scenario—full outputs, one extra retrieval round for 30% of GROUP/
RECONCILE operations, plus paid retries for 10% of baseline calls—scales roughly **$91.56→$79.41**,
plus retrieved-detail input and cache-write premiums. This is a coarse proportional scenario, not a
measured or absolute upper bound. Full-baseline outputs with all input deliberately priced as 1h
writes fall $88.09→$78.24, an overstatement since only system is cache-marked. Two retrieval rounds
on every GROUP/RECONCILE would mean 368 optimized calls versus 443 before; output and input details
would need separate projection. Unlimited human retries have no finite modeled worst-case bill.

The unchanged other-stage scenario is **$125.36**, leaving **$24.64** for A07. Even ideal-cache
baseline $28.15 exceeds it. Ordinary uncached totals would be about **$155.68–$164.48** at modeled
25–50% output use. Downstream context/usage and paper-level repeat-validation needs remain uncertain;
these totals do not prove a runnable pipeline. The absolute configured run cap remains $35, separate
from the $150 batch gate. No budget was raised or scientific check removed to make the figures fit.

## Verification and remaining limitations

All three optimized workloads finish COMPLETE with **zero pending mandatory items and zero
unaccounted findings**. The comparison script asserts exact before/after equality of every detailed
finding, context, source entity attribute, normalized mandatory source unit, approved framework and
global PLAN evidence/context index. Alias metadata and the eliminated duplicate source copy are the
only intentional normalization differences. Retrieval remains available outside packets and the
independent fixture exercises both allowed rounds; its 20 provider-counted requests all fit limits.

Regression tests cover:

- All-candidate packing without spill, bounded consolidation and one owner per mandatory item.
- Source and theme identity preservation, identical gap counts and registry-wide independence.
- Supplied cross-group contradictions **and** shared-study issues retained after consolidation.
- Source-only/ordinary output gap limits, atomic truncation, successful resume without duplication,
  and invalidation when the consolidation setting changes.
- Existing eligibility, appraisal, attribution, constraints, CP_SYN, stale-input, context-admission,
  completion and A10 scoping tests remain in the full suite.

`litreview check` passed without --ping/--apis; no paid health checks ran. The full suite passed
**259 tests**; `git diff --check` passed.

**Remaining limits:** mocked tests preserve supplied scientific relationships; they do not establish
live contradiction detection, interaction interpretation, semantic entailment or evidence-omission
recall. Shared study/cohort labels remain explicit identifiers with independence null; no new identity
resolver was introduced. The replicated benchmark still contains outside-selected thematic references
in its partial final cycles and is not 120 unique papers. Dense source-only packets require a small
scientist-adjudicated paid pilot to verify 16-unit completion within the unchanged cap. Such a pilot
requires separate authorization and was not run. If it shows truncation or interpretation loss, reduce
source-only packing density or justify output changes from observed evidence; never drop analyses.

**Freeze recommendation:** freeze the existing package contract for A10 work, with this conditional
structural acceptance. Do not certify production science or full-pipeline affordability. Further A07
architecture work is not justified by these measurements; prioritize a representative clean fixture,
remaining-stage cost calibration and the authorized semantic pilot before paid scale-up.

Reproduce baseline capture/counts with `python -B tests/a07_validation_audit.py --output-dir
docs/a07_efficiency`; `--recount` reuses exact requests; `--retrieval` exercises retrieval. Run
`python -B tests/a07_efficiency_report.py` for the comparison. `--count-prefix` makes only two free
input-count probes. Artifacts are in [a07_efficiency](a07_efficiency/), including exact compressed
requests, provider counts, per-group distributions, cache calibration and scientific equality checks.
Prior audit artifacts and all historical runs were left untouched.
