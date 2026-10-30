# Task 5 final commit and Stage 1 handoff

This is an operational handoff, not spending authorization, scientific approval, a reference key, or publication material. No pilot or paid evaluation has been initiated. Work remains on `task3-integration`; no merge, push or baseline tag is authorized here.

## Commit scope and validation record

- `0214ce7` - `feat(pilot): enforce separate stage authorizations and financial safeguards`: `src/litreview/agents/base.py`, `batch_stage.py`, `budget.py`, `cli.py`, `orchestrator.py`, `pilot_authorization.py`.
- `ef15d7e` - `fix(memory): stream JSON persistence and canonical fingerprint hashing`: `src/litreview/orchestrator.py`, `src/litreview/synthesis_registry.py`.
- The following tests/documentation commit contains `tests/test_pilot_authorization.py`, `tests/test_run_persistence.py`, `tests/staged_pilot_simulation.py`, `docs/task5_staged_pilot_report.md`, and this handoff. Its exact hash is supplied in the final handoff response / `git log -3 --oneline`.

Existing Task 1 (`ff27cb9`), Task 2 (`20eaa8a`), Task 3 (`bfd6634`) and subsequent Task 4 history remain ancestors, unchanged. Credential-pattern review found no matching secret in the Task 5 files. Environment files, temporary diagnostics, bytecode and historical-run files are excluded.

The detailed [implementation and validation report](task5_staged_pilot_report.md) preserves the original two complete runs: 476 passed each, no skips/deselections; 44 authorization tests; eight persistence/hash tests; unchanged oversized fixtures; Python allocation peak 1,331 to 788 MiB. Both full runs exercised the three historical tests on fresh temporary copies and verified all 562 original files unchanged. Final checks against the committed tree are reported separately in the final handoff response; these historical measurements are not relabelled as new measurements.

Scientific and financial policies are unchanged: Stage 1 is A02-A07 through CP3, Stage 2 is A08-A12 with a separate approval, the actual cap is $35, the spending review point is $25, and admission is `actual spent + outstanding commitments + 1.30 * future uncommitted costs <= $35`. Current offline estimates remain $16.4025 / $21.3232. No estimate grants authority. Gate 1, A06 eligibility, CP3, CP_LEDGER, CP_CONTRARY, A10/current-verification and final-release requirements remain mandatory. Near-context CP_CONTEXT and spending CP_SPEND reviews are not waived. Stage 1 approval cannot create Stage 2 paid reservations.

## Human reference-key verification checklist

**The existing `docs/pilot_reference_findings.md` remains an UNVERIFIED DRAFT and has not been edited or approved.** Its wording, including the section labelled "required contradiction: confirmed", is not an accepted scientific judgment. Earlier A05/A06 outputs may have influenced the draft. Independently inspect original publications, figures, tables, legends and supplements; do not use prior extraction agreement as validation. The items below are review targets from the draft, not findings certified by this handoff.

For every accepted entry, record original source version/DOI/PMID, exact passage and page/section/figure/table/panel, observed result versus author interpretation versus secondhand attribution, experimental unit and shared-study identity, model/arm/comparator, dose/unit/copper formulation, schedule, endpoint, sample size, uncertainty/statistics, and unresolved limitations. Record corrections and missing information rather than filling gaps from other papers. Have the researcher sign/date the resulting external key.

| Source / draft entries | Human checks against original source |
|---|---|
| Liu 2021, PMID 34638842, PMC8508702; dose statements in sections 2.2 and 4.3 and corresponding table/figure | Locate the exact conflicting table/caption and passages for 150 micromolar versus 150 nanomolar. Record both and whether an erratum resolves them; do not silently normalize. This is a **known inconsistency**, to be scored separately from blinded discovery. Verify 8 micromolar 1306MG and the U87MG dose, treatment duration and copper status independently. |
| Liu, L1-L3/L14-L15; associated results, methods and panels | Check parental versus RR/RTR identities, irradiation/TMZ derivation, TGF-beta/ALDH assays, units, individual endpoints and whether mechanistic conclusions are measured or inferred. Do not treat all models as one independent experiment. |
| Liu, L4-L8; migration results and captions | Verify null parental 2D effects, the R4T3 null result and reported p value, parental U87MG 3D null effect, model-specific decreases and combination comparators. Keep 2D migration, Transwell and viability separate. |
| Liu, L9; combination-index results/table and CompuSyn methods | Verify each line's CI and the stated interpretation, including parental antagonism, resistant-line synergy and near-additivity. Check doses, endpoint and uncertainty; do not infer synergy solely from a larger combination effect. |
| Liu, L10-L13; sphere/orthotopic growth, survival and tolerability panels | Check DSF alone versus galunisertib alone versus combination; cell line, mouse groups, schedules, dose units and sample sizes. Verify reported single-agent growth nulls, the 3.5GR6 survival null, medians/not-reached/censoring and body-weight null. Growth and survival are distinct endpoints; no body-weight change is not proof of general safety. |
| Liu discussion/limitations and attributed clinical result | Preserve hedges about ALDH-independent action, sphere-only stemness and genetic confirmation. Identify the cited Huang trial explicitly; its restatement in Liu is secondhand, not a second clinical cohort or independent negative result. |
| Lun 2016, PMID 27006494; original abstract, N1-N5 | Confirm patient-derived BTIC models, copper-dependent formulation, TMZ resistance/quiescence, in vitro TMZ enhancement and in vivo survival wording. Record which numeric doses, schedules, sample sizes, comparators and statistics are absent from the abstract as unavailable. Do not import full-text detail into an abstract-only benchmark or claim additional assays were observed. Separate the proposed mechanism/adjuvant recommendation from demonstrated endpoints. |
| Huang 2019, PMID 30771200; original abstract, H1-H5 | Independently check trial design, recurrent/TMZ-resistant population, eligibility, enrolled versus evaluable denominators, ORR 0%, clinical-benefit definition/denominator, median PFS/OS and any uncertainty available. Verify DSF/copper/TMZ doses and schedules, exposure duration, grade-3 ALT toxicity denominator and limited-activity conclusion. Retain negative endpoints and absence of a comparator; descriptive survival is not a causal treatment effect. |
| Lun-Huang relationship and study identities | Classify as **preclinical-clinical translational discordance**, not a direct contradiction. Retain differences in formulation/exposure, model/population, recurrent status, treatment, endpoint, design and unknown brain exposure. Do not invent a causal explanation or pool independent-study counts by publication/theme occurrences. A pre-supplied relationship tests preservation/interpretation, not independent discovery. |
| Scope boundary | The paid selection is exactly Liu, Lun and Huang. Skrott and Li appear in the broad draft but are not selected pilot papers and must not silently enter the benchmark or corpus. Record out-of-scope/contextual material as such; do not use it to fill source gaps in the three-paper key. |

The future human-verified key must be stored outside both framework worktrees, their common workspace parent and all run/input/retrieval locations. Keep source excerpts and answers out of topic, notes, seeds, research-agent prompts, payloads and retrieval. Only metadata enters financial bookkeeping: `version`, lowercase `sha256`, private key `commit`, `verified_by`, `approved_at`, `store_path`, `human_verified: true`. The human, not this task, independently verifies, freezes/commits and hashes that external key. Software checks metadata/hash consistency, not scientific correctness or the truth of the attestation.

## Stage 1 preflight requirements

Before a run-specific financial approval is actionable, the human must establish:

1. An independently verified external key and complete approval metadata. No such real key has been approved by this task.
2. Approved intended scientific scope and source policy in the input files. A02's formal scope/theme proposal must subsequently receive CP1 approval; CP2/CP_SYN/CP3 review remains mandatory as each is produced. Do not copy evaluation answers into those inputs.
3. Exact paper selection and source types: Liu PMID 34638842 **FULL_TEXT**; Lun PMID 27006494 **ABSTRACT**; Huang PMID 30771200 **ABSTRACT**. Review actual run-specific record IDs and source availability in `data/selected_corpus.json` when CP2 produces it; historical IDs are not pilot IDs. Initial pre-CP2 projections use pinned planned placeholders, not an approved final corpus. A source-type mismatch blocks the staged projection and must be resolved/reviewed before continuation.
4. A clean committed checkout; record `git rev-parse HEAD`, prompts, schemas, configs, actual model routes, prices and calibration. No tag is created here. Financial identity captures these dependencies, inputs, approved upstream evidence and key metadata; later changes require current projection/approval.
5. Actual spent amount and all outstanding reservations/batches reconciled against accepted outputs and billing. Inspect `status`, `costs`, run `costs.jsonl`, `reservations.json` and `data/pilot_reservations.json` (paths from `BudgetTracker.__init__`). Unknown/uncertain commitments must stay held, not be deleted to obtain admission.
6. A fresh Stage 1 projection, its exact pending fingerprint and an explicitly named human decision. Initial $16.4025/$21.3232 figures are not substitutes for that run-specific record.

The current snapshot has no approved real key and no reviewed run-specific pending financial projection. **Stage 1 paid pilot readiness: NOT READY.** These are human/run-preparation prerequisites, not a newly demonstrated code defect. No new technical blocker was found during the reviewed offline validation; final committed-tree regression results must also pass.

## Existing CLI sequence for later human use only

These commands are instructions only. None that create a run, record approval, authorize spending, approve a checkpoint or generate scientific outputs have been executed for this handoff. Run them only after the corresponding human prerequisites have been satisfied. Use the configured environment/virtual environment for this integration checkout, with credentials already securely loaded; do not print credentials. CLI syntax is from `src/litreview/cli.py`, not a proposed new interface.

**A. Freeze/review and prepare a new staged run (no model generation in `new`).** If a new dedicated staged run already exists, use its recorded RUN_ID and inspect it rather than creating a duplicate. Do not resume the historical run as the pilot.

```powershell
git status --short
git rev-parse HEAD
litreview check
litreview new --topic "C:\PilotInputs\topic.md" --notes "C:\PilotInputs\notes.md" --seeds "C:\PilotInputs\seeds.txt" --family oncology-drug-repurposing
```

The input directory is an illustrative human-managed location, separate from the private answer key. Use the run ID printed by `new` as RUN_ID in all following commands. Verify `execution_mode: STAGED_PILOT`, pinned intended sources and the frozen code record. Do not infer formal CP1 approval from the existence of input notes.

**B. Record already human-approved external key metadata, inspect actual finances, request a projection, then stop for review.** Recording the metadata does not grant spending authorization.

```powershell
litreview pilot-reference RUN_ID --metadata "C:\PrivateEvaluation\approved-key-metadata.json"
litreview status RUN_ID
litreview costs RUN_ID
litreview project RUN_ID --stage 1
```

Read `data/pilot_pending_authorization.json` and inspect its context, actual spending, commitments, future forecast and fingerprint. Confirm it is the intended Stage 1 scope and WITHIN_CAP. Only the human may decide the recorded key is independently verified and this exact financial request should be approved.

**C. Only after explicit approval of that exact pending projection, record financial authority.** Replace APPROVED_FINGERPRINT with the current printed value and REVIEWER_NAME with the approving human; placeholders are not approvals.

```powershell
litreview authorize-stage RUN_ID 1 --fingerprint APPROVED_FINGERPRINT --reviewer "REVIEWER_NAME"
```

**D. After valid Stage 1 financial authorization, the human may choose to initiate Stage 1 up to its checkpoints.** This command can generate paid outputs and is not run by this handoff:

```powershell
litreview run RUN_ID --until outline
```

Review generated checkpoint review/decision files and source-linked evidence. At each applicable checkpoint, the human fills the current decision file and may then use the matching existing command, one checkpoint at a time:

```powershell
litreview approve RUN_ID CP1
litreview approve RUN_ID CP2
litreview approve RUN_ID CP_SYN
litreview approve RUN_ID CP3
```

This is not a batch approval sequence: a later checkpoint does not yet exist when an earlier one is reviewed. If CP_CONTEXT or CP_SPEND occurs, review its request-specific decision and use `litreview approve RUN_ID CP_CONTEXT` or `litreview approve RUN_ID CP_SPEND` only if independently approved; the $35 cap is never raised by these decisions. Review/resolve any validation holds instead of bypassing them.

Accepted scope, themes, selected records, full text, extractions and validations can change the financial identity. After such updates the guard may pause before the next call. Inspect actual work/spend/commitments, repeat `project RUN_ID --stage 1`, review its **new** fingerprint, and repeat `authorize-stage RUN_ID 1 ...` only after human approval. Do not repeatedly invoke `run` or silently reapprove to work around a stale identity or uncertain submission. Valid accepted work and holds must survive interruption.

After human CP3 approval, retain the completed Stage 1 evidence/evaluation and stop. Stage 2 remains separately unauthorized; the framework can record `COMPLETED_STAGE_1_PARTIAL_EVALUATION` at CP3 rather than advance to A08. CP_LEDGER, CP_CONTRARY and A10/final-release gates remain in place for any separately approved future Stage 2. No Stage 2 approval command, baseline tag or automatic continuation is part of this handoff.
