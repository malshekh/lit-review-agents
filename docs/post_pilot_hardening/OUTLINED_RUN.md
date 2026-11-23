# The outlined 5 + 10 paper run: what is ready, what you provide, and what still pauses

Date: 2026-11-23. Branch `claude/post-pilot-hardening`, PR #5. No paid call has been made. Tests: 985 passed,
0 skipped, every provider key blank.

"No stopping" is implemented as: no avoidable technical interruption. Scientific uncertainty, budget limits and
your approvals still stop the run, on purpose.

## 1. Starting point

- **One authoritative commit.** PR #5 and the local branch are the same commit again. I looked for other local
  follow-up changes across all seven worktrees and found none outside this branch: the only unpushed work was my
  own commits, now pushed. Two other worktrees hold old uncommitted work (`lit-review-gemini`,
  `lit-review-integration`); neither is part of this branch, and I did not touch them.
- **Complete tests with all dependencies.** `pip check` is clean. The three tests that were always skipped need
  the October reference run; they were run against a local copy of it and pass.
- **v11 is preserved** with its history. The new runtime (v12) is built with **no run inside it**: no PLAN,
  approval, finding or financial authorization comes across. Only engineering is reused (vendored packages,
  launcher, model-record telemetry).
- **A new run ID** cannot be created by me: it is created from your outline and corpus manifest (section 3).

## 2. What changed for this run

| Brief item | What exists now |
|---|---|
| Outline and reading tiers as inputs | `input/outline.json` and `input/corpus_manifest.json`, validated and fingerprinted with a snapshot of models, prompt and schema hashes, prices and limits (`input/run_spec.json`). Sections hold questions; a statement is refused as a question and a heading that asserts a result is refused. |
| 5 + 10 selection, no assumed multipliers | The manifest is the corpus: identifier-only retrieval of exactly those papers, no discovery search, no citation expansion. Pricing uses your counts; no CORE share or availability factor. |
| Importance separate from access | `scientific_importance` and `intended_reading_level` are separate fields; a CORE paper read as an abstract is allowed and listed. `actual_access` (full text or abstract, figures inspected, supplements inspected) travels with each paper to every agent. |
| Unmapped evidence | A08 places evidence outside your outline in `data/unmapped_evidence.json`, shown at CP_LEDGER. Sections the evidence cannot fill are reported, not padded. |
| Researcher corrections that act | `litreview decide`: a versioned instruction naming findings, records, sections or themes. It is attached to every request containing what it names, and so enters that request's identity: changing it re-runs exactly the affected outputs. Theme changes go only through `litreview revise-framework`. |
| A06 paging | Token-sized packets, each with the global index of the theme; one reconciliation with the originals of every finding a packet flagged, and up to two retrieval rounds. A conflict found in a packet cannot disappear. No finding is dropped to fit. |
| Contracts and recovery | Prompt contract lines are generated from the schemas (a test fails if they drift). `fivew1h` is replaced by typed `unresolved_questions`. Structured output is used only for model/schema pairs a live smoke test confirms. A repair that loses an evidence ID or a number is rejected. A timeout or dropped connection is recorded as "may have been billed" and the call is not resent until you settle it (`litreview resolve-dispatch`). |
| Job ledger | Every call is written as PREPARED, RESERVED, DISPATCHED, RESPONSE_SAVED, ACCOUNTED, VALIDATED, COMMITTED, or a named failure. A crash after the reply arrives loses nothing and pays nothing twice; a run lock stops two processes. |
| Science rules | Six wording rules are prompt instructions and code checks: copper absence, non-significance as no effect, undefined medians, percentages without a comparator, replication claims, and abstract overreach. Each flag blocks submission-ready until you record a review. |
| Budget | `scripts/plan_budget.py` and the `corpus15` profile (section 4). Stage sub-caps are derived from the run's own projection. |
| Early warning | After one full text and two abstracts are extracted, the run stops (`CP_EARLY`) with findings, comparator labelling and cost per paper against the projection. The rest continues in the same run after your approval. |
| Readiness | `scripts/readiness.py` (section 5). |

## 3. What you provide, and the commands

Templates: `docs/run_spec/outline.template.json` and `docs/run_spec/corpus.template.json`. Every paper needs a
PMID in this version (retrieval is by PubMed identifier). For the five full texts, `actual_access.level` must be
`FULL_TEXT` and the full text must be obtainable from PMC or placed by hand in `data/fulltext/<record>.json`.
If one is not, the run stops rather than reading it as an abstract.

Run these in v12, under the `LitReviewPilot` account, in a shell without `ANTHROPIC_BASE_URL`,
`ANTHROPIC_AUTH_TOKEN` or `OPENAI_BASE_URL` (the pipeline refuses to start otherwise):

1. `litreview spec-check --outline outline.json --corpus corpus.json` — free. Fix what it lists.
2. `python scripts/plan_budget.py --full-text 5 --abstract 10 --words <your outline's total>` — free.
3. `litreview smoke-test` — free: lists the 15 model/schema pairs. Then, with your approval,
   `litreview smoke-test --approve-usd 1 --by "<your name>"` (worst case $0.44).
4. `litreview new --topic topic.md --outline outline.json --corpus corpus.json --corpus-mode OPEN_CORPUS --profile corpus15`
   — prints the new run ID.
5. `litreview run <id>` and the checkpoints as they come: CP1, CP2 (the selection must equal the manifest),
   CP_EARLY, CP_SYN, CP3, CP_LEDGER (read the unmapped-evidence queue), then the review loop and export.

After each paid stage: `python scripts/reconcile_billing.py runs/<id> --billed anthropic=<USD> openai=<USD> kimi=<USD>`.

## 4. Budget for 5 full texts and 10 abstracts

From `scripts/plan_budget.py`, for a 5,000-word manuscript, with the four parts kept separate:

| Stage | Expected | Sub-cap (expected + 30% + 15% recovery) |
|---|---:|---:|
| A02 to A04 | $4.00 | $5.98 |
| A05 and A06 | $5.52 | $8.26 |
| A07 | $8.35 | $12.49 |
| A08 and A09 | $6.47 | $9.68 |
| A10 | $24.83 | $37.13 |
| A11 and A12 | $2.49 | $3.73 |
| **Total** | **$51.66** | **$77.27** |

Uncertainty allowance $15.50; recovery allowance $10.11; smoke test $1.00. Largest single reservation: $2.08
(an A07 reconciliation). Profile `corpus15`: review at $50 and $70, hard stop $80; the sub-caps and the
smoke-test allowance fit inside it. Other scenarios: low $35.39, high $96.99, adverse $434.26 (the adverse case
reruns every verification packet at every pass; the hard stop prevents it).

With a 3,000-word outline the expected total falls to $43.47, because verification scales with the prose, not
with the number of papers.

**What these figures rest on.** Per-paper costs are the October run re-priced, not current code; most
output-size figures are assumptions. Treat them as a plan, not a measurement. The first three papers (CP_EARLY)
are the first real measurement: compare them with the projection before approving the rest.

## 5. Readiness

`scripts/readiness.py` result on this commit (report in `docs/readiness/readiness.json`):

| Check | Result |
|---|---|
| Faults: malformed output, truncation, timeout, dropped connection, crashes between ledger states, reordered and missing batch results, refusals, repair that loses evidence | pass |
| Resume: accepted outputs reused; a changed decision invalidates only its descendants | pass |
| Accounting: every finding has a disposition; every claim has a verification verdict | pass |
| Budget: recovery calls reserved; no borrowing between stages; derived sub-caps | pass |
| Specification: outline and manifest route, source access, early check | pass |
| Rehearsal: 15 papers through A12 and export, with two injected call failures | pass: 211 findings, A10 approved, 193 of 193 occurrences verified |
| Live smoke test | **not run**: needs your approval |

Two limits of this demonstration:

- **Scripted models.** The rehearsal uses scripted models: it shows the machinery holds, not that the science is
  good.
- **Coverage of the chain.** It starts at A07. The stages before it (search, CP2, extraction, validation) are
  covered by their own tests, not in one chain.

**Found by the rehearsal: the table.** With 15 papers the comparative table can hold up to 25 rows. In the
rehearsal it was estimated at 5.1 pages against the journal's one-page limit, and the export listed it as a
blocker. Real cells may be shorter, but plan to choose the rows at CP_LEDGER (about 6 to 8 rows fit a page),
or lower `bridge.table_max_rows`.

## 6. Not done, and why

- **The orchestrator is not split up.** The brief's six responsibilities exist as modules (`run_spec`,
  `decisions`, `job_ledger`, `budget`, `structured`), but `orchestrator.py` (about 200 KB) still holds the
  stages. Splitting it now would touch every stage and test just before the run; better after it.
- **A07 GROUP packets** are still sized by finding counts (24 per group) plus a context-window check, not by
  expected output. A06 is paged as asked; A10 packets were already sized by tokens. A07 at 238 findings is about
  11 groups, well inside the limits, so I left its identities unchanged.
- **No new extraction fields.** Dose, comparator, values, n and test are recorded in A05's context and quantity
  fields as before. I did not add a check that each usable finding has all of them, because "not reported" is a
  legitimate value for most.
- **Kimi structured output** stays off (JSON mode only) until its schema support is confirmed.
- **New run ID and v12 runs.** Both wait for your outline and manifest; I did not invent either.

Your earlier decisions on the old R0001 PLAN, CP_SYN notes and the copper wording are **not** carried into the
new run. If you want the copper wording rule there, record it after CP2 with `litreview decide`, naming the
findings once they exist.
