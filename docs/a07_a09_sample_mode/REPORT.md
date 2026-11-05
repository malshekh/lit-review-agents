# Phase 1.5: NON-REPRESENTATIVE A07 → A09 writing sample

Status: development only, not promoted. No paid or free provider call was made. No live ledger was written, no
checkpoint approved, no financial hold placed. Frozen v10 was only read: `runtime_integrity.verify` reports
6,015 immutable files with zero mismatches, manifest SHA-256 `9c2cb648d3c38e14b0a90ae68d5237dd96346ef2cfab9d494b040ca7c3c72bc1`.

## Go / no-go

**Conditional GO for a 3-GROUP, 1-section sample.** Its worst case, with the 30% margin held, is $10.77
against $14.191105 of writing sub-cap. The 2-section variant also fits ($13.36), but leaves only $0.83.
Its A08 and A09 rows are conditional envelopes, so a larger real package could push it over at the Stage 2
gate.

Before any paid call, all of the following must happen:
1. Codex promotes a versioned runtime containing this branch. Frozen v10 cannot run any of it.
2. May approves the repaired PLAN.
3. May approves CP_SYN.
4. May authorizes a fresh Stage 1 projection.

Writing then needs CP3, a fresh Stage 2 authorization and CP_LEDGER. The full 11-GROUP path does not fit
($52.94) and is not proposed.

## Git proof

| Item | Value |
|---|---|
| Codex work committed | `92b2c56` on `fix/a07-a12-contract-hardening`, "wip: Codex A07–A12 contract hardening (818 tests)". Not pushed. |
| Codex suite before that commit | 828 passed, 3 skipped. The 10 extra tests are parametrized cases in `tests/test_contract_hardening.py`, edited after Codex's 818 count. |
| Worktree | `C:\Users\maykh\Desktop\lit-review-agents\lit-review-agents-claude-phase15` |
| Branch | `claude/a07-sample-mode`, from `92b2c56`. The branch name was free. |
| Codex tree after Step 0 | Clean; HEAD still `92b2c56`; nothing written there since. |

`main`, PR #1, PR #2 and every other branch are unchanged.

## What changed

| File | Change |
|---|---|
| `src/litreview/sample_mode.py` (new) | Sample authority, PLAN import and approval, the sample A07 job, worst-case pricing, the dry run, and the sample stage projection. |
| `a07_a09_sample.py` (new) | Guarded launcher. Every subcommand except `continue --paid` is free. |
| `src/litreview/synthesis_bounded.py` | Adds `validate_output` and `check_plan`, extracted unchanged from `_run_turn` and `plan()`. Adds `import_plan`, which writes a `TURN_IMPORTED_REPAIR` event, and `require_import_approval`, which blocks GROUP. |
| `src/litreview/synthesis_job.py` | The ledger treats `TURN_IMPORTED_REPAIR` as committed, with its own event name and model label. |
| `src/litreview/orchestrator.py` | The A07 job builder and per-call quote are split out of `stage_synthesize`, with behaviour unchanged. Adds hooks for settings, job class, journal, outline payload and sample mode. `_admitted` gains an optional `extra`. A full run refuses a sample package at CP3. |
| `src/litreview/singlepaper_eval.py` | WritingRun sample mode (below). The writing reservation floor now prices every provider's input at its cache-write rate. |
| `src/litreview/pilot_authorization.py` | `project()` uses the sample projection when the sample authority exists. |
| `tests/test_sample_mode.py` (new) | 24 offline tests. |

No schema, prompt or validator was weakened or edited. The CP3 package validator `require_package` is unchanged.

### 1. Repaired-PLAN import

- **Copy by default.** The import refuses inside a frozen or promoted runtime unless `--live` is given.
- **Hash checks.** It verifies raw0 `3d2f03ad…74675` and repaired `958ea8e0…f32db`. It also checks the
  private provider response against its receipt hash, and checks that the evidence registry is identical to
  the one the PLAN was generated against. A mismatch writes nothing.
- **Production validators.** The import runs the PLAN schema, the mode/status check, the output-allowance
  check and the theme-proposal anchor check. A test runs the four v10 violation types through it: missing
  `mode`, `fivew1h` arrays, a 517-character rationale, and 15 finding IDs.
- **Ledger event.** The PLAN is committed as `TURN_IMPORTED_REPAIR` with model `researcher-repair-of:<raw sha>`.
  It is never recorded as `TURN_ACCEPTED`.
- **Import record.** `plan_import.json` records the paths and hashes of the original, the repair, the receipt,
  the private response and a code-computed `plan_repair_audit.json`. It also records the v10 and current job
  identities, the prompt and schema hashes, and `researcher_approved: false`.
- **Approval gate.** GROUP raises `ImportApprovalRequired` until `approve-plan-import` names the exact
  repaired SHA-256 and a person. Approval refuses overwrite.
- **What the repair changed.** The audit, run on a copy, lists four changes:
  - `mode` was added;
  - the 5 `fivew1h` entries became 9 strings;
  - one unresolved item was relocated to `scope_drift`;
  - the over-long theme proposal was split, taking proposals from 6 to 7.

  May should read this file before approving.

### 2. Guarded GROUP continuation

- **Sample authority.** `init --max-groups N` writes `input/a07_a09_sample.json`, taking the first N packets
  in the production builder's order.
- **Mandatory items stay in scope.** The sample job refuses any subset that leaves a mandatory manifest item
  unowned. On v10, G0001–G0003 own all 20 items, so **3 is the minimum**. `--max-groups 2` is refused with
  "include packets ['G0003']".
- **Excluded findings.** Findings in excluded packets get the disposition `OUT_OF_SAMPLE_SCOPE`. They are never
  dropped and never left `UNACCOUNTED`.
- **Labelling.** The package, the CP_SYN alignment record, the state and `sample_output.json` all carry
  `NON_REPRESENTATIVE_SAMPLE`.
- **Separate job.** The sample job has its own identity and folder, so it never shares turns with a full
  synthesis.
- **Reservations.** Each call goes through `WritingRun._reserve`, which refuses before send if spent minus
  baseline, plus holds, plus 1.3 × cost exceeds $15. Codex's `Run._reserve` then holds the 30% margin, and
  unused holds are released after settlement.
- **Dry run.** `dry-run` copies the run to a temporary folder. It disables every provider route, both SDK
  client factories and socket connect, then lists the gates and every next call with its reservation.
  A test proves no provider function or SDK factory is called and no file in the run changes.
- **No paid retrieval or repair.** Retrieval rounds and JSON repair are 0 in sample mode, so NEEDS_EVIDENCE
  stops the run.

### 3. Stop after A09 (WritingRun `sample_mode`)

- **Loops.** The constructor accepts 0 critique cycles / 0 redrafts only with a sample authority, applied to
  the run's own config copy. Without one, it still requires the native 0/1. The sample handler table has no
  verify, critique or edit handler, and `agent()` and `_admitted()` refuse A10, A11 and A12.
- **Path.** The sample runs, in order:
  1. imported and approved PLAN;
  2. CP_SYN;
  3. 3 GROUP calls;
  4. RECONCILE pages;
  5. FINAL;
  6. CP3 pause;
  7. A08, with `sample_scope` in its payload and the word limit set to the sample maximum;
  8. a check that the outline has 1–2 sections and 800–1,000 words, else a PAUSE;
  9. CP_LEDGER, plus the native contrary-evidence and allocation gates;
  10. A09 for those sections only, each through the native section gate;
  11. `sample_output.json` (`verified: false`, `a10_a12_run: false`, no front matter);
  12. state `COMPLETE_SAMPLE`.

  Failures end as `PAUSED: …`, never FAILED.
- **Default behaviour.** Behaviour without the sample authority is unchanged, and a test shows the critique
  and edit handlers still run.

### 4. Caps and effort (sample authority; shared config untouched)

| Setting | Value | Reason |
|---|---|---|
| A09 `max_tokens` | **16,000** (allowed 8k–16k), effort **medium**, `output_config.effort` only | A schema-valid 1,020-word section with a tag on every sentence has a byte bound of about 10.1k. Bytes are at least tokens, so at least 5k tokens are provably left for adaptive thinking; at about 3.5 bytes per token, about 13k. 2,500 cannot hold the text alone. The 16k cap costs at most $0.26 more per section than 8k (+30%). A test asserts no `budget_tokens` is ever sent. |
| A08 `max_tokens` | **8,000** default (allowed 4k–16k) | A minimal schema-valid 2-section outline for the simulated 29-element sample package has a byte bound of 8,947, or 2.3k–3.4k tokens, and OpenAI reasoning shares the cap. **4,000 is not contract-safe. 8,000 is likely but not provable by the strict byte bound.** 12,000 would add only about $0.05 (+30%). |
| A07 caps | Unchanged: PLAN 32k (not called), GROUP 12k, RECONCILE 6k, FINAL 6k | Not reduced. GROUP/RECONCILE/FINAL still inherit A07 effort `high`. |
| Retries | No new retries | Raw outputs are still saved per attempt. |

## Tests (all provider keys blank)

| Run | Result |
|---|---|
| `tests/test_sample_mode.py` | 24 passed |
| Full suite | **852 passed, 3 skipped, 0 failed** (Codex's 828 plus these 24). The skips are the two unavailable run-20261025-100039 tests and one unavailable live probe. |

The sample tests cover:
- hash mismatch refused with nothing written;
- the four v10 violation types refused by the import;
- import recorded as `TURN_IMPORTED_REPAIR`, with GROUP blocked until approval;
- wrong-SHA and blank-name approval refused;
- the live runtime refused without `--live`;
- a subset that leaves mandatory items unowned refused;
- the sample package passing the unchanged `require_package`;
- a full run refusing a sample package;
- the dry run making no call and writing nothing;
- the projection pricing only the sample's calls and excluding the candidate;
- worst case priced at cache-write rates;
- `reserve()` blocking an over-cap call before dispatch;
- sample caps and effort applied, with A10–A12 refused;
- the stop after A09 reaching `COMPLETE_SAMPLE`;
- an out-of-bounds outline pausing;
- verification phases unreachable in sample mode;
- critique still running when the sample is off;
- the constructor's loop rules;
- the authority bounds.

An offline end-to-end check also ran on a copy of the v10 run inside this worktree's gitignored `runs/` folder:
1. the import refused GROUP while unapproved;
2. on the copy only, a simulated approval let a fixture model, not a scientific result, run 3 GROUP calls,
   1 RECONCILE and FINAL through every production validator;
3. the sample package passed the unchanged CP3 validator, with 88 findings `OUT_OF_SAMPLE_SCOPE`.

The copy was deleted afterwards.

## Part B: re-price (read-only)

Method:
- **GROUP inputs** are exact serialized request byte bounds from the production packet builder, through the
  new dry run.
- **RECONCILE and FINAL** are envelopes. Each accepted GROUP output is at most 10,976 bytes, because the output
  guard refuses more; 160 bytes per proposition is added for code IDs, the registry parts are serialized
  exactly, and the 2 RECONCILE pages are a worst case for at most 36 propositions.
- **A08** is exact on the simulated sample package.
- **A09** is an envelope: every element of the sample package in one section packet (real bridge builders),
  plus the earlier section's prose bounded at 8 bytes per word.
- **Worst case** prices every input byte at the cache-write rate: Opus 5 1-hour write $10/M, GPT-6.1 30-minute
  write $2.50/M. Output is the full cap.
- **Expected** uses 2.335 bytes per token (measured on the v10 PLAN), half of each cap as output, the
  hardened A07 system prompt (about 9.8k tokens) written once and then read at $0.50/M, and 1 RECONCILE page.
  It is an assumption, not a forecast.
- **A08/A09 rows are conditional projections** from a fixture package. They are re-priced exactly by the sample
  projection at the Stage 2 authorization and again before each call.

The hardened A07 prompt is 22,968 bytes against v10's 11,910. That adds about 11k bytes to every A07 call,
worth about $0.11 cold each.

### Mini-path: 3 GROUP (G0001–G0003), 2 sections — fits, $0.83 headroom

| Step | Model | Input bound (bytes) | Basis | Output cap | Cache split (worst / expected) | Worst $ | +30% | Expected $ | Cum +30% | ≤ $14.191105 | ≤ $26.8747694 |
|---|---|---:|---|---:|---|---:|---:|---:|---:|---|---|
| GROUP_G0001 | claude-opus-5 | 49,553 | EXACT | 12,000 | all 1h write / system write | 0.7955 | 1.0342 | 0.3053 | 1.0342 | yes | yes |
| GROUP_G0002 | claude-opus-5 | 45,824 | EXACT | 12,000 | all 1h write / system read | 0.7582 | 0.9857 | 0.2039 | 2.0199 | yes | yes |
| GROUP_G0003 | claude-opus-5 | 101,676 | EXACT | 12,000 | all 1h write / system read | 1.3168 | 1.7118 | 0.3235 | 3.7317 | yes | yes |
| RECONCILE_0001 | claude-opus-5 | 104,550 | ENVELOPE | 6,000 | all 1h write / system read | 1.1955 | 1.5542 | 0.2546 | 5.2858 | yes | yes |
| RECONCILE_0002 (only if >32 propositions) | claude-opus-5 | 104,550 | ENVELOPE | 6,000 | all 1h write / system read | 1.1955 | 1.5542 | — | 6.8400 | yes | yes |
| FINAL | claude-opus-5 | 75,463 | ENVELOPE | 6,000 | all 1h write / system read | 0.9046 | 1.1760 | 0.1923 | 8.0160 | yes | yes |
| A08 outline | gpt-6.1-sol | 50,932 | EXACT on fixture package | 8,000 | all cache write / uncached | 0.2073 | 0.2695 | 0.0836 | 8.2855 | yes | yes |
| A09 section 1 | claude-opus-5 | 151,295 | ENVELOPE | 16,000 | all 1h write / uncached | 1.9130 | 2.4868 | 0.5240 | 10.7724 | yes | yes |
| A09 section 2 | claude-opus-5 | 159,362 | ENVELOPE | 16,000 | all 1h write / uncached | 1.9936 | 2.5917 | 0.5412 | 13.3641 | yes | yes |

| Variant | Worst case +30% | Expected | Left of $14.191105 | Left of $26.8747694 |
|---|---:|---:|---:|---:|
| 2 sections | $13.3641 | $2.68 | $0.8270 | $13.5107 |
| **1 section (recommended)** | **$10.7724** | $2.14 | **$3.4187** | $16.1024 |
| 1 section, 1 RECONCILE page | $9.2182 | $1.89 | $4.9729 | $17.6565 |

**The mini-path worst case fits $14.191105. No top-up is needed.** Reservations are not simultaneous: each
call holds its own amount and releases the unused part after settlement.

### Informational: full 11 GROUP, stop after A09, 2 sections — not proposed

The full path's GROUP rows match the mini-path for G0001–G0003, then:

| Step | Input bound (bytes) | Worst +30% | Cum +30% |
|---|---:|---:|---:|
| GROUP_G0004 | 87,139 | 1.5228 | 5.2545 |
| GROUP_G0005 | 81,376 | 1.4479 | 6.7024 |
| GROUP_G0006 | 76,271 | 1.3815 | 8.0839 |
| GROUP_G0007 | 93,239 | 1.6021 | 9.6860 |
| GROUP_G0008 | 81,661 | 1.4516 | 11.1376 |
| GROUP_G0009 | 83,937 | 1.4812 | 12.6188 |
| GROUP_G0010 | 45,342 | 0.9794 | 13.5982 |
| GROUP_G0011 | 38,464 | 0.8900 | **14.4883 (over $14.19)** |
| RECONCILE_0001–0005 (envelope, ≤132 propositions) | 310,886 each | 4.2365 each | 35.6709 (over $26.87 from page 3) |
| FINAL (envelope) | 193,559 | 2.7113 | 38.3821 |
| A08 outline (fixture) | 123,758 | 0.5062 | 38.8883 |
| A09 section 1 (envelope) | 496,244 | 6.9712 | 45.8595 |
| A09 section 2 (envelope) | 504,311 | 7.0760 | **52.9356** |

The full path's expected total is about $9.55, but its worst case would need a $38.74 top-up over the writing
sub-cap and $26.06 over the pilot cap. That arithmetic is reported, not proposed.

### Contingencies excluded from the base path

None of these is automatic, and each is refused before send unless separately reserved:
- A07 retrieval lookups (0 rounds in sample mode);
- JSON repair (0);
- an A09 evidence request (0 rounds; NEEDS_EVIDENCE stops);
- a retry after truncation;
- A09 front matter;
- A10–A12.

### Cheapest further cuts

These are ordered by money saved, without touching evidence:
1. **One section instead of two.** Saves $2.59.
2. **One RECONCILE page.** This is automatic when there are 32 propositions or fewer. Saves $1.55.
3. **A09 cap 8k instead of 16k.** Saves $0.26 per section, but the thinking headroom is then unproven.
4. **The prompt-hardening overhead** on the 6 A07 calls is about $0.86 (+30%). It is not cut, because it buys
   the contract fixes.

Dropping mandatory packets is not possible, because the job refuses it. No GROUP cap cut is proven safe.

## Commands for May

All commands are PowerShell. Clear every provider key first, in every new shell:

```powershell
$env:ANTHROPIC_API_KEY=""; $env:OPENAI_API_KEY=""; $env:MOONSHOT_API_KEY=""; $env:LANGSMITH_API_KEY=""; $env:LANGSMITH_TRACING="false"
```

**A. Free rehearsal on a copy, in this development worktree.** This was run verbatim during development:

```powershell
cd C:\Users\maykh\Desktop\lit-review-agents\lit-review-agents-claude-phase15
$env:PYTHONPATH="src"; $py="..\lit-review-agents\.venv\Scripts\python.exe"; $rid="20261031-213324-r0001-writing-v1"
& $py -B a07_a09_sample.py copy-run --source "C:\Users\maykh\LitReviewStage1\execution-20261104-v10-a07-plan-retry\runs\$rid"
& $py -B a07_a09_sample.py init --run-id $rid --max-groups 3 --created-by "May Khalid Alshekhlee"
& $py -B a07_a09_sample.py import-plan --run-id $rid
& $py -B a07_a09_sample.py dry-run --run-id $rid
```

**B. Live sample, only after Codex promotes a runtime containing this branch.** Call it vNEXT. The commands use
its bootstrap, and paths depend on that promotion, so **these live commands are unverified**. Each line stops
for May's review before the next.

```powershell
cd C:\Users\maykh\LitReviewStage1\<vNEXT runtime>
$b="python -I -S -B bootstrap.py a07_a09_sample.py"; $rid="20261031-213324-r0001-writing-v1"
# 1. sample scope (writes input/a07_a09_sample.json; invalidates older stage authorizations by design)
iex "$b init --run-id $rid --max-groups 3 --created-by 'May Khalid Alshekhlee' --live"
# 2. import (free); then READ data/synthesis_job_<tag>/plan_repair_audit.json
iex "$b import-plan --run-id $rid --live"
# 3. RESEARCHER: approve the exact repair
iex "$b approve-plan-import --run-id $rid --sha 958ea8e00eabb8fafe93bd31a2f6758cc829b0113d107c945d10feac467f32db --by 'May Khalid Alshekhlee' --live"
# 4. free dry run: gates and every reservation
iex "$b dry-run --run-id $rid"
# 5. Stage 1 projection (free), then RESEARCHER authorizes the printed fingerprint
iex "$b request-authorization --run-id $rid --stage 1 --live"
iex "$b authorize --run-id $rid --stage 1 --fingerprint <printed> --reviewer 'May Khalid Alshekhlee' --live"
# 6. PAID: stops at CP_SYN (no GROUP yet). RESEARCHER edits/approves CP_SYN, then PAID again: GROUP/RECONCILE/FINAL, stops at CP3
iex "$b continue --run-id $rid --max-groups 3 --paid --live"
iex "$b approve-checkpoint --run-id $rid --checkpoint CP_SYN --live"
iex "$b continue --run-id $rid --max-groups 3 --paid --live"
# 7. RESEARCHER approves CP3; Stage 2 projection (now exact for A08) and authorization; PAID A08, stops at CP_LEDGER
iex "$b approve-checkpoint --run-id $rid --checkpoint CP3 --live"
iex "$b request-authorization --run-id $rid --stage 2 --live"
iex "$b authorize --run-id $rid --stage 2 --fingerprint <printed> --reviewer 'May Khalid Alshekhlee' --live"
iex "$b continue --run-id $rid --max-groups 3 --paid --live"
# 8. RESEARCHER approves CP_LEDGER; PAID A09 for the 1-2 approved sections, then COMPLETE_SAMPLE
iex "$b approve-checkpoint --run-id $rid --checkpoint CP_LEDGER --live"
iex "$b dry-run --run-id $rid"
iex "$b continue --run-id $rid --max-groups 3 --paid --live"
```

Step 6 is a paid command only once CP_SYN is approved. Before that, the job stops at the CP_SYN gate without
calling a model, because the PLAN is imported.

For a 1-section sample, May approves a 1-section A08 outline at CP_LEDGER. The cap check accepts 1 or 2
sections. Step 8 accepts the A08 output only if it plans 1–2 sections and 800–1,000 words. Otherwise the run
pauses before any A09 call.

## Not verified, not done, and quality limits

- **Unverified.** The live commands, the promotion itself, the private-audit-folder ACLs, and the real token
  counts are unverified; no provider tokenizer was called. A08/A09 sizes for a real package are re-priced
  only at Stage 2.
- **Prompt mismatch.** The repaired PLAN was generated under the v10 A07 prompt. GROUP would run under Codex's
  hardened prompt. Both identities are recorded in the import, and May should accept the mismatch knowingly.
- **Scope of the sample.** It covers 1 paper (R0001) and 3 of 11 packets. 88 of 180 findings, the rest of T3
  and all of T4 and T5, are explicitly out of scope. It is unverified prose: no A10 verification, A11
  critique, A12 editing or front matter. Interpretive inflation or errors can remain. It shows only that the
  machinery can produce a gated section; it does not show multi-paper synthesis quality, verification or
  readiness to publish. It must never be labelled a review or a validated manuscript.
- **Observations, not changed:**
  - `PlanRetryRun._reserve` passes an amount that already includes the margin to `Run._reserve`, which adds 30%
    again. That overstates the hold at about 1.69x.
  - Codex's `writing_admission.quote_call` prices OpenAI input at the plain $2.00 rate, while cache writes bill
    at $2.50. The sample floor uses $2.50.
  - In the dev `config/pipeline.yaml`, `notify.on` has become `true:`, because YAML reads the bare word `on` as
    a boolean. That key probably no longer drives notifications.
- **Recommendation if the gates do not hold.** If Stage 2 re-pricing of the real package exceeds the sub-cap,
  defer prose until after the post-pilot fixes rather than cutting evidence.
