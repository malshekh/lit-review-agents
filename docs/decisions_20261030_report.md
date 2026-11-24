# Decisions of 2026-10-30: implementation and pre-spend report

No paid call has been made. Free calls only: PubMed/PMC retrieval of the five pilot papers. Branch
`task3-integration`, worktree `../lit-review-integration`:

- **Task 3 integration:** committed separately as `bfd6634`, on top of the merge `be77dd2` (Task 1 `ff27cb9`, Task 2
  `20eaa8a`), so both earlier histories are kept.
- **The work below:** originally uncommitted; committed in separate logical changes by Codex under the 2026-10-30 handoff instruction. See `docs/codex_handoff_20261030.md` and the branch log.

Before the commit, the three run-dependent tests were rerun against a temporary copy of the historical run: 40
passed. The copy was deleted, and the original's file-tree hash was unchanged.

## 1. The reconciled table (120 papers, UNVALIDATED)

The full table is in `docs/integration_validation/reconciled_120.md`, with what every cell rests on, and the data
is in `reconciled_120.json`. `tests/reconciled_forecast.py --root <checkout of bfd6634>` regenerates both. Every
stage is recomputed from its parts and asserted equal to `forecast.full_run`'s own figure, unrounded, to 1e-9 USD.
The rows sum to the total.

| Reconciliation | USD |
|---|---:|
| Baseline (unrounded 212.5629) | 212.56 |
| Baseline + 30% margin | 276.33 |
| Gap to $150 at baseline | 62.56 |
| Gap to $150 with margin | 126.33 |

The table answers the three questions about what is counted:

- **A06 repeat: counted.** 77 papers (repeat share 0.643, measured) at the 90th-percentile A06 cost, batched:
  $16.20.
- **Theme pass: counted as 279 calls**, the reference run's 65 free-text themes scaled up: $14.76. That is not the
  current architecture; see correction (a).
- **Batch discount: counted.** ×0.5 on A05/A06 per-paper work after one interactive probe per content level, and
  on the repeats; no batching elsewhere. The factor was measured by repricing the reference calls. That batches run
  at all, given the 24-hour vendor window and unmeasured throughput, is an assumption.

### Corrections found while sourcing, not folded into the $212.56

**(a) Theme pass.** The current architecture makes one A06 call per primary theme (5–8), each carrying every
finding of its theme. The per-finding fit measured on the reference run's 65 theme calls is 6,456 + 1,623 input
tokens and 764 + 50 output tokens per finding. At 2,017 findings:

- the calls carry 252–403 findings each, beyond the fitted range of 1–27;
- each call is 416k–661k input tokens, priced at GPT-6.1's long-context rates;
- the total is $14.79–$14.91, about the same money in a different structure.

**Capacity risk (P0 for the full run).** If one theme holds about 31% or more of the findings, its single call
exceeds GPT-6.1's 1.05M window. The A06 theme pass has no subdivision rule. The new context check would stop that
call for review before dispatch; it cannot make it fit.

**(b) Per-paper mean overstates.** The reference run re-extracted and re-validated 19 papers (repair loop on);
the loop is now off. The $43.38 per-paper line therefore overstates the current architecture. That is the safe
direction, and it is left as is.

**(c) Today's changes.**

| Change | Effect at 120 papers |
|---|---:|
| Contrary-evidence entries in the packets, and the role-column text, on A09 | +$0.34 |
| Retry share | +$0.02 |
| **Forecast on the current code** | **$212.92** (×1.3 = $276.80) |
| A10 GLOBAL register entries (not in A10's byte constants) | about $0.06, est. |

The paper counts that fit are unchanged: 50 papers fit $150 with the margin, 70 at baseline.

**Labels.** Every projection beyond the largest cohort actually run (28 papers, 471 findings) now carries
`validation: UNVALIDATED` (`forecast.validation`, `forecast.json`, `reconciled_120.json`). The 30% margin stays.

## 2. Pilot: fresh projection on the current architecture

`tests/pilot_projection.py`, results in `docs/integration_validation/pilot_projection.json`. The pilot now runs to
A12, because it is also the scientific evaluation.

**Part 1: the CP2 gate as it stands.**

| Selection | Projected total (cap $35) |
|---|---:|
| 2 full texts + 3 abstracts | $63.67 |
| 2 full texts + 2 abstracts | $62.36 |
| 2 full texts + 1 abstract (trial) | $60.98 |
| 1 full text + 2 abstracts | $57.81 |
| 1 full text + 1 abstract (trial) | $56.52 |

Every selection would be refused at CP2. A10's calibrated line holds each LOCAL packet at its 1,996-finding size,
so I measured instead of extrapolating.

**Part 2: pilot scale, measured.** The production A07 and A10 builders were run offline on stand-in registries
(the reference run's largest papers), with a structural manuscript at each length. The CP2 basis is shown first,
then the baseline without margin. Only selections that keep the required contradiction are shown.

| Selection (findings) | 5,000 words | 3,000 | 2,000 | 1,500 |
|---|---|---|---|---|
| 2 FT + 3 abstracts (159) | $54.65 / $44.34 | $47.77 / $39.05 | $44.27 / $36.35 | $42.58 / $35.05 |
| 2 FT + 2 abstracts (141) | $53.02 / $42.94 | $46.34 / $37.81 | $42.99 / $35.22 | $41.33 / $33.95 |
| 1 FT + 2 abstracts (100) | $47.49 / $38.31 | $41.49 / $33.69 | $38.53 / $31.42 | $37.01 / $30.25 |

**Finding.** No selection fits $35 with the margin, at any length tested.

- Reducing the paper count, as instructed, is not enough. With the margin, the lowest figure for any selection is
  $35.28 (1 full text + 1 abstract at 1,500 words), and that selection cannot test the contradiction.
- What sets the floor is the manuscript's length, through A09, A10 and A12. A10 is about 22 LOCAL calls of about
  195 KB per pass for 5,000 words, whatever the paper count. A07's group calls add to it.
- No scientific check was cut, and the cap was not touched.

**Decision needed (yours).** The levers I can see are:

- **Manuscript length:** a configuration change before the freeze. It changes the evaluation's conditions, not a
  check.
- **The margin, or the cap:** you have kept the 30% margin and ruled out a cap raise.

Pre-CP2 is priced at worst case on the current routes ($3.18). At CP2 the gate uses the actual pre-CP2 spend,
which was $2.07 on the reference run's models.

## 3. The table rule

Implemented as you specified. Tests: `tests/test_contrary_evidence.py` (10).

| Rule | Implementation |
|---|---|
| Selective, not exhaustive | Table notes and the A09 caption rule say so; the selection rule is restated |
| Every displayed conclusion acknowledges contrary evidence | A supporting row appears only with every contrary finding of its claims. The "Role and contrary evidence" column links rows by set letter, or says the challenged claim, or further contrary evidence, is discussed in the text. Still 7 columns: one page |
| Omitted contrary findings remain mandatory | Contrary-evidence register. The plan is refused unless a written element carries each one (`CONTRARY_NOT_CARRIED`). The CP_LEDGER review lists each one with its section |
| No selective reporting | A supporting row shown without its contrary finding is refused, at the plan (`TABLE_CONCEALS_CONTRARY`) and again at release |
| No forced equivalence | Each contradiction pair carries a comparability record: the context fields that differ or are unreported (system, line, dose, arm, comparator, endpoint and others). A09 must state the differences; A10 raises `FORCED_EQUIVALENCE` |
| A10 verification | GLOBAL pages carry each register entry beside its finding, at no extra page cost. A10 checks that each is accounted for and that the table agrees with the manuscript. Severity floors: `CONTRARY_EVIDENCE_UNADDRESSED` and `TABLE_CONCEALS_CONTRARY_EVIDENCE` BLOCKING; `TABLE_PROSE_INCONSISTENT` and `FORCED_EQUIVALENCE` MAJOR |
| Release gate | `finalize` stops at `CP_CONTRARY` unless each contrary finding is in the final table, or in a body sentence A10 VERIFIED that is tagged with a carrier and cites its paper, or excluded with a justification you record. The justification must be at least 20 characters, is bound to this register and manuscript, and is logged in provenance |

**On the compact 120-paper fixture.**

- Contrary findings: 54. In the table: 25 (5 linked sets). Omitted: 29, each carried in exactly one section.
- 220 of 232 contradiction pairs differ in at least one context field, most often agent, cell line, assay and dose.
- **What the gate caught:** a scripted writer that cites only three papers per sentence left five R0106 contrary
  findings tagged but uncited, and the gate blocked release. That case is kept as a regression test.

## 4. Context utilisation warnings

Implemented in `src/litreview/context_watch.py` and `pipeline.yaml -> context_utilisation`. Tests:
`tests/test_context_watch.py` (9, including the spend review point).

- **What is computed.** Every interactive and batch call computes (input + reserved output) / window and logs the
  byte bound and Anthropic's free count. The count decides the level where it exists; the byte bound decides
  otherwise. Actual usage is logged after the call.
- **Levels.**
  - Warn at 0.80: logged and notified; the call proceeds.
  - Review at 0.90: stops at `CP_CONTEXT` until that exact request is approved; the approval is recorded in
    provenance.
- **Configuration.** Thresholds are per model and labelled operational defaults, not reliability guarantees. The
  hard admission ceilings are unchanged.
- **No window recorded.** Claude Haiku 5.5 (A04) and GPT-6-luna have no recorded window. Their calls are logged as
  WINDOW_UNKNOWN with no ratio.
- **At 120 papers.** A09's largest section is 84% of its window by byte bound, which would warn. Anthropic's count,
  about 2.4 bytes per token, puts it near 40%.

**Spend review point.** `run.spend_review_usd: 25.00`. Before the call that would take spent + reserved + that
call's worst case past $25, the run stops at `CP_SPEND` and asks. The $35 cap does not move.

## 5. Pilot selection: unverified draft findings and proposed contrast

`docs/pilot_reference_findings.md` records each paper's findings, including null and negative results, conditions
and attribution. It is a **draft for your verification**, and items needing the PDF are marked VERIFY.

**Unverified draft assessment: the following is a proposed preclinical?clinical contrast, pending human source review and approval. It is not an approved reference answer.**

- **Lun et al. 2016 (PMID 27006494), preclinical:** DSF-Cu augmented TMZ and prolonged survival in models from
  recurrent tumours.
- **Huang et al. 2019 (PMID 30771200), phase II:** TMZ plus DSF/Cu in recurrent TMZ-resistant GBM: response rate
  0%, clinical benefit 14%, median PFS 1.7 months.

The record lists why the two are not like-for-like:

- system;
- exposure: nanomolar in vitro against 80 mg three times daily orally, with brain CuET exposure unknown;
- population;
- endpoint;
- adherence: median 1.6 cycles.

**Secondary contrasts are also recorded:**

- DSF alone (no copper) without effect in vivo, against DSF-Cu effective in vivo;
- proteasome inhibition asserted, against not found.

**Which selections keep the contradiction.** It needs **both** abstracts, 27006494 and 30771200. The "2 full texts
+ 1 abstract" selection loses it.

## 6. Calibration reporting (report only)

`litreview calibration-report RUN` (`src/litreview/tools/calibration_report.py`, test
`tests/test_calibration_report.py`) reports the following. It is read-only and changes no rate or procedure.

- **A06 repeat:** cost, calls, agreement counts, and quarantines by cause. Disagreement is measured only.
- **Theme pass:** calls, cost, and conflicts and independence notes per theme.
- **A09:** retrieval and redraft frequency per section, and the blocking A10 findings behind redrafts.
- **A10:** LOCAL and GLOBAL calls, cost and issue codes.
- **Per-call rates:** cost and output per call by agent and model; cache hits and writes; output per A07
  proposition; bytes per token by model (GPT and Kimi tokenization).

Reasoning tokens are billed as output and not recorded separately; the report says so.

## 7. Verification

```text
421 passed, 3 skipped   (full suite, clean checkout; the 3 need the historical run and passed against a copy)
git diff --check        clean
litreview check         all checks passed (keys from the process environment; no .env in the worktree)
120-paper simulation    reaches finalize; A10 APPROVED 388/388; release accounting: nothing unaddressed
```

## 8. Decisions needed before any paid call

1. **The pilot does not fit $35 with the 30% margin at any selection that tests the contradiction.** Choose a
   manuscript length for the pilot, or another lever; the cap and the margin are yours.
2. Verify `docs/pilot_reference_findings.md` (the evaluation key).
3. **For the full run:** the A06 theme pass needs a subdivision rule before 120 papers, or the gate will stop it
   whenever one theme holds about 31% or more of the findings.
4. Committing was authorized by the 2026-10-30 Codex handoff instruction. Human approval of the reference key and the final pilot baseline tag remain outstanding.

## Codex handoff verification

Codex independently reran the full suite: **421 passed, 3 skipped**. The skipped tests need the historical run or live probe in this worktree and were not rerun against a copied fixture in this handoff. The earlier copied-run result above is Claude's recorded result, not a new Codex measurement. `litreview check` passed with credentials loaded only into the checking process; no `.env` was copied, staged or committed, and no API probe was requested. No pilot or paid call was started. The reference findings remain an unverified, unapproved draft. See `docs/codex_handoff_20261030.md`.
