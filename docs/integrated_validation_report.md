# Integrated A07–A10 validation and 120-paper assessment

**Overall verdict: FAIL for the complete pipeline under the current configuration.**
**A07→A10 structural integration: CONDITIONAL PASS after two minimal corrections.**
The distinction matters: bounded synthesis/verification works on the evaluation inputs, but an
upstream provenance counterexample, downstream context exposure and the actual financial gates
prevent a defensible full-pipeline PASS. No live-model scientific reliability is established.

## Scope and evidence

This audit reviewed the three earlier reports, production synthesis/verification builders, registry,
retrieval, orchestration, schemas, prompts, checkpoints, budget monitor and projections. It ran the
current A07 job and A10 job with scripted responses on the replicated 120-paper workload, captured
production A08/A09/A11/A12 stage payloads, and used Anthropic's **free input counter** for the saved
writer/editor stress requests. No generation endpoint, research execution, manuscript generation,
historical-run modification or commit was performed. The prose fixture is repetitive evaluation text.

New evidence is in [integrated_validation](integrated_validation/):

- `a10/measurements.json` and `a10/requests.jsonl.gz`: current exact requests, bounds and coverage.
- `handoffs.json`, `handoff_requests.jsonl.gz`, `handoff_provider_counts.json`: production stage
  builders exercised with a deliberately expansive, synthetic full-proposition plan.
- `costs.json`: telemetry, explicit scenarios and the current runtime projection.

Reproduce offline with `python -B tests/integrated_capacity_audit.py` and
`python -B tests/integrated_cost_audit.py`. The first creates temporary run/job state and new audit
artifacts, not a research run. Provider counts are saved observations; these two scripts do not call APIs.
The existing [A07 provider measurements](a07_efficiency/measurements.json) are reused, not represented
as new counts. A07 implementation, prompts and schemas were unchanged by this audit.

## Confirmed integration corrections

1. **Incomplete synthesis could enter direct verification.** CP3/A08 already checked completion,
   but `Run._verification_registry` did not. It now rejects explicit non-COMPLETE status,
   unaccounted findings and incomplete mandatory coverage before reading findings or dispatching.
   See [orchestrator.py](../src/litreview/orchestrator.py:1507) and the three counterexamples in
   [test_integrated_verification.py](../tests/test_integrated_verification.py:12).
   Status-less legacy packages remain supported; this is not retroactive proof of their completeness.
2. **Proposition qualifications could disappear in LOCAL payloads.** `VerificationJob.bound`
   followed plan references for findings/roles but selected propositions only under initial IDs.
   Its field allowlist also omitted `context_qualifiers` and `evidence_qualifiers`. It now follows the
   reference closure with cycle protection and retains complete bound propositions. Source items
   reached through those propositions consequently remain available too. See
   [verification_job.py](../src/litreview/verification_job.py:201) and the indirect B1→P1 regression
   [test](../tests/test_integrated_verification.py:20), including dose/arm/model, hedging, secondhand
   attribution, shared-cohort limitation and reconciliation IDs.

An initial ad hoc rerun decoded the UTF-8 test source using the Windows default encoding, corrupting
its proposition delimiters. This was an audit-harness error, not a repository fixture defect. The final
integrated harness reads UTF-8 explicitly; the existing helper is unchanged and now has an additional
word-count/binding regression. Historical measurements were not overwritten. The final new fixture
has 5,000 body words and real bindings; the intermediate malformed-tag result was superseded.

## Capacity and evidence accounting

| Operation | Calls | Input measurement | Output allowance | Largest request / headroom |
|---|---:|---|---:|---|
| A07 PLAN | 1 | 416,714 provider-counted input | 4,000 | Byte bound + cap 863,546; 36,454 below 900k |
| A07 GROUP | 111 | 2,905,938 provider input total | 1,332,000 total | Largest provider input 42,284 |
| A07 RECONCILE | 11 | 889,123 provider input total | 66,000 total | Largest provider input 81,316 |
| A07 FINAL | 1 | 92,275 provider input | 6,000 | Byte bound + cap 209,005 |
| A10 initial LOCAL/GLOBAL | 42 / 23 | 12,965,188 summed UTF-8 bounds | 604,000 total | Max input + cap 239,074; 926 below 240k |
| A10 one-sentence edit | 1 / 23 | 5,228,585 summed UTF-8 bounds | 194,000 total | Max input + cap 237,404; 2,596 below 240k |

A07's 124 calls replace the earlier 149-call scenario. The original pre-optimization PLAN was
858,995 input-only + 4,000 output = 862,995, leaving 37,005. The current optimized request is slightly
different (859,546 byte input bound); do not substitute the original number for the current request.
Byte bounds include conservative framing; they are not provider token measurements. The provider
counter measures input, including supported definitions, not future output or thinking. Counting is
free and does not demonstrate cache hits. See [Anthropic token-counting documentation](https://platform.claude.com/docs/en/build-with-claude/token-counting).

The new run assembles 324 propositions and 572 gaps from 1,996 findings and 688 mandatory items.
The inherited A07 accounting has no pending mandatory items or unaccounted findings. A10 reviews
257/257 candidate sentence/cell occurrences, including 53 table occurrences; all 2,892 global index
entries and all 1,996 findings are accounted for in both versions. There are zero reconciliation
issues in this baseline **because its model fixture supplies none**, not because science is consistent.
The body fixture cites all 120 paper IDs, but its 12-row comparative table and repeated vocabulary do
not establish the ability to produce a scientifically useful 120-paper comparison or critical prose.

The corpus repeats the historical 28 papers; it is not 120 independently sampled scientific studies.
Whole-cycle theme replication also introduces references to 20 outside-selected paper IDs in the last
partial cycle. Those administrative source units inflate some GROUP/gap work. Preserve the existing
artifacts but correct this fixture construction before treating group distributions as representative
of a real 120-paper corpus: [a07_capacity_simulation.py](../tests/a07_capacity_simulation.py:29).
Do not remove sparse groups merely to lower cost: some carry mandatory source-only evidence.

### Downstream context is not validated end to end

Production builders were intercepted before providers, using a plan that carries all 324 complete
propositions. This is a stress plan, not an A08-generated plan or the sole valid representation.

| Builder | Input byte bound | Provider-counted input | Configured output cap |
|---|---:|---:|---:|
| A08 outline | 4,869,929 | Not measured for its OpenAI model | 32,000 |
| A09 initial writer | 2,627,535 | 1,122,050 (Opus 5) | 64,000 |
| A11 critique | 7,222,324 | Not measured for its Kimi model | 32,000 |
| A12 LINE edit | 2,680,901 | 1,148,533 (Sonnet 5.5) | 64,000 |

The editor's input alone exceeds the documented 1M context window, before its output allowance.
See [official model limits](https://platform.claude.com/docs/en/models/overview).
The writer also exceeds the repository's assumed 1M window. Counting is not a generation attempt;
no claim is made about an observed provider generation rejection. The byte bounds for OpenAI/Kimi
alone cannot establish actual token overflow. No free model-specific counts were obtained for them.

This demonstrates an unguarded oversized handoff, not inevitable overflow for every compact plan.
`stage_outline` sends the entire package; A11 sends package, plan and manuscript. A09/A12 depend on
the plan. Their generic dispatch lacks the A07/A10 request-admission safeguard:
[orchestrator.py](../src/litreview/orchestrator.py:1419),
[stage_draft](../src/litreview/orchestrator.py:1612),
[stage_review_loop](../src/litreview/orchestrator.py:1631),
[stage_finish_edit](../src/litreview/orchestrator.py:1660),
[base.run_agent dispatch](../src/litreview/agents/base.py:104).
The A08 prompt requires adjacent qualifications and a self-contained writer plan, but its example
ordered-item schema is thin; the top-level schema does not enforce those scientific fields.
See [A08 prompt](../prompts/agents/A08-OL_Outline.md:92) and
[A08 schema](../schemas/A08-OL.schema.json:47). A compact, qualification-preserving plan must be
measured before claiming full-pipeline capacity. The stress plan is not a forecast of actual A08 output.

## Integrity, recovery and human oversight

| Safeguard / adversarial case | Demonstrated result and limit |
|---|---|
| Complete propositions, indirect plan bindings, source limitations | Full LOCAL proposition equality after correction; source items retained. Does not prove prose respects them. |
| Cross-theme synergy/antagonism, 1 uM/1000 mM, hedging and secondhand attribution | Original details, quantities, spans and contexts remain retrievable in the new independent fixture. No model discovers the mismatch. |
| Shared studies/cohorts across groups | Two publications in different themes yield one known shared study; independence remains unknown. Explicit IDs deduplicate globally; aliases and unidentified overlapping experiments are not resolved automatically. |
| Contradictions across groups | Existing reconciliation fixture requests both sides and supplies contradiction/shared-evidence issues; limitations survive assembly. This proves preservation and validation, not discovery. |
| Incorrect doses, unsupported mechanism/clinical claims, misattribution | Existing A10 adversarial tests supply DEFECT verdicts and exercise enforcement. They do not demonstrate entailment accuracy. |
| Ineligible and appraisal-only evidence | Forbidden roles block; each appraisal occurrence needs a preservation judgment; promotion blocks. The preservation judgment is still supplied by a model. |
| Uncited, repeated and table claims | Inventory assigns distinct occurrences, includes row context and requires verdict coverage. Scientific versus NON_SCIENTIFIC classification is semantic; checking ten dimension names is not proof they were checked correctly. |
| Retrieval outside current packet | Existing A07 cross-theme and A10 uncited-conflict tests exercise targeted retrieval and bounded exhaustion. A request cannot silently fabricate an evidence ID. |
| Interrupted/truncated/invalid work | Existing tests reject partial acceptance, tampered caches and incomplete global review; valid local work resumes without redoing accepted locals. No live truncation rates measured. |
| Revisions and stale approval | Text changes rerun affected LOCAL and all GLOBAL pages; policy/evidence changes invalidate dependencies. Metadata-only changes can reuse scientific results under a new version fingerprint. |

References: [registry identity/details/retrieval](../src/litreview/synthesis_registry.py:66),
[A07 assembly](../src/litreview/synthesis_bounded.py:360),
[A10 LOCAL enforcement](../src/litreview/verification_job.py:282),
[global pages/run](../src/litreview/verification_job.py:351),
[adversarial tests](../tests/test_verification_job.py:68),
[reconciliation fixture](../tests/test_synthesis_bounded.py:186),
[new integration tests](../tests/test_integrated_verification.py:20).

CP_SYN requires the exact planning fingerprint and explicit retention of the approved framework;
CP3 rejects incomplete synthesis. These are meaningful human gates, but approval of a compact plan
is not a review of every scientific relationship. A11 cannot override BLOCKING A10 findings;
major/blocking LINE findings halt before proof; final export independently requires current complete
approval without major/blocking defects. See [checkpoints](../src/litreview/checkpoints.py:224) and
[release gates](../src/litreview/orchestrator.py:1631). Status-less legacy synthesis remains a bounded
validation gap. Exported citation numbering is not verification that bibliographic identities and
every source attribution are correct; no live reference-resolution check was executed in this audit.

## Why 24 calls after one sentence changes?

The changed sentence invalidates one LOCAL packet. Every GLOBAL page contains the entire manuscript
and occurrence index, so its cache key changes: all 23 global pages rerun. This is required by the
current global consistency contract, rather than evidence that the local cache is ineffective.
The earlier 61 initial calls become **65** after retaining full proposition qualifications; four extra
LOCAL packets are the cost of the corrected payload, not a proposed architectural expansion.

Minimal safe opportunities are provider prefix caching where actual cache telemetry confirms reuse,
and deferring verification until an editing pass is complete. Neither changes coverage or release
identity. Reusing old global judgments solely because a sentence changed “slightly” would weaken
consistency. A delta-based global verifier would need new scientific dependency validation and is
not a minimal proven optimization. Retain the 23 global calls until evidence supports an alternative.

## Full-run financial assessment

All dollar figures below are **modeled**, except explicitly identified historical billed telemetry.
Current repository prices are used; no live generation/output/reasoning/cache billing was measured.
A10 assumes three UTF-8 bytes per input token and 25–50% use of output caps, **including reasoning**.
Thinking is not added again. A07 uses saved provider-counted input and modeled output, yielding
$30.32–39.12 without cache savings. Output-cap sufficiency remains uncalibrated.

| Agent / operation | Planning baseline USD | Evidence / uncertainty |
|---|---:|---|
| A02 scope | 0.74 | Historical 5 calls; model/routing and future revisions may differ |
| A03 search planning | 0.96 | Historical 3 calls; not a new 120-paper retrieval measurement |
| A04 screening | 0.37 | Historical 18 calls; future search pool size unknown |
| Extra pre-CP2 allowance | 1.93 | Brings discovery allowance to $4; assumption |
| A05 extraction | 28.56 | Historical attempts scaled 28→120, then halved for batch eligibility |
| A06 initial paper validation | 14.09 | Same scaling/batch assumption |
| A06 instability repeats | 25.35 | Historical p90, all 120 repeated, half-price batch assumption |
| A06 theme validation | 14.73 | Historical mean scaled to about 279 theme operations |
| A07 synthesis/reconciliation | 30.32–39.12 | Saved provider input, modeled output; zero baseline retrieval |
| A08 outline | 2.96 | Inherited projection; not measured full-corpus generation |
| A09 writing | 3.80 | Inherited 2-call projection; assumes 60k input/call |
| A10 initial | 10.15–11.66 | Current 65-call fixture; output 25–50% |
| A10 one small revision | 3.97–4.46 | Current 24-call fixture; output 25–50% |
| A11 critique | 3.28 | Inherited 2-call projection; context fit unresolved |
| A12 revisions/LINE/PROOF | 3.04 | Inherited 4-call projection; 60k input/call assumption |

At 25% A10 output, the compact-handoff planning baseline is **$144.25–153.05**, leaving
**+$5.75 to −$3.05**. The midpoint is approximately $148.65. This is an optimistic planning scenario,
not a reliable expected bill: downstream handoffs have not been shown to fit; first extraction probes
remain interactive; batching/corpus mix/attempt counts can differ. The extra $0.0007 versus the older
other-stage subtotal comes from recomputing raw telemetry rather than reusing rounded rates.

The $150 cap leaves **$36.07 for A07** after the other modeled stages and one A10 revision. A07's
$30.32–39.12 straddles that allowance. First verification plus five small edits instead yields
**$160.13–168.93**, before additional retrieval or paid failures. A mandatory final call can reuse
scientific caches if its exact payload is unchanged; actual editing commonly changes that payload.

A finite adverse scenario is **$370.65**: no batch discount for paper work/repeats, p90 theme costs,
A07 full output/write scenario $78.24, A10 first + five edits at all input-byte write bounds/full caps,
and inherited downstream projections. It is deliberately conservative, not an observed bill or an
absolute worst case. It excludes unbounded failures and expensive fallbacks. A 40% additional A07/A10
retrieval/retry exposure would add about $76.70. Ineligible batch items and fallback routes can make
this worse; A05's priced Opus fallback is approximately 2.5× its Sonnet rate before cache differences.

The old $33.60 illustrative and $153.09 conservative A07 figures were different token/output/cache
scenarios, not bills. The optimization report's $30.32–39.12 uses measured optimized input; neither
estimate finances other agents. Revised A10 also cannot be compared against the entire $150 alone.

Two decisive configuration issues remain:

- `run.spend_cap_usd` is **$35**, while `batch.gate_usd` is $150; the batch gate does not override
  the hard run cap ([pipeline.yaml](../config/pipeline.yaml:12)). The reference run already spent
  **$34.29193**, leaving about $0.708 under its configured cap, or $115.708 under a hypothetical $150.
  No reservations file/batch records were found for that reference run. A new simulation has no paid
  commitments. For a selected real continuation, add actual spent plus outstanding reservations;
  do not add historical spending to a fresh-run projection or assume future commitments are zero.
- The current production `downstream(..., 1996)` planning envelope returns **$5,492.64 A07** and
  **$158.34 A10 alone**. The former assumes far more groups, maximum propositions and retrieval;
  the latter 759 calls. These are pessimistic envelopes, not measured costs, but they are consumed by
  the gate and cannot be reconciled with a $150 execution approval simply by citing the audit baseline.
  See [projected_a07](../src/litreview/synthesis_registry.py:245),
  [downstream](../src/litreview/tools/cost_projection.py:115), and
  [batch gate](../src/litreview/tools/cost_projection.py:267).

Savings that preserve science: batch eligible A05/A06 work only after successful probes; preserve
accepted-call caches on resume; reduce unnecessary editorial passes; measure prefix cache hits.
The modeled batch saving on initial paper work is about $42.65 and on the all-paper repeat scenario
about $25.35 versus interactive prices. Those savings are already in the baseline and cannot be
subtracted twice. Earlier A07 prefix savings were only about $2.17 under ideal reuse. Do not count
cache savings, throughput or reduced scientific checking as guaranteed budget margin.

## Priorities and minimal next steps

| Priority | Confirmed defect or bounded gap | Required action / reference |
|---|---|---|
| P0 unresolved | A06 SUPPORTED can override failed deterministic provenance | Counterexample: invented span fails `span_check` but `_validated_findings` emits SUPPORTING. Enforce Gate 1 as an eligibility ceiling before a pipeline pilot. [test](../tests/test_integrated_verification.py:43), [join](../src/litreview/orchestrator.py:1003), [classify](../src/litreview/evidence.py:114), [Gate 1](../src/litreview/tools/span_check.py:60). No A06 changes applied. |
| P0 corrected | Direct A10 accepted explicit incomplete A07 | Completion/accounting guard added at [registry entry](../src/litreview/orchestrator.py:1507). Legacy status-less completeness remains unproven. |
| P1 corrected | LOCAL lost transitive propositions and qualifier fields | Full bound-reference closure and complete proposition payload, regression at [test](../tests/test_integrated_verification.py:20). |
| P1 unresolved | A06 may return COMPLETE without dispositions | Top-level schema requires no validations array; no exact input/output finding-set check at save. Missing entries become unresolved rather than supporting, but “complete validation” and evidence completeness are not established. [schema](../schemas/A06-SV.schema.json:40), [save](../src/litreview/orchestrator.py:769), [schema counterexample](../tests/test_integrated_verification.py:57). Require exact unique dispositions plus explicit unresolved reasons. |
| P1 unresolved | Downstream oversized handoffs lack admission | Measured editor stress request exceeds 1M input; compact production plan still unmeasured. Add admission and validate a qualification-preserving plan before the full run; no unrelated-agent redesign applied. |
| P1 unresolved | Budget gates cannot approve the advertised workload | $35 hard cap, extremely pessimistic production envelopes and narrow modeled $150 margin. Reconcile request-based projections and cap policy before paid execution; do not silently relax either. |
| P1 unresolved | Scientific discovery and output adequacy untested | Contradiction discovery, wrong-arm/dose/mechanism detection, NON_SCIENTIFIC classification, 10k/8k reasoning/output adequacy need blinded live evaluation. |
| P1 unresolved | Requested table differs from configured default | Configuration requests an evidence-map figure ([pipeline](../config/pipeline.yaml:96)). Set/approve the intended single comparative table before a real run; the audit table fixture does not change that preference. |
| P2 | Replication and conservative projection artifacts distort efficiency conclusions | Repair partial-cycle theme fixture and calibrate per-stage call distributions before interpreting empty-group counts or envelopes as real-corpus demand. |
| P2 | Global rechecks dominate small revisions | Measure actual prefix cache reuse first; retain full global review pending validated dependency-based alternatives. |

Before the next **pipeline** paid pilot: correct upstream Gate 1 and A06 completeness, retain the two
integration fixes, align the single-table specification, admit actual downstream requests, and produce
a gate-compatible run budget including actual commitments. No architecture replacement is needed.

A small **isolated scientific-reliability evaluation** is conditionally ready using manually checked,
gold-standard findings/registry inputs, independent of the defective upstream eligibility path.
Use 8–12 diverse papers, blinded positive/negative controls, shared-study cross-theme pairs, genuinely
unannounced contradictions and dose/unit/arm/mechanism perturbations. Require the model to find issues
without fixture-supplied verdicts; have a domain scientist adjudicate missed and false findings, citation
entailment, appraisal preservation and contradictory evidence coverage. Record input/output/reasoning,
cache classes, truncations and paid retries. Set a small explicit budget before executing it. This audit
did not execute or price-authorize that evaluation. Full-run publication quality remains unestablished.

Validation: **300 tests passed**, `python -B -m litreview check` passed without network probes, and
`git diff --check` passed. The new tests establish counterexamples and structural enforcement only.
A structural PASS requires every simulated request to fit configured limits, complete global accounting,
enforce scientific eligibility and preserve cross-group relationships; it does not establish that a live
LLM will discover, interpret or synthesize those relationships correctly. The full pipeline does not yet
satisfy that criterion.
