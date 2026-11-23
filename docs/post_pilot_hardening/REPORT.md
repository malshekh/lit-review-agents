# Post-pilot hardening: what was done, what was not, and what needs you

Date: 2026-11-23. Branch: `claude/post-pilot-hardening`, on top of Codex's `92b2c56` and the sample-mode
commits `715c353` and `b0c08f4`. **No paid call was made.** No checkpoint was approved, no `--live` command was
run, and nothing was merged into `main`.

Tests: **915 passed, 3 skipped**, with every provider key blank (858 before this work).

## 1. State of things

| Item | Value |
|---|---|
| Sealed runtime | `C:\Users\maykh\LitReviewStage1\execution-20261123-v11-post-pilot-hardening` |
| Built from | commit `27f578a5e8bc6c2041db5dbad347b213e67bbacc` (clean worktree), by `scripts/build_runtime.py` |
| Manifest | 6,020 files verified; manifest SHA-256 `d77c18b5f772dab11c04adba45b0cc7efa31e664aae7db45be9464820086b25c` |
| Pilot archive | `C:\Users\maykh\LitReviewStage1\archive\pilot-2026-11\` (v8, v9, v10, read-only, with `PILOT_CLOSEOUT.md`) |
| Pull requests | #3 (Codex `92b2c56`), #4 (sample mode), and the PR for this branch |
| Runtime expiry | The price table in v11 was read on 2026-11-23. After **2026-12-23** the 30-day price gate refuses paid calls and a new runtime is needed. |

Pin the manifest SHA somewhere outside the runtime. It is recorded here and in the pull request.

## 2. Dry run on the promoted runtime: zero network calls

The guarded commands were run on a byte-identical copy of v11's code (130 files compared with the sealed
manifest, 0 differences) and a copy of its run. The copy was needed because `init` and `import-plan` write
into the run, and inside v11 that takes `--live`, which is yours to run.

Each command ran under `scripts/offline_guard.py`, which replaces socket connections and name lookups with a
counter that raises. Result for `copy-run`, `init`, `import-plan` and `dry-run`: **0 network attempts each**.

Worst case with the 30% margin held, as the dry run printed it:

| Step | Input bound | Output cap | Worst +30% | Cumulative |
|---|---:|---:|---:|---:|
| GROUP_G0001 | 49,553 | 12,000 | $1.0342 | $1.0342 |
| GROUP_G0002 | 45,824 | 12,000 | $0.9857 | $2.0199 |
| GROUP_G0003 | 101,676 | 12,000 | $1.7118 | $3.7317 |
| RECONCILE_0001 | 104,550 | 16,000 | $1.8792 | $5.6108 |
| RECONCILE_0002 (only if more than 32 propositions) | 104,550 | 16,000 | $1.8792 | $7.4900 |
| FINAL | 95,463 | 16,000 | $1.7610 | $9.2510 |
| A08 outline (re-priced exactly at Stage 2) | | 8,000 | about $0.27 | about $9.52 |
| A09 section (re-priced exactly at Stage 2) | | 16,000 | about $2.49 | about $12.01 |

Against the $14.191105 writing sub-cap that leaves about **$2.18** (about $4.06 with one RECONCILE page). It was
$3.42 before: raising RECONCILE and FINAL from 6k to 16k, as you asked, costs $1.24 of worst-case room. GROUP
stays at its approved 12k.

**Known mismatch, accept it knowingly:** the repaired PLAN was generated under the v10 A07 prompt (11,910
bytes). GROUP runs under Codex's hardened prompt (22,968 bytes), about 11k bytes more on every A07 call, worth
about $0.11 per cold call. Both prompt identities are recorded in `plan_import.json`.

## 3. Control-label check (free; read from the cached full text of R0001)

All seven findings carry `comparator: NONE_REPORTED` or no comparator. Checked against the source:

| Finding | Where | Verdict |
|---|---|---|
| F67 | Results, Fig. 1B | **Wrong in substance.** The sentence before it opens "In comparison with parental GBM cells" and this sentence continues it ("In addition … were upregulated … in both RR and RTR"). The comparator is the parental cells. |
| F62 | Results | Control reported implicitly. The values are percent viability (85.5%, 88.3%), which presupposes an untreated control that the sentence does not name. `NONE_REPORTED` is literally true and reads as uncontrolled. Also labelled `NO_EFFECT_ON`, although growth fell by 12 to 15%. |
| F51 | Abstract | Control reported elsewhere. "TR activated ALDHs" has no comparator in the abstract; the Results compare against parental cells. |
| F1 | Fig. 10 summary | Inconsistent with its own constraint, which says "relative to parental cells". It is an interpretive schematic statement, so the label should be `NOT_APPLICABLE`. |
| F59 | Abstract | Background statement ("DSF … functions by inhibiting ALDHs"). Should be `NOT_APPLICABLE`, not `NONE_REPORTED`. |
| F29, F31 | Conclusions | Authors' concluding interpretations. The comparator is missing (null), not wrong. Should be `NOT_APPLICABLE`. |

None of this blocks the sample: F51 and F62 are `BLOCKED_ALIGNMENT`, F67 is `HUMAN_REVIEW_REQUIRED`, and F29,
F31 and F59 are `DOES_NOT_ESTABLISH`. The cause is systematic, though: A05 took the comparator from the span
sentence alone. The A05 prompt now says to take it from the experiment's own context, and to use
`NOT_APPLICABLE` for background and interpretation (prompt v0.7). This is my reading of the paper; please
confirm F67 and F62 against Figure 1B and Figure S1.

## 4. Science review of the repaired PLAN (SHA `958ea8e0…f32db`)

This is advice for your decision. I did not approve the SHA: the approval gate takes your name, and it should
be yours.

**DSF and copper.** The PLAN proposes a subtheme for "disulfiram administered without copper in this record's
own experiments". The paper does not support "without copper". It mentions copper once, as an attributed
statement about radiosensitisation (refs 45, 46). Its own experiments add no copper, in cells grown in DMEM
with 10% fetal bovine serum and in mice given DSF 50 mg/kg intraperitoneally. Serum and tissue supply copper,
and DSF's cytotoxicity is generally attributed to its copper complex, so these are "no copper supplement
reported" conditions, not copper-free ones. The PLAN itself lists "whether copper was present in any reported
condition" as unresolved, so its own proposal overstates. Wording to use: "disulfiram with no copper
supplementation reported". The negative in vivo single-agent result must not be read across to DSF with copper.

**T5 repurposed.** T5 was approved as "cross-paper interpretation and translational boundaries". With one paper
it cannot do that, and the PLAN repurposes it as the boundary between the authors' interpretation and the
evidence, flagged for human approval and not applied. That is acceptable for the sample only, on three
conditions: record it at CP_SYN as a sample-only relabel; allow no sentence that implies convergence across
studies; restore the approved definition for the full run. Its five items (F29 to F32, F58) are single-paper
author conclusions, three of them not established.

**Non-significance wording.** The PLAN uses "nulls" as shorthand ("DSF single-agent nulls in vivo", "two
attributed clinical null results"). The paper's "did not affect" statements rest on p-values such as 0.0732 for
a fall from 40.7% to 32.0%: not significant, and not evidence of no effect. For survival, the paper reports a
median of 54 days for vehicle and "not defined" for the three treated arms, with no log-rank test. That means
not reached within the observation period. Without a test it is neither a survival benefit nor a null result,
and the PLAN is right that the group-level no-difference statement was rejected. Carry these as "no
statistically significant difference reported" with n and test, or "test not reported". The shared language
policy (v0.2) now states this rule for the writer, verifier, critic and editor.

**The fivew1h gap.** Two separate things:
- *Encoding.* The repair turned 5 entries with arrays into 9 entries whose `unresolved` field is a
  JSON array written as a string (`"[\"…\", \"…\"]"`), to fit the schema's 480-character string and 9-entry
  limit. The content is intact (14 items; one moved to `scope_drift`), but GROUP will see bracketed, escaped
  text. It is ugly, not wrong.
- *Content.* Despite its name, the field holds only unresolved questions per theme. There is no who, what,
  where, when, why or how for any theme, because the schema has no place for it. If you expected a 5W1H
  analysis from PLAN, it does not exist, in the original or in the repair.

**Recommendation.** Approve the SHA for the sample, and make the copper wording and the T5 relabel explicit in
your CP_SYN decision, which is the gate built for that. Rename or extend `fivew1h` after the sample, not before:
the import pins this exact SHA.

## 5. Approval order (yours; each step is a separate decision)

Run in v11 under the `LitReviewPilot` account, with `$b = "python -I -S -B bootstrap.py a07_a09_sample.py"`.
The full command list is in `docs/a07_a09_sample_mode/REPORT.md`, section B; only the runtime path changes.

1. `init --live`, `import-plan --live`, read `plan_repair_audit.json`, then `approve-plan-import --sha 958ea8e0…`.
2. `dry-run`, then the Stage 1 projection and authorization.
3. **CP_SYN and Stage 1:** 3 GROUP calls, RECONCILE, FINAL. Stops at CP3.
4. **CP3, Stage 2 and CP_LEDGER.**
5. **One A09 section.** The state ends at `COMPLETE_SAMPLE`.

The result is tagged `NON_REPRESENTATIVE_SAMPLE`. Its costs are now kept out of the forecast in code:
`litreview cost-rates` and `litreview output-shares` refuse a sample run.

After each paid stage, compare the log with the provider consoles:
`python scripts/reconcile_billing.py <run folder> --billed anthropic=<USD> openai=<USD>`.

## 6. The list, item by item

Status: **Done**, **Partly**, **Not done**, or **Yours**.

### Sample path (items 1 to 9)

| # | Item | Status | Note |
|---|---|---|---|
| 1 | Push `92b2c56` and `715c353`, open PRs | Done | PR #3 and PR #4 |
| 2 | Promoted runtime with both commits | Done | v11, section 1 |
| 3 | Three bugs (double margin, OpenAI input rate, YAML `on`) | Done | Already fixed in `b0c08f4`, with tests; v11 contains the fixes |
| 4 | Dry run, zero network calls | Done | Section 2 |
| 5 | Control-label check | Done | Section 3 |
| 6 | Science review, then approve the SHA | Partly | Review in section 4. Approval is yours. |
| 7 | Note the prompt mismatch | Done | Section 2 |
| 8 | Approvals in order | Yours | Section 5 |
| 9 | Refuse to start when `ANTHROPIC_BASE_URL` or `ANTHROPIC_AUTH_TOKEN` is set | Done | Also `OPENAI_BASE_URL`. Checked at CLI start, at `Run.run`, in the sample launcher and when a client is built; the clients also pin their own endpoints. |

**Found on the way:** the sample launcher would have refused its own A08 call. It decides by the call's trace
which calls a route may serve, and the router passed the trace to Anthropic only. The failure would have
appeared at Stage 2, after the GROUP money was spent. Fixed, with a test.

### P0 submission integrity (items 10 to 15)

| # | Item | Status | Note |
|---|---|---|---|
| 10 | `cite()` drops unknown IDs | Done | The export stops on an unknown or empty citation; nothing is written |
| 11 | `is_retracted()` never called | Done | Called at CP2 (all records, then the selection) and at export. A paper that cannot be checked is listed as unchecked, never assumed clean. An exception needs a written reason in `CP2_approved.json`. |
| 12 | Crossref: retry, cache, title check, `[CHECK FORMAT]`, first author only | Done | Retries with backoff, per-run disk cache, outage distinguished from "not found", DOI title compared with the paper read, fallback keeps every author, no marker ever printed; problems go to `final/submission_status.json` |
| 13 | Declarations are placeholders | Done | Drafts generated from the provenance log into `final/declarations/`. Each blocks submission-ready until a person removes every placeholder and marks it `STATUS: FINAL <name>`. |
| 14 | Table rows are cited CORE papers; table fits one page | Done | Checked in code at export. The page check is an estimate from the Word export's geometry and errs towards "does not fit". |
| 15 | Re-check live guidelines; A12 fails on a broken limit | Done | Page re-read 2026-11-23: no limit changed. The journal says "roughly 5,000 words" and allows 8 display items; 5,000 and 1 are enforced as your choices. A12 stops on any hard limit. |

Check with `litreview submission-check <run>` after editing the declarations.

### P1 reliability (items 16 to 28)

| # | Item | Status | Note |
|---|---|---|---|
| 16 | Truncation loses output | Done | Partial output kept; one retry at 1.5x the cap, never above 64k. A06 batches and vendor-batch items too. Off in the staged pilot, whose holds cover one attempt. |
| 17 | JSON repair resends the input | Done | Repair is made from the saved reply at low effort, with an audit of every changed path |
| 18 | `reserve()` before every A05 to A12 call | Done | Every send on the standard path, retries and repairs included |
| 19 | Caps with no room for thinking | Done | RECONCILE, FINAL, A10 LOCAL and GLOBAL at 16k, medium effort. PLAN was already 32k. |
| 20 | 64k to 128k defaults | Done | Agent defaults are now 12k to 48k; A05 by content level |
| 21 | Kimi never sends `reasoning_effort` | Done | Sent and tested. Kimi accepts `low`, `high`, `max` (not `medium`), so A11 runs at `high`. The 32k reserve stays: whether Kimi counts reasoning inside the cap is not established. |
| 22 | Replace `gpt-5-mini` | Done | `gpt-6.1-terra`, OpenAI's named replacement. No agent was using the alias. |
| 23 | Prompt and schema parity; structured output | **Not done** | See section 7 |
| 24 | General repair-import | Done | `litreview repair-import` |
| 25 | Resume from receipts | Done | Standard path: an accepted output is reused when the request is identical; an output edited after acceptance stops the run. The staged pilot already had its own. |
| 26 | Batch test with `min_items` 3 | Done | |
| 27 | Retire legacy schemas; narrow `except Exception` | **Not done** | See section 7 |
| 28 | Temperature never reaches the API | Done | Documented in config and code; the one wrapper that did send it was unused and is deleted |

### P1 cleanup and prices (items 29 to 36)

| # | Item | Status | Note |
|---|---|---|---|
| 29 | Archive v8, v9, v10, R0001 | Done | Section 1 |
| 30 | Review `model_record.jsonl` | Partly | A refusal now stands only until a person clears it (`litreview clear-refusal`). I did not clear the Opus 5.5 refusals: that should follow the retest in item 44. |
| 31 | Re-measure `cost_rates.json` | Partly | Re-priced without the 19 re-extractions ($8.32 removed; abstract paper $0.43 to $0.23, full text $1.15 to $0.70). It is still the old one-call-per-paper procedure. A true re-measurement on current code needs the calibration run. |
| 32 | `prices.yaml` as the only table | Partly | Source and date per model, 30-day gate, Anthropic and OpenAI re-read 2026-11-23, batch rows added. **Kimi could not be re-read** (its price tables did not render), so Kimi is refused by the gate until you re-check it. No Kimi batch row: see section 7. |
| 33 | Billing reconciliation | Done | `scripts/reconcile_billing.py` |
| 34 | Profiles | Done | `pilot`, `sample`, `manuscript` (review at $120 and $150, hard stop $200, stage sub-caps summing to $150) |
| 35 | Seal one runtime, then sync `main` | Partly | Runtime sealed. `main` not touched: see section 7. |
| 36 | CI; paid scripts out of `tests/` | Done | `.github/workflows/tests.yml`; four scripts moved to `scripts/live/` |

### P2 cost (items 37 to 47)

| # | Item | Status | Note |
|---|---|---|---|
| 37 | A06 per-theme row | Done, with a correction | See section 8: the $14 is mostly real |
| 38 | A10 | **Not done** | Section 7 |
| 39 | A07 | Partly | System prompt was already cached; effort now medium. Batching GROUP and larger groups not done. |
| 40 | A06 retest on CORE only | Done | `validation.instability_tiers: [CORE]` |
| 41 | A09 | Partly | Effort medium. Evidence scope not changed: section 7. |
| 42 | A05 full text for CORE only; saturation stop | Partly | Tier policy done (`extraction.full_text_tiers`). Saturation stop not built. |
| 43 | One critique cycle | Not done | Section 7 |
| 44 | Re-test Opus 5.5 | Yours | Paid |
| 45 | Kimi A/B | Yours | Paid, after the sample |
| 46 | Measured output shares | Partly | The forecast no longer depends on caps. Only PLAN has a measured value; the rest are labelled ASSUMED until the calibration run. |
| 47 | Calibrate on about 30 papers | Yours | Paid |

## 7. What I skipped or changed, and why

**Kimi batch rate (32).** Skipped on purpose. The pipeline has no Kimi batch transport, so a `-batch` price row
would price Kimi work at a discount it cannot get.

**Structured output (23).** I did not switch it on. The schemas use length and count limits that strict
structured output generally does not enforce, so it would not have prevented two of the four PLAN violations
(the 517-character rationale and the 15 finding IDs). A request the provider rejects fails a paid stage, and
this cannot be tested without a live call. Better order: test one mode with `litreview check --ping`, then
enable per provider. The cheap repair-from-reply path now covers the failure meanwhile. Prompt and schema
parity for A07 is in Codex's gap table; a general parity test for every mode is still to write.

**Legacy schemas and broad handlers (27).** Left alone before the sample. The old A07 schemas are referenced by
fixtures and by the frozen run's identities, and removing them changes fingerprints. The handler in the agent
runner is narrowed in comment only: provider SDKs raise unrelated exception families. Do both after the sample.

**A10 on CORE claims only (38).** I recommend against it as worded. A10 is built to review every reader-facing
sentence, and the release gate depends on complete coverage. Limiting the model to CORE claims would leave
non-CORE claims unverified in a manuscript you sign. Cheaper routes that keep full coverage: batch the LOCAL
packets (50% off, they are independent), and re-run the GLOBAL pages only at draft and final instead of at
every pass. Both need work inside the verification job, and I would do them after the calibration run shows
A10's real share.

**A09 CORE-only evidence (41), one critique cycle (43), batching GROUP (39), saturation stop (42).** Each
changes what the science stages see or how often they run. With no prose produced yet, there is nothing to
judge them against. Two specifics:
- With `max_critique_cycles: 1` the run already allows one cycle, and then always pauses: accepting needs a
  second critique call, by design ("never accepted because cycles ran out"). Decide whether a human approval
  may replace that second call.
- A saturation stop is an evidence-selection decision, which the journal's AI policy makes yours. It should be
  built as "code measures novelty, you decide", not as an automatic stop.

**Sync `main` (35).** `main` on GitHub is 28 commits behind this branch, and none of those commits has been reviewed by you there. The PR
for this branch targets `main` and fast-forwards it; merging it is the one click that syncs. I did not push my
own unreviewed work to the default branch.

## 8. The forecast, honestly

Full run of 120 papers, baseline scenario, with the tier policy on (CORE share assumed 40%):

| Stage | Before | Now |
|---|---:|---:|
| A02 to A04 | $4.00 | $4.00 |
| A05 and A06 per paper | $43.38 | $18.66 |
| A06 instability repeats | $16.20 | $2.90 |
| A06 theme pass | $14.76 | $14.96 |
| A07 synthesis | $45.49 | $35.90 |
| A08 outline | $1.36 | $1.25 |
| A09 writing | $28.13 | $23.64 |
| A10 verification | $47.05 | $41.49 |
| A11 critique | $1.97 | $0.85 |
| A12 editing | $4.16 | $2.78 |
| Failed and redone calls | $6.41 | $5.30 |
| **Baseline** | **$212.92** | **$151.72** |
| **Baseline plus 30%** | **$276.80** | **$197.24** |

**The target is not met at 120 papers.** Baseline plus 30% is at or under $150 up to about **80 papers**
($133.56); 100 papers is $154.88.

Three things you should know about these numbers:

1. **Most of the fall comes from policy, not efficiency.** Full text for CORE papers only cuts expected
   findings from 2,017 to 1,581, and everything downstream scales with findings. If more than 40% of your
   corpus is CORE, the cost rises again.
2. **The A06 theme row was not $14 of air.** The old row assumed 279 calls and the code makes 9, but each of
   those 9 calls carries every finding of its theme. At 120 papers that is about 307,000 input tokens per call,
   over the long-context price threshold, and about 29,000 output tokens, over the cap: **the theme pass would
   truncate as written.** It has to be paged before a run of this size (`validation.theme_findings_per_call`),
   and paged and batched it costs about $4 to $5.
3. **The per-paper rates are not from current code.** They are the October run re-priced. The only paper run
   on current code, R0001, cost $3.68 for A05 and $3.38 for A06, against a forecast rate of $0.70. It is an
   outlier (180 findings, and one known cache defect since fixed), but one outlier is all there is.

So items 46 and 47 are the real answer: run the calibration on about 30 papers, run
`litreview cost-rates` and `litreview output-shares --write` on it, and re-run the forecast. Until then every
figure above 28 papers is labelled UNVALIDATED.

## 9. Suggestions beyond the list

1. **Get one section of prose in front of you before any further engineering.** The pilot spent its effort on
   controls and never produced a sentence. The sample exists for this; the remaining P2 items should wait for it.
2. **Page the A06 theme pass** before the calibration run. It is the one place where the current code will
   fail at scale.
3. **Your detailed outline should enter at A08**, as a fixed input the outline agent maps evidence onto, with
   A07's theme framework taken from it at CP1. That removes the PLAN turn's theme proposals and most of A08's
   output, and it is where the outline actually saves money. This is not built; it needs a small schema for the
   outline you provide.
4. **Split `orchestrator.py`** (190 KB, one class) after the sample: staged-pilot code, the standard path and
   the export are three different things. The one-off pilot modules (`plan_retry.py`,
   `r0001_evaluation_driver.py`, `singlepaper_eval.py`, `sample_mode.py`) hard-code dollar amounts and should
   leave the package once the sample is done.
5. **Move the private audit path out of `pipeline.yaml`.** It is a path on your machine in a file that is
   pushed to GitHub. An environment variable would do.
