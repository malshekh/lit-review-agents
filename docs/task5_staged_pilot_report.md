# Task 5 — staged pilot authorization and financial safeguards

Implemented on `task3-integration`, based on `0eeec9b`. The original pre-commit validation snapshot is preserved below; final commit details and remaining human prerequisites are in [the Stage 1 handoff](task5_stage1_handoff.md). No pilot, paid call, manuscript generation, key approval, historical-run write, cap/model/prompt change, merge, push or tag was performed.

## Decision

**PASS for offline technical validation.** Two complete clean-process regression runs pass after the diagnosed memory corrections. The stage-specific financial controls and their regression tests are implemented. Live execution remains unauthorized until the researcher verifies/freezes the external reference key and explicitly approves the current Stage 1 projection. Structural tests and historical replay establish orchestration behavior, not scientific accuracy or a guarantee of completing within $35.

## Files and functions

| File | Changes |
|---|---|
| `src/litreview/pilot_authorization.py` | New `project`, `admit`, `request`, `approve`, `require`, `identity`, `work_basis`, `completed_credit`, `selection`, `scientific_ready`, `record_key`, `key_metadata`, `partial`, and run-local `journal`. |
| `src/litreview/orchestrator.py` | `new_run` defaults new runs to `STAGED_PILOT`; `Run.run` guards phase transitions and remains at CP3 without Stage 2 approval; `agent` guards dispatch and reuses exact accepted outputs; `_reserve` guards before creating commitments; `_batch_gate`, `_require_projection`, `_supersede_projection`, `_reproject`, `_downstream_gate`, and `stage_cp2` respect staged scope. Existing bounded A07/A10 and bridge reservation call sites use `_reserve`. |
| `src/litreview/agents/base.py` | `run_agent` accepts an optional `dispatch_guard`, which runs before each provider attempt, including existing JSON repair attempts. Scientific validation and retry limits are unchanged. |
| `src/litreview/budget.py` | `record` optionally links usage to its reservation; `reserved` subtracts already billed usage from that hold, including interruptions between logging and cleanup. |
| `src/litreview/batch_stage.py` | `_submit` uses the run's scoped reservation wrapper before upload/create. Authorization is checked before even a context-count API call. Existing vendor separation, worst-case pricing and batch recovery remain. |
| `src/litreview/cli.py` | `cmd_project`, `cmd_pilot_reference`, and `cmd_authorize_stage` expose `project RUN --stage 1|2`, `pilot-reference RUN --metadata FILE`, and `authorize-stage RUN 1|2 --fingerprint HASH --reviewer NAME`. Projection alone grants no authorization. |
| `tests/test_pilot_authorization.py` | 44 financial/authorization regression cases; marked `projection_guard` so the repository's default fixture does not replace financial gates with mocks. |
| `tests/staged_pilot_simulation.py` | Reproducible no-generation historical replay using actual production A07 builders; writes only fresh temporary diagnostics. |

Existing recorded legacy runs retain their legacy execution mode; historical state is not migrated or altered. New runs always enter staged mode. This task does not authorize resuming a legacy scientific run. Future production-run authorization is separate work; $150 is a future target and $200 remains unauthorized.

## Authorization behavior

Stage 1 status is `STAGE_1_AUTHORIZED`: A02–A07 only, pinned to Liu PMID 34638842 full text, Lun PMID 27006494 abstract, and Huang PMID 30771200 abstract. The actual CP2 selection/source types must match. No A08–A12 request or reservation can use this approval.

The authorization fingerprint includes run ID, input hashes, selected/planned papers, code/prompt/schema/config file hashes, current configuration, model routes, prices/calibration, projection, approved reference-key metadata, and upstream evidence. Accepted evidence/configuration/plan changes can require renewed approval; completed files and spending are retained. Explicit reprojection and superseded forecasts invalidate stale financial approval. This conservative policy may pause between evidence updates; it never silently extends authorization.

CP3 scientific approval still runs normally. A separate `FULL_PIPELINE_AUTHORIZED` approval is required for A08–A12. Before approval, current CP3/synthesis/eligibility accounting is checked through the existing scientific contract, and outstanding reservations must be reconciled. A refused or missing Stage 2 approval leaves the state at CP3 with `COMPLETED_STAGE_1_PARTIAL_EVALUATION`, not a failed manuscript evaluation. A subsequent valid Stage 2 approval clears that partial marker without deleting work.

For staged runs only, the journal profile passed to planning/writing targets 1,500 main-text words; the global 5,000-word profile is untouched. The existing comparative-table and all scientific/release gates remain. No A06 subdivision or A07/A10 redesign was introduced.

## Finance and recovery

Admission uses Decimal comparison:

`actual spent + outstanding commitments + 1.30 × uncommitted future forecast <= $35`

Only future work receives the margin; it is not billed and does not lower the actual cap. The existing $25 committed-spending review remains separate and stops before requests that would exceed that point. $35 equality is allowed; amounts over it are refused.

The projection includes the pre-CP2 allowance, P90 extraction/validation, instability repeats, theme validation, A07, cache writes and configured future retry allowance. Pilot paper work is conservatively projected interactively; execution batch configuration is unchanged. Candidate/batch work is excluded from future estimates before its strict reservation is counted. Logged usage offsets its own outstanding hold exactly once. Unknown/unmapped commitments stop for reconciliation rather than receiving speculative credits.

Stage 2 starts from actual approved synthesis/findings/propositions and its current plan. Accepted, logged, hash-matching requests receive modeled forecast credits so their work is not forecast again. Credits are bound to evidence, plan, code/prompt/configuration and prices; altered plans do not inherit stale credits. These credits are estimates of completed request cost, not changes to billed spend. Existing byte-bound long-context pricing gates remain active, with long-tier calls explicitly priced and counted in the staged forecast. A10 retains its existing conservative calibration; this task does not claim Stage 2 will fit.

Accepted identical outputs can be reused after interruption, with schema/hash checks and known hold cleanup. An uncertain submission remains held and is not automatically resubmitted. Failed/uncertain calls require billing/output reconciliation; completed scientific work is not deleted. Per-request and per-batch strict reservations remain independent of the modeled admission forecast.

## Reference-key boundary

No real reference key has been approved. `docs/pilot_reference_findings.md` is untouched and remains an unverified draft.

A human-supplied metadata record must contain `version`, lowercase SHA-256, private key `commit`, `verified_by`, `approved_at`, `store_path`, and `human_verified: true`. The key must be outside the framework workspace and run paths. Finance verifies its binary hash; no contents are copied into run data, retrieval or generation payloads. The human attestation/commit metadata is not a software certification of scientific correctness. A changed/missing/unapproved key blocks authorization.

Once the researcher has independently verified and committed/frozen the key, the intended manual sequence is:

1. Record its metadata with `pilot-reference`.
2. Run `project RUN --stage 1`; review its exact projection/fingerprint.
3. Record explicit financial approval with `authorize-stage RUN 1 --fingerprint HASH --reviewer NAME`.
4. Resume only after all existing scientific checkpoints are satisfied. Reproject/reapprove when dependencies change.
5. At completed CP3, request a fresh Stage 2 projection and independently approve it only if it fits actual remaining funds. Otherwise retain the completed Stage 1 partial evaluation.

These commands were not executed against a real pilot.

## Updated Stage 1 projection

The runtime's initial calibrated forecast is **$16.4025 baseline / $21.3232 with contingency**:

| Item | Before future retry/margin, USD |
|---|---:|
| A02–A04 allowance | 4.0000 |
| A05 + initial A06, two abstracts | 1.2628 |
| A05 + initial A06, one full text | 1.9877 |
| A06 instability repeats, all three papers | 1.1802 |
| A06 theme validation, eight modeled calls | 0.7408 |
| A07 calibrated request model | 5.1739 |
| Conservative A07 system-cache writes | 1.2760 |
| Subtotal | 15.6214 |
| Future retries, configured 5% | 0.7811 |
| Baseline | **16.4025** |
| Admission with 30% future contingency | **21.3232** |

The production-builder replay of the actual three historical papers (R0030/R0159/R0040) gives **$15.9327 / $20.7125** under the same paper-cost basis. It has 55 historical findings, 223 mandatory items and 21 scripted A07 requests:

| Mode | Calls | Production byte input bound, total | Output allowance, total |
|---|---:|---:|---:|
| PLAN | 1 | 73,333 | 4,000 |
| GROUP | 18 | 637,643 | 216,000 |
| RECONCILE | 1 | 21,208 | 6,000 |
| FINAL | 1 | 47,273 | 6,000 |

Every request fits the configured limit. A07 input is modeled as byte bound / 2.1; output/thinking is modeled at 50% of its shared output cap, with modeled retrieval and cache misses. No new provider count or billed generation cost is claimed. The replay retains 65 legacy theme records and is deliberately not presented as a newly approved scientific framework. A02–A06 are priced from calibration, not regenerated. Scripted COMPLETE proves structural accounting for the fixture, not correct scientific interpretation.

The previous $15.52/$20.17 result is not silently reused: it used largest-paper stand-ins, component-wise P90 tokens, a different theme fit, and provider counts. The new result uses the pinned papers' historical evidence and existing saved P90 dollar rates; the runtime additionally budgets more conservative A07 cache exposure. Both updated projections fit $35, but a fresh authorized live projection and all hard runtime stops remain required. Neither estimate guarantees completion under adverse retries/retrieval.

## Final memory diagnosis and validation (2026-10-30)

**PASS for this offline technical validation; paid execution remains unauthorized.** No stress fixture was reduced, test deselected from the complete runs, MemoryError caught/suppressed, context limit increased, or scientific safeguard changed.

### Confirmed cause and production exposure

`tests/bridge_fixtures.py:237` (`oversized_package`) creates 3,720 propositions, multiplying each proposition's constraints to the union for its theme. The unchanged fixture serializes to 189,194,848 characters; the complete Unicode JSON string alone occupies 378,389,754 bytes. This deliberately adversarial replication magnifies the issue; it is not a measured live 120-paper workload.

The original `Run.save` performed `json.dumps(..., indent=2)` followed by `Path.write_text`. Instrumentation reproduced the section and critique MemoryErrors at `TextIOWrapper.write`, after successful JSON construction. Full-document Unicode, Windows newline/encoding buffers coexist. Tracemalloc attributed the retained 361 MiB string to `json/encoder.py:263`. Once a test fails, pytest's failure traceback retains that string: live traced allocations rose from about 419 MiB after the first failed save to about 788 MiB after the next. This explains cascading pressure without establishing a separate application memory leak.

Fixing the save alone exposed two additional confirmed failures: `fingerprint(pkg)` at `canonical(value).encode()` during outline preparation, and `Run.load` at `Path.read_text` during section preparation. The save-only intermediate run had one pass and two MemoryErrors; it was not accepted as a solution.

These are **shared production code paths**, not a test-only defect. A large accepted package could encounter them in A08/A09 preparation; A11/A12 also use shared persistence/fingerprint utilities. The tested correction removes those avoidable copies. It does not turn JSON decoding or request construction into constant-memory operations or prove arbitrary unbounded inputs safe. Existing per-request admission still decides whether provider dispatch is permitted.

### Minimal corrections and regression coverage

| File / function | Exact correction |
|---|---|
| `src/litreview/orchestrator.py:112`, `Run.save` | Stream `json.dump` chunks into a unique temporary sibling, close, then `os.replace`. Encoding failure, interruption and replace failure leave the accepted artifact intact; temporary files are cleaned. No evidence fields or values are omitted. |
| `src/litreview/orchestrator.py:125`, `Run.load` | Load through a text stream with `newline=""`; JSON consumes CRLF whitespace directly, avoiding full-document universal-newline translation. This still decodes the complete JSON document. |
| `src/litreview/synthesis_registry.py:21`, `fingerprint` | Incrementally hash `JSONEncoder.iterencode` UTF-8 chunks with the same canonical options. Digest compatibility is regression-tested; no A07/A10 protocol, scientific rule or interface changes. |
| `tests/test_run_persistence.py:7` | Verify chunked Unicode persistence without whole-document `dumps`, exact content round trip, and bounded writes for the fixture. |
| `tests/test_run_persistence.py:31` | Three failures injected separately: unsupported value, interrupted encoding, failed replacement; accepted bytes survive and temporary files disappear. |
| `tests/test_run_persistence.py:56` | Three canonical digest compatibility cases, including Unicode/nested and repeated large strings. |
| `tests/test_run_persistence.py:64` | CRLF JSON whitespace, embedded CRLF string values and missing-file default remain correct. |

`tests/test_bridge.py` and `tests/bridge_fixtures.py` are unchanged. No fixture cleanup workaround, forced GC, larger resource allowance or limit relaxation was required.

### Memory measurements

Same three oversized tests, same fixture, separate processes, Python 3.14, tracemalloc depth 1 and Windows `GetProcessMemoryInfo`. MiB uses 1,048,576 bytes. Working set varies with Windows paging; committed/private process memory and Python-traced allocations are separate measurements.

| Scenario | Result | Peak working set MiB | Peak process commit MiB | Peak traced Python MiB |
|---|---|---:|---:|---:|
| Original save, before correction | 1 passed, 2 MemoryErrors | 950.14 | 1,867.95 | 1,331.09 |
| Save correction only | 1 passed, 2 MemoryErrors elsewhere | 992.74 | 1,651.43 | 1,064.42 |
| All three minimal corrections | 3 passed | 906.31 | 1,050.83 | 788.19 |

In the successful profiled run, live traced memory returned to approximately 57.5 MiB after each outline/section case and 10.3 MiB at session end, after fixture teardown. The measured accumulation in failing runs is consistent with retained failure frames; successful runs do not show that pattern. No stronger leak-free claim is made.

### Regression results

| Run | Result | Duration | Peak working set MiB | Peak process commit MiB |
|---|---|---:|---:|---:|
| Oversized outline individually, fresh process | 1 passed | 8.51 s | 759.82 | 859.45 |
| Oversized section individually, fresh process | 1 passed | 12.46 s | 682.38 | 858.94 |
| Oversized critique individually, fresh process | 1 passed | 4.62 s | 185.81 | 182.48 |
| All three together, allocation profiling | 3 passed | 81.93 s | 906.31 | 1,050.83 |
| Complete suite, clean process 1 | **476 passed, 0 skipped, 0 deselected** | 123.77 s | 794.97 | 906.59 |
| Complete suite, clean process 2 | **476 passed, 0 skipped, 0 deselected** | 124.22 s | 701.66 | 907.99 |

Both complete runs use the unchanged pytest discovery set, with cache provider disabled and production source unchanged between runs. All 44 Task 5 authorization cases passed in both. A separate focused run passed all 44 plus the eight new persistence/hash cases (52 total, 7.40 s). No paid/free provider endpoint was used; existing autouse tests block network connections.

An earlier instrumented full-suite attempt stopped after 332 passed tests because the temporary logger called `json.dumps` while the new streaming test deliberately patched it to fail. That diagnostic-harness error is not a suite PASS or production failure. Binding the logger's serializer before tests resolved it; the two complete results above are subsequent fresh runs. The initial sandboxed profiling attempt also hit temporary-directory permission errors; successful runs used authorized access, not enlarged memory limits.

The three historical tests ran, rather than skipping, in **both** complete runs:

- `test_run_20261025_known_errors_stay_rejected_and_normalization_blocks_are_held`
- `test_run_20261025_meaning_survives_serialization`
- `test_live_a06_conflict_output_strips_the_identity_and_keeps_the_findings`

The temporary diagnostic pytest plugin points only these tests at a fresh copy and removes their unavailable-fixture skip markers once the copy exists. The handoff test's `RUNS_DIR` is scoped to that copy during its call; all original assertions execute. Copies were `task5-historical-rpvj7tzf/20261025-100039` and `task5-historical-intx1emm/20261025-100039` under the Windows temporary directory. SHA-256 manifests compared every relative filename and file's contents before/after each full run: **562 original files unchanged**, both times. Original source: sibling `lit-review-agents/runs/20261025-100039`. No historical fixture was added to this worktree.

### Admission and safeguard preservation

Fresh individual stress runs reached actual production `admission.assess`; all had `fits=false`, raised the expected safe Pause, and the scripted dispatch hook would fail the test if called:

| Agent | Input byte bound | Output/reasoning reserve | Context window |
|---|---:|---:|---:|
| A08-OL | 6,141,294 | 32,000 | 1,050,000 |
| A09-WRI | 23,738,189 | 16,000 | 1,000,000 |
| A11-RC | 6,729,219 | 64,000 | 1,048,576 |

These are unchanged conservative request byte bounds, not provider token counts. Existing A12 oversized-manuscript unit-splitting tests also pass in both full runs.

All 44 authorization tests use the real financial guards via the existing `projection_guard` marker: Stage 1 cannot dispatch or reserve Stage 2; approval is separate; margin applies only to future uncommitted work; exact $35 cap and $25 review boundaries stop correctly; unknown commitments pause; accepted resume avoids duplicate calls; uncertain submissions remain held; missing, altered, unapproved or workspace-exposed reference keys block. `tests/test_pilot_authorization.py:122,177,183` check CP3 science/financial separation explicitly.

Scientific/release regressions also pass: `test_scientific_integrity_gates.py:33,54,83,141,203` (Gate 1, accepted A06 results, source identity and CP3); `test_bridge.py:324` and `test_integration_safeguards.py:133` (CP_LEDGER/current plan); `test_contrary_evidence.py:128,155,179,216` (contrary accounting, A10 and final release); `test_finalize.py:68` and `test_integrated_pipeline.py:32` (current complete verification). Existing orchestration fixtures script model responses and selectively mock unrelated guards; passing them establishes the asserted runtime behavior, not live scientific interpretation or discovery.

### Offline forecast, checks and decision

The repeated `tests/staged_pilot_simulation.py` run is unchanged: 55 findings, 223 mandatory items, 65 legacy theme records, 21 scripted A07 requests, structurally COMPLETE, every request within configured admission, **zero generation calls**. Diagnostics are in `%TEMP%/task5-offline-siedlueg`; machine-readable stdout is `%TEMP%/task5_final_offline_stdout.json`.

- Runtime baseline: **$16.40248719375**, rounding to **$16.4025**.
- Future-work 30% admission margin: **$21.323233351875**, rounding to **$21.3232**.
- Cap: **$35**, unchanged; the $25 review point is unchanged.
- Request-builder modeled scenario remains **$15.93272025 / $20.712536325**. It is a separate scenario described above, not a recalibration of the runtime forecast.

`litreview check` passed locally without `--ping` or `--apis`; credentials were loaded only into that child and values were not printed. `git diff --check` passed. Configurations, prompts, schemas, historical artifacts and the unverified reference draft remain unchanged. At the original validation snapshot, branch was `task3-integration`, HEAD `0eeec9b`, with changes uncommitted and unstaged. The subsequent approved logical commits and final checks are described in the Stage 1 handoff and final response.

Temporary diagnostic harness: `%TEMP%/task5_memrunner.py`. Detailed measured logs: `task5_memory_before_real.jsonl`, `task5_memory_after_trio.jsonl`, `task5_memory_after_trio2.jsonl`, `task5_memory_full1.jsonl` (harness-aborted), `task5_memory_full2.jsonl`, `task5_memory_full3.jsonl`, and `task5_memory_individual_{outline,section,critique}.jsonl` in `%TEMP%`. Full runs used `python -X utf8 -B %TEMP%/task5_memrunner.py -q -p no:cacheprovider` with `HISTORICAL_SOURCE` set to the original run and `NO_TRACE=1`; the profiled trio enabled tracemalloc. These are temporary evaluation artifacts, not historical-run edits.

**Original pre-commit recommendation: commit Task 5 after review.** The user subsequently authorized the logical Task 5 commits; see the Stage 1 handoff for that finalization. The memory/regression blocker is resolved for the unchanged stress workload. Remaining prerequisites before paid execution: independent human verification and protected freeze of the real reference key, review/approval of the selected source types and scientific framework, and explicit current Stage 1 financial authorization. Stage 2 still requires current CP3 scientific approval, reconciled spending, a fresh affordable projection and separate approval. This PASS grants no scientific approval or spending authority; no pilot has begun.
