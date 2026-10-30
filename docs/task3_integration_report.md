# Task 3: integration, scientific integrity and 120-paper validation

**Verdict: CONDITIONAL PASS.** The merged framework processes 120 papers end to end in an offline simulation:
real A07 and A10 jobs, the bridge, sequential writing and final release, with scripted model outputs. No
evidence was lost or promoted, every element was accounted for, and no request exceeded its window.

Two conditions block a real 120-paper run:

- **Budget.** It does not fit $150 in any modeled scenario, and its baseline exceeds $200.
- **Scientific reliability.** It is untested: structural success is not scientific accuracy, and only a
  live-model evaluation can establish it.

Branch `task3-integration`, worktree `../lit-review-integration`. It contains:

- **Merge commit be77dd2.** Its parents are Task 1 (`ff27cb9`) and Task 2 (`20eaa8a`).
- **The Task 3 changes below, uncommitted.**

Neither original worktree was modified. No paid API call, research execution or manuscript generation took
place, and no historical run data was modified. Free provider endpoints used: Anthropic's token counter, and
the Anthropic, Moonshot and OpenAI model-metadata listings.

## 1. Files changed and conflicts resolved

The Git merge of the two tasks applied cleanly. `orchestrator.py` and `checkpoints.py` were auto-merged
(CP_LEDGER beside Task 1's fingerprint-bound CP3). A patch-based trial showed only a context clash at that
spot.

Integrating the two tasks exposed nine incompatibilities. Each is fixed, with a regression test:

| Incompatibility | Fix | Where |
|---|---|---|
| Task 1's package contract read a gap's `established_by` as proposition IDs; bounded A07 writes eligible **finding** IDs, so any finding-grounded gap would have blocked CP3 | Accept eligible findings (or legacy propositions); refuse unknown or ineligible ones | `scientific_validation.py` |
| A10 required a citation on every scientific occurrence, including the title and abstract, where the journal forbids references, so every compliant manuscript would stop at the line edit | Title, abstract and keywords exempt from citations only when the verdict names its evidence findings | `verification_job.py` |
| A10 records at most 24 evidence findings per occurrence; a sentence covering a grouped passage could bind 44 | The section gate refuses a sentence binding more than A10's limit (read from A10's schema); A09 prompt updated | `bridge.py`, A09 prompt |
| The bridge dropped Task 1's provenance metadata from packets | Packets keep the Gate 1 verdict, source and finding fingerprints, span-correction history, eligibility status and reason | `bridge.finding_record` |
| The bridge did not apply Task 1's package contract | Every bridge stage runs `require_package` against current evidence first | `orchestrator._bridge_inputs` |
| Table selection bookkeeping (status, counts, IDs) became text A10 had to verify | A10 and the export see a reader-facing table (columns, tagged rows, notes); the selection record is kept separately | `bridge.reader_table` |
| Resuming re-requested paid front matter and integration | Both cached by input fingerprint | `orchestrator._assemble`, `_integrate` |
| A07/A10 projection envelopes ($5,492.64 and $158.34 at 1,996 findings) admitted no workload | Calibrated forecasts (section 5) | `tools/forecast.py`, `cost_projection.py` |
| A Task 1 test needed the untracked historical run | Committed minimal fixture (R0030 F18, F20, F21 and one results section), extracted read-only with a check that Gate 1 outcomes match the full source | `tests/fixtures/r0030_gate1.json` |

Other changes:

- Kimi K3.1 Pro's window is recorded from Moonshot's endpoint.
- The measured batch factor (0.5) and instability-repeat share (0.643) are added to `records/cost_rates.json`.
- The `forecast` configuration key is new.
- New tools: `tests/integrated_pipeline.py`, `tests/full_run_forecast.py` and `tests/model_window_probe.py`.
- New tests: `tests/test_integrated_pipeline.py` and `tests/test_integration_safeguards.py`.

## 2. Scientific safeguards preserved

Each is tested through the bridge (`tests/test_integration_safeguards.py`, `tests/test_integrated_pipeline.py`).

- **Gate 1 cannot be overridden.** A finding that fails Gate 1, a BLOCKED_PROVENANCE finding, a QUARANTINED
  finding and one requiring revalidation are each kept out of packets, table rows and retrieval. CP3's contract
  refuses them first, and the bridge refuses them again.
- **Held evidence stays held.** In the 120-paper simulation, a SUPPORTED finding given a failed Gate 1 stayed
  held. No proposition, packet, table row or manuscript sentence used it.
- **Provenance and qualifiers survive.** Fingerprints, constraints, attribution, modality, context and
  eligibility reasons pass through the bridge unchanged. The original source quotation is supplied on
  retrieval. A10 refuses to verify from a finding without its source passage, which the simulation
  confirmed.
- **Approvals are bound to exact versions.** CP3 binds to the package fingerprint, CP_LEDGER to the plan and
  ledger, and A10 approvals to the text, plan and evidence version. A ledger edited after approval stops
  writing. A re-quarantined finding stops critique and editing. Final release requires current, complete
  verification.
- **Incomplete work cannot advance.** Incomplete synthesis, incomplete verification and failed section gates
  stop the run. Interrupted calls keep their reservations until reconciled.

## 3. Test results

```text
401 passed, 3 skipped (full suite, clean checkout)
40 passed, 0 skipped (the three run-dependent test files, run once against a temporary copy of the
           reference run; copy deleted, original byte-identical afterwards)
git diff --check: clean
litreview check: passes except the three API keys, because this worktree has no .env (by design)
```

The three skipped tests need whole-run artifacts (all extractions and validations, renormalization archives,
live A06 probes). They skip in a clean checkout and pass with the run present.

## 4. A08–A12 capacity

**Compact 120-paper fixture**, from the production builders (`docs/bridge_validation/measurements.json`):

| Agent | Model | Window | Largest request (bytes) | All fit |
|---|---|---:|---:|---|
| A08 | GPT-6.1 | 1,050,000 | 635,201 | yes (over the 272k pricing threshold, priced as such) |
| A09 | Opus 5 | 1,000,000 | 660,359 | yes |
| A11 | Kimi K3.1 Pro | 1,048,576 | 653,007 | yes |
| A12 | Sonnet 5.5 | 1,000,000 | 655,577 | yes |

**Integrated simulation, 120 papers** (`docs/integration_validation/simulation_120.json`):

| Agent | Largest request (bytes) | Window |
|---|---:|---:|
| A08 | 419,600 | 1,050,000 |
| A09 | 837,930 | 1,000,000 |
| A11 | 491,733 | 1,048,576 |
| A12 | 492,849 | 1,000,000 |

All requests fit. The largest A09 request leaves only 16% of the window in bytes. Its true token count is about
2.4 times smaller, by Anthropic's count. The first 120-paper attempt put every gap in one section; admission
stopped it before dispatch, as designed.

| Free token count (Anthropic) | Bytes per token |
|---|---:|
| Largest A09 section request | 2.384 |
| A09 front matter | 2.158 |
| A12 integration | 1.916 |

Every oversized request was stopped before dispatch:

| Oversized request | Input bound (bytes) | Window |
|---|---:|---:|
| A08 | 6,140,789 | 1,050,000 |
| A09 | 24,660,580 | 1,000,000 |
| A11 | 6,738,110 | 1,048,576 |
| A12, one unit | 6,750,510 | 1,000,000 |

## 5. Cost at 120 papers

The forecast is calibrated and planning only (`docs/integration_validation/forecast.json`). Measured inputs:

- A05/A06 per-paper and per-theme costs, batch factor and repeat share, from the reference run;
- A07 provider-counted input at 40, 80 and 120 papers;
- A10 production request bounds;
- A08–A12 from the bridge's builders.

Assumptions, stated in `pipeline.yaml -> forecast`: the share of each output cap used, bytes per token for
GPT and Kimi, retrieval and redraft frequency, critique outcomes and failed calls. A new run starts with
nothing spent and nothing reserved.

| Stage (120 papers, 47 full text) | Low | Baseline | High | Adverse |
|---|---:|---:|---:|---:|
| A02–A04 before CP2 | 2.07 | 4.00 | 6.00 | 8.00 |
| A05+A06 per paper (batch after one probe) | 43.38 | 43.38 | 71.07 | 139.51 |
| A06 instability repeats | 16.20 | 16.20 | 16.20 | 50.63 |
| A06 per theme | 14.76 | 14.76 | 25.84 | 25.84 |
| A07 synthesis | 31.81 | 45.49 | 63.77 | 198.58 |
| A08 outline | 0.57 | 1.36 | 1.54 | 1.79 |
| A09 writing | 14.16 | 27.79 | 48.67 | 167.68 |
| A10 verification | 27.00 | 47.05 | 86.98 | 423.23 |
| A11 critique | 0.74 | 1.97 | 2.36 | 2.84 |
| A12 editing | 2.24 | 4.16 | 5.33 | 8.53 |
| Failed and redone calls | 0.00 | 6.39 | 20.87 | 120.40 |
| **Total (USD)** | **152.94** | **212.56** | **348.62** | **1,147.03** |

The baseline plus the 30% uncertainty margin is **$276.33**. This is the figure the runtime gate uses.

Against the limits:

- **$150 is exceeded in every scenario**, including low.
- **$200 is exceeded at baseline.**

Largest paper count that fits, by the per-finding estimate:

| Limit | Baseline + margin | Baseline |
|---|---:|---:|
| $150 | 50 papers | 70 papers |
| $200 | 80 papers | 100 papers |

No variant fits at adverse.

Not added to the totals:

- **A05 fallback to Opus 5:** about 2.5 times A05's share, and requires approval.
- **Unbounded failures:** each one supersedes the projection before the next call.

In the simulation every stage stayed within its projection lines. For example, A10 made 90 calls against
1,170 allowed.

## 6. Remaining blockers

**P0**

- **A 120-paper run does not fit $150, and its baseline exceeds $200.** The fix is a researcher decision
  between reducing scope (about 50 papers fit $150 with margin) and approving the separate $200 increase,
  which still covers only about 80 papers with margin. No scientific check was removed to improve these figures.
- **`run.spend_cap_usd` is still $35, the pilot cap.** It was not changed. Any real run needs that cap set as a
  separate approved decision.

**P1**

- **Forecast assumptions.** Output use, retrieval and redraft rates, critique outcomes, and GPT/Kimi
  tokenization are unmeasured. The first real stages should recalibrate them.
- **A09 window margin.** The largest A09 request in the simulation used 84% of the window by byte bound. A
  real plan with a denser section would stop and need splitting.
- **Table rule awaits your confirmation.** "No claim without its contrary evidence" means 29 of 54 contrary
  findings appear only in the prose at 120 papers.
- **Run-dependent tests.** Three tests need the historical run and skip in a clean checkout.

## 7. Scientific capabilities still needing live-model evaluation

- Correct synthesis, contradiction discovery and reconciliation (A07).
- Allocation judgment (A08).
- Faithful prose that keeps every qualifier, hedge, dose, arm, model and attribution, and that renders grouped
  passages without merging claims (A09).
- Entailment and the numbers-to-arm match (A10), and critique quality (A11).
- Edits that preserve meaning (A12).
- Real bytes per token on GPT-6.1 and Kimi, and output use against the caps.

Every structural result here comes from scripted outputs. FixtureModel's propositions are mechanical, and
ScriptedVerifier supplies its verdicts rather than discovering them. None of it shows scientific accuracy.
