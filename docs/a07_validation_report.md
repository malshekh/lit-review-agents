# A07 final validation and scalability audit

Verdict: **CONDITIONAL PASS for the tested structural workloads after one minimal correction.**
Not accepted for an unattended 120-paper scientific synthesis or a $150 complete-pipeline run.
Date: 2026-10-29. Configured model: `claude-opus-5`, effort `high`.

A structural PASS requires every simulated request to fit its configured limits, complete global
evidence accounting, enforce scientific eligibility, and preserve cross-group relationships. It does
not establish that a live LLM will correctly discover, interpret, or synthesize those relationships.

## Method and reproducible evidence

No paid generation, research agents, manuscripts, commits, or historical-data changes were made.
Production request builders generated mocked PLAN/GROUP/RECONCILE/FINAL sequences for 40/80/120
replicated papers. All **320 baseline requests**, plus **20 requests** exercising both allowed retrieval
rounds on an independent four-paper fixture, were counted successfully by Anthropic's free endpoint.
An initial sandbox connection failure was retried with approved network access. An earlier successful
baseline count omitted effort; the authoritative saved count includes the actual `output_config`.

Evidence files under [a07_validation](a07_validation/):

- `measurements.json`: each provider count, output allowance, byte bound, request hash, workload and coverage results.
- `requests.jsonl.gz`: exact serialized generation parameters, built but **never sent to generation**.
- `groups_40.json`, `groups_80.json`, `groups_120.json`: every GROUP's findings, theme, mandatory items and input count.
- `summary.json`: aggregate distributions and explicit other-stage cost assumptions.
- `retrieval/`: independent two-round retrieval requests and measurements.

Reproduce with `python -B tests/a07_validation_audit.py`; it makes only free count calls, but takes
several minutes to rebuild mock jobs. `--recount` reuses saved requests. `--retrieval` counts the
independent retrieval scenario. `python -B tests/a07_validation_summary.py` regenerates summaries
without network access. Generation responses are mechanical fixtures, not scientific judgments.

## Capacity: provider input counts and separate allowances

The provider endpoint measures input, not future output or thinking. It supports system/messages,
tools and output configuration; these requests contain one user message, a cached system block,
effort `high`, no API tools and no prior conversational history. Retrieval is application-level JSON,
not a tool definition. Each retrieval request includes accumulated detailed findings. No previous
assistant responses or thinking blocks are carried forward. See `request_body` and `message_params`
in [anthropic_client.py](../src/litreview/llm/anthropic_client.py#L33).

Thinking shares `max_tokens`; it must not be added again on top of that allowance. Current-turn
thinking is billed as output. Counts also do not measure real cache hits or billed usage. Official
references: [token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting),
[thinking and limits](https://platform.claude.com/docs/en/build-with-claude/thinking), and
[Opus 5 specifications](https://platform.claude.com/docs/en/models/opus-5/overview): 1M context, 128K
maximum output. The tested 4K/12K/6K/6K per-mode allowances are below that output maximum.

| Papers | Findings | Mandatory items | Calls PLAN/GROUP/RECONCILE/FINAL | PLAN provider input | PLAN byte input bound | PLAN input + allowance, provider / bound | FINAL provider input |
|---|---:|---:|---|---:|---:|---:|---:|
| 40 | 642 | 347 | 1/62/4/1 | 146,639 | 313,223 | 150,639 / 317,223 | 40,197 |
| 80 | 1,353 | 474 | 1/94/7/1 | 287,568 | 598,715 | 291,568 / 602,715 | 64,934 |
| 120 | 1,996 | 688 | 1/136/11/1 | 416,539 | 858,995 | 420,539 / 862,995 | 92,253 |

All baseline packages completed with zero pending mandatory items and zero unaccounted findings.
Every captured baseline input plus its output allowance fits both the 900,000 admission ceiling and
the documented model window. Every mocked visible response fits the runtime's conservative output
byte check; actual live response length and thinking use remain unknown.

**PLAN clarification confirmed through the builders:** `offline_tokens(system) +
offline_tokens(user_parts(payload))` produces **858,995 input-bound units** for the rebuilt 120-paper
PLAN. `message_params` receives **max_tokens=4,000** from `RegistrySynthesisJob.limit("PLAN")` and the
orchestrator's mode override. Admission explicitly adds them: **862,995**, leaving **37,005** below
900,000. The provider-counted equivalent is **420,539**, leaving **479,461**. The 48K allowance is not
used by this execution path. References: [orchestrator.py:1224](../src/litreview/orchestrator.py#L1224),
[synthesis_bounded.py:67](../src/litreview/synthesis_bounded.py#L67),
[synthesis_bounded.py:91](../src/litreview/synthesis_bounded.py#L91).

| 120-paper operation | Calls | Total provider input | Largest provider input | Total output allowance, including thinking |
|---|---:|---:|---:|---:|
| PLAN | 1 | 416,539 | 416,539 | 4,000 |
| GROUP | 136 | 3,141,588 | 47,829 | 1,632,000 |
| RECONCILE | 11 | 889,034 | 81,294 | 66,000 |
| FINAL | 1 | 92,253 | 92,253 | 6,000 |
| Total | 149 | 4,539,414 | — | 1,708,000 |

The independent retrieval workload completes after LOOKUP0/LOOKUP1 requests and a final LOOKUP2
response for every GROUP and RECONCILE. All 20 requests have provider counts and fit their allowances.
This tests two-round protocol handling and a supplied shared-study issue; it does not demonstrate
that a live model will know when or what to retrieve. It is not a 120-paper maximum-detail stress run.

## Why 136 GROUP calls?

The registry first creates **86 theme packets** for 1,996 findings, then **50 UNMAPPED mandatory-source
packets**. Of the 136 packets, **49 have zero findings**, and one overflow packet repeats two paper
anchors. There are therefore 1,998 finding occurrences across packets, not 1,998 distinct findings.
The global registry retains 1,996 unique findings and does not claim independent replication.

| Findings per group | Number of groups |
|---:|---:|
| 0 | 49 |
| 2 | 1 |
| 6 | 2 |
| 7 | 1 |
| 15 | 1 |
| 20 | 1 |
| 23 | 2 |
| 24 | 79 |

Mandatory-item occupancy: 0 items in 2 groups; 1 in 8; 2 in 17; 3 in 24; 4 in 16; 5 in 12;
6 in 2; 7 in 2; 8 in 53. GROUP input ranges **7,011–47,829 tokens**, median **27,148**.
At 40/80 papers there are respectively 31/34 finding-empty groups and 32/35 UNMAPPED groups.

These empty groups still carry mandatory scientific source records; deleting them would remove
evidence obligations. The 136 calls are necessary for *this algorithm and fixture*, not proven
scientifically necessary. Many thematic records cannot map to synthetic T1–T8, so source records
overflow regardless of space in finding packets. The suspected first-candidate-only packing problem
exists in `EvidenceRegistry.packets` at [synthesis_registry.py:136](../src/litreview/synthesis_registry.py#L136),
but **zero actual overflow items** had another non-full packet with matching finding anchors in this
120-paper workload. Do not attribute the measured fragmentation to that unobserved scenario.

The fixture copies whole 28-paper cycles of thematic records even for a partial final cycle:
[a07_capacity_simulation.py:55](../tests/a07_capacity_simulation.py#L55). Those records reference **16/4/20
outside-selected paper IDs** at 40/80/120. This inflates thematic obligations and makes call counts
unrepresentative of a clean 120-paper corpus. Historical artifacts were not corrected or overwritten.
This is a demonstrated benchmark defect, not evidence of missing production papers.

RECONCILE's 11 calls follow 325 mocked propositions in pages of 32; each repeats the global index.
Its 889K aggregate input buys global visibility, not 11 independent global discoveries. GROUP output
allowances dominate potential cost. Repeated system text is cacheable, while per-packet payloads are
not. Safe recommendations: first repair the evaluation corpus mapping; then measure whether related
source records can share already eligible packets. Preserve all source units and reconciliation.
Do not remove source-only groups or reduce global visibility merely to save calls. No grouping redesign
was implemented during this audit.

## Scientific integrity, human oversight and recovery

The original full suite passed **243 tests**. Added independent adversarial cases test detailed
context retention, cross-theme shared identity, unrelated reconciliation anchors, interrupted resume,
changed framework/context/finding rejection, bounded truncation and the current A10 scoping interface.
Final full-suite verification: **251 passed in 14.12 seconds**, with cache writing disabled and a
workspace-local temporary directory. `git diff --check` passed. No other agent implementation changed.

| Requirement | Evidence and result | Limit of evidence |
|---|---|---|
| Mandatory accounting | All replicated jobs COMPLETE; pending/unaccounted zero; bounded missing-coverage test blocks FINAL | Accounting includes explicit unused dispositions; it does not prove adequate scientific use or justify an omission |
| Eligibility | Existing `test_evidence_eligibility.py:135` and `test_synthesis_bounded.py:146` reject forbidden roles atomically; appraisal test at :246 preserves attribution | Cannot judge whether an otherwise allowed assertion overstates the biology |
| Doses/units/arms/models | Independent fixture preserves distinct 1 uM/1000 nM labels, DSF+Cu/DSF-alone arms, cellular/animal systems and model labels in full context qualifiers | Does not establish equivalence conversion or scientific comparability |
| Synergy/antagonism | Independent source records retain different predicates; full registry details remain available | Mechanical model does not interpret interaction endpoints or discover antagonism |
| Hedges/secondhand claims | Existing bounded appraisal test retains REPORTED_BY_OTHERS, attribution and A06 rationale | Metadata preservation does not prove final prose keeps the hedge |
| Cross-group contradictions | Existing bounded test at :186 supplies both sides and the issue; retained limitations attach to affected propositions | **Preservation, not independent detection**. The no-conflict mock can complete even when conflicting inputs exist |
| Shared studies | Independent two-theme fixture: 2 papers, 1 explicit study ID, shared cohort, independent count null; retrieval fixture preserves supplied SHARED_EVIDENCE issue | No automatic study-alias graph or experiment identity resolution; unknown identities remain unknown |
| Retrieval | Existing external-theme retrieval test at :166 and 20 provider-counted two-round requests | No live-model retrieval recall, no maximum-detail 120-paper retrieval calibration |
| Human approval | CP_SYN stops GROUP; exact fingerprint and explicit framework-retention decision required; themes/subthemes/distribution/emerging findings/proposals exposed | Requires a scientist to inspect the JSON where compact review omits detail |
| Stale resume | Existing prompt/schema/settings/tamper tests plus new framework/context/finding-change tests reject stale state | Not an OS/power-loss fault-injection campaign |
| Interruption | New test preserves all accepted GROUP outputs when reconciliation interrupts; resume performs no repeated PLAN/GROUP calls | Unbilled versus billed lost responses still require manual usage reconciliation |
| Truncation | New bounded AgentError test leaves every mandatory item pending and no accepted propositions; provider stop check in base.py:145 precedes parsing | No paid truncated generation was induced |
| CP3/A08 gating | Job completion checks, orchestrator :1278, CP3 approval checks :234 and existing integration tests reject incomplete packages | Does not establish downstream 120-paper context capacity |

**Confirmed defect and minimal correction:** prior reconciliation checked that issue anchors were
retrieved, but not that they belonged to the referenced propositions. A scripted issue citing a
different paper's finding was accepted and the new rejection test failed. Added a four-line check in
`RegistrySynthesisJob.reconcile`, [synthesis_bounded.py:287](../src/litreview/synthesis_bounded.py#L287):
each referenced proposition with finding evidence must share an anchor with the issue. The adversarial
test then passes. External counterevidence can still be included alongside those anchors. This is a
provenance check, not entailment detection. Source-only propositions still require human/semantic
checking; the fix does not invent finding links for them.

Registry independence is deliberately conservative: `independent_studies` and
`independent_datasets_or_cohorts` remain null. `study_id or nct_id` and `dataset_id or cohort_id` count
explicit labels, not deduplicated scientific units ([synthesis_registry.py:72](../src/litreview/synthesis_registry.py#L72)).
Multiple aliases for one study can appear as distinct labels; experiment IDs are not modeled. These
counts must never become a replication count downstream. No production change to identity semantics
was made under this validation-only task.

## Cost: measurements versus assumptions

**Measured billed generation cost: none; generation was not run.** The following are modeled costs
using measured input-token counts and configured prices, independently matched to the official
[Opus 5 price table](https://platform.claude.com/docs/en/models/opus-5/overview): $5/M input,
$25/M output, $10/M one-hour writes, $0.50/M cache reads.

| 120-paper A07 scenario | Modeled cost | Assumptions |
|---|---:|---|
| Input alone | $22.70 | All input uncached; no generated output |
| Baseline planning band | $33.37–$44.05 | Total visible output plus thinking uses 25–50% of allowances; no retrieval/retry/cache savings |
| Revised old illustrative formula | $37.90 | Measured input; fixture output byte bound /3, plus thinking at 25% of allowances |
| Every output allowance consumed | $65.40 | Measured baseline inputs; no retrieval/retries; all output including thinking at caps |
| Every input billed as 1h write, full outputs | $88.09 | Deliberate overstatement: only system is actually cache-marked |
| Finite adverse operating scenario | About $90 plus retrieved-detail input | 30% of GROUP/RECONCILE calls need one extra round and 10% of baseline calls incur another paid attempt; all responses at caps; uncached inputs. Proportional $65.40 x 1.4 = $91.56 is a coarse approximation, not measured usage |
| Retrieval-heavy stress | $190.60 plus retrieved-detail input | All 147 GROUP/RECONCILE operations consume both extra rounds: 443 calls; baseline-sized input and all output caps repeated. Not a realistic-output prediction or an unlimited-retry bound |

The practical baseline band is sensitivity analysis, not empirically calibrated live Opus output.
Live high-effort thinking can exhaust a cap before valid JSON completes. Failed attempts still cost
money, and conservative byte-based response rejection may stop output that fits the actual tokenizer.
No finite worst-case bill is claimed for arbitrarily repeated manual resumes.

The old **$33.60** assumed three bytes per input token; actual baseline input is 4,539,414 versus that
assumption's 3,679,700, raising its same output formula to **$37.90**. The old **$153.09** treated the
11,039,099-byte input bound as tokens, billed all of it as one-hour writes, and consumed all output caps.
Replacing that byte bound with provider input counts yields **$88.09** under the same deliberately
overconservative cache treatment, or **$65.40** with ordinary uncached input.

Only the small repeated system prefix is cache-marked. Its byte bound is 11,359 per call, much smaller
than the whole payload. Do not apply cache-read discounts to the 4.54M aggregate input. Actual hit rate,
TTL refreshes and cacheable-token count were not measured. A07 is interactive; A05/A06 batch discounts
must not be applied to A07. Every accepted/failed attempt needs its own reservation; unknown billing
leaves the reservation held. Output caps and fresh per-call reservations limit dispatch, not all future
retry requests. See [orchestrator.py:1232](../src/litreview/orchestrator.py#L1232).

### Does A07 have an allowance inside $150?

Reproducing the existing other-stage scenario gives:

| Other stages/assumption | Projected cost |
|---|---:|
| Discovery/pre-CP2 allowance | $4.00 |
| A05 + per-paper A06, historical means with /2 batch approximation | $42.65 |
| Repeat A06, historical p90 /2 on every paper | $25.35 |
| Thematic A06, historical mean and theme density | $14.73 |
| A08 | $2.96 |
| A09 | $3.80 |
| A10 | $25.56 |
| A11 | $3.28 |
| A12 | $3.04 |
| Other-stage total | **$125.36** |
| Remaining A07 allowance | **$24.64** |

That allowance is below the modeled $33–$44 baseline band. Adding that band gives approximately
$158.73–$169.40 for this scenario; those totals are **not a proven runnable pipeline**. The downstream
projection still assumes large A08/A10 inputs and is not a context validation. If repeat A06 were
unnecessary for all papers, the scenario would free $25.35 and give A07 approximately $49.99; that is a
sensitivity calculation, not authorization to remove scientific checks. Recompute with actual selection,
instability outcomes, batch probes, downstream redesign counts and contingency before spending.

The configured absolute run cap is still **$35** (`config/pipeline.yaml:12`); the $150 batch gate does
not raise it. As currently configured, the framework cannot spend $150 on a full run. No cap changed.

## Priorities and A10 interface readiness

| Priority | Finding, evidence and action | Status |
|---|---|---|
| P0 before paid scale-up | Other-stage scenario leaves $24.64, below A07 baseline; $35 absolute cap remains. Re-project the actual full pipeline and set an explicitly approved operating budget before dispatch (`pipeline.yaml:12`, `cost_projection.py:97`) | Demonstrated budget mismatch; no affordability claim |
| P1 | Reconciliation accepted unrelated retrieved anchors (`synthesis_bounded.py:279`). Require referenced-proposition anchors | Fixed narrowly; regression added |
| P1 | Replication copies outside-selected theme evidence (`a07_capacity_simulation.py:55`). Build a corpus-consistent benchmark before treating 149 as the expected real-run count | Demonstrated fixture defect; historical records unchanged |
| P1 | Semantic detection untested: reconciliation can return no issues without retrieving detail (`synthesis_bounded.py:271`, `synthesis_registry.py:214`). Evaluate contradiction/overlap recall against a scientist-adjudicated set | Unmeasured live reliability; not a detected semantic model failure |
| P1 | Explicit IDs are not entity-resolved study/cohort/experiment identities (`synthesis_registry.py:66`). Preserve null independence; adjudicate aliases and shared experiments before replication claims | Known interface limitation |
| P1 | Live JSON completion and thinking/output distribution unmeasured; byte output check can reject early (`synthesis_bounded.py:104`). Measure a small paid pilot before changing allowances | Safe stopping risk; no observed live truncation in this audit |
| P2 | First-candidate-only assignment can fragment other datasets (`synthesis_registry.py:136`); none of the measured overflow items had a non-full anchor alternative | Hypothetical here; retain until a representative counterexample justifies correction |
| P2 | Full global proposition index repeats in 11 reconciliation calls (`synthesis_bounded.py:259`) | Measured cost; preserve visibility unless an equally complete alternative is validated |

A07 is **ready to provide a provisional input contract for the upcoming A10 redesign**, not an
end-to-end readiness certification. The assembled package exposes stable proposition IDs, evidence
roles, finding IDs, citations, full contexts, qualifiers, constraints, reconciliation limitations,
source-item aliases, framework fingerprints and unused findings (`synthesis_bounded.py:355`). An added
integration test confirms current A10 scoping follows bounded proposition IDs to the correct detailed
findings and retains the rest in its contradiction index (`verification_scope.py:75`).

A10 acceptance must additionally prove handling of source-only propositions, gaps, UNMAPPED
propositions, shared-study identity, appraisal/hedging, contradictions and every claim-bearing element.
Existing A10 scope is not a demonstration that the full 120-paper package fits its model window or
that semantic entailment judgments are accurate. Do not change A10 in this task.

Minimal next steps: correct the evaluation workload; recalibrate remaining-pipeline costs; then, with
separate paid authorization, evaluate a small real-model sample against scientist-adjudicated cases.
Include both an undisclosed contradiction and a supplied contradiction, shared-study cases, interaction
direction and context mismatches, appraisal-only claims and retrieval-needed evidence. Measure discovery
recall separately from preservation, false contradiction rate, evidence-role violations, qualifier loss,
retrieval recall, valid-JSON completion, output/thinking usage and billed cost. P0 scientific-role violations
must be zero; a scientist must decide acceptable discovery/interpretation performance before scale-up.
