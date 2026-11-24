# Paid discovery pilot: plan, readiness and what needs your approval

Date: 2026-11-23. Branch `claude/post-pilot-hardening`, PR #5. **No paid call has been made. The pilot has not
started.**

## 1. What the pilot does

Your two-chapter outline (`docs/pilot7/outline.json`, written from your text; please check it) is the only input.
The pipeline itself:

1. **Scope.** A02 writes the selection criteria and search concepts from the outline. The eight subsections become
   the themes T1 to T8; A02 cannot replace them.
2. **Search.** A03 plans queries that reach every subsection's questions, including evidence that may answer them
   negatively. The queries run against PubMed, Europe PMC, OpenAlex, Semantic Scholar, PubTator and
   ClinicalTrials.gov.
3. **Deduplication and screening.** Records are deduplicated (versions of one publication merged). A04 screens
   each record against the section questions, giving a reason for every exclusion. Citation expansion runs one
   level, capped at 40 records.
4. **CP2, your first selection decision.** The pipeline proposes seven papers from the screening results: the
   strongest tier first, covering as many subsections as possible, with one contrary-evidence paper if screening
   found any. Access is not a criterion. You confirm or change the marks. More than seven, or two versions of one
   publication, is refused. Free access checks and a provisional budget run before freezing. Over-budget selections remain editable in
   the same run, without repeating discovery or screening. Changed access or selection requires renewed review.
   Your CP2 approval freezes only the reviewed, affordable selection as `data/corpus_manifest.json`.
5. **Retrieval.** For each paper, an open-access full text is sought: Europe PMC by PMID or DOI, then PMC XML,
   with identity verification. Every attempt is logged (`data/retrieval_log.json`). A failure means the paper is
   read as its abstract, recorded as a retrieval limitation, never as an exclusion. A paper with no text at all
   stops the run. Figure legends are read as text; figure images and supplements are not retrieved, and this is
   recorded.
6. **Early check (CP_EARLY).** After three papers are extracted AND independently validated, the run stops.
   `{papers: 3}` accepts any retrieved mix and includes both reading levels when available. The review shows
   actual reading levels, separate extraction/validation costs, dispositions, comparator problems and unresolved
   issues. It compares extraction plus validation with the same CP2 quantity and re-forecasts remaining work.
7. **Extraction and validation.** Extraction, then validation by a different vendor, in batches of 15 findings.
   Every paper with a blocked finding gets a second independent reading, and the theme check is paged where
   needed.
8. **Synthesis, with CP_SYN and CP3.**
9. **Outline and writing.** The outline agent maps the evidence onto your ten sections (CP_LEDGER shows evidence
   outside the outline, and sections the evidence cannot fill). Then come writing, verification of every
   reader-facing claim, two critique cycles, editing, and export.
10. **Report.** `python scripts/pilot_report.py runs/<id>` returns everything you asked for: the two chapters and
    references, chapter lengths against 800 words, retrieval and screening records, extraction and validation
    results, unresolved issues, spending by stage and agent, failures, retries and repairs, and every human
    intervention.

## 2. Readiness evidence (offline; does not count as the pilot)

| Check | Result |
|---|---|
| Discovery rehearsal (`scripts/rehearse_pilot7.py`) | **Pass.** See below. |
| Faults, resume, accounting, budget and specification tests | Pass (`scripts/readiness.py`) |
| 15-paper rehearsal, synthesis to export | Pass |
| Full test suite | Current continuation results: see `HARDENING_RESULTS.md`; 996 passed was historical. |
| Live literature services (`litreview check --apis`, free, 2026-11-23) | PubMed, Europe PMC, PubTator, OpenAlex, Semantic Scholar, ClinicalTrials.gov, HGNC and OLS answered; ChEMBL timed out once (a lookup failure is recorded and does not stop the run) |
| Live full-text fetch (free) | A real open-access paper returned 40 verified sections |
| Provider output contracts | **All 15 complete** (`structured.schema_inventory()` reports no problem; see `schema_repair/REPORT.md`) |
| Live model smoke test | **Not run: needs your approval.** In the existing run, 9 checks need a retest (worst case about $0.21); 6 are reusable |

The discovery rehearsal runs the real run loop from scope to export under the `pilot7` profile and your
outline:

- **What it replays:** real records, full texts, extractions and validations from the October run, on a
  different topic. Scripted models for synthesis onward, and scripted approvals at CP1, CP2, CP_EARLY, CP_SYN,
  CP3 and CP_LEDGER. It shows the route holds; it says nothing about the science or the prose.
- **Replay data left out:** three October findings that fail today's schema (counted in the output).
- **Four real defects it found, now fixed:**
  - The CP2 projection priced verification for a 5,000-word manuscript instead of 1,600 words.
  - Extraction and validation had no stage spending limit.
  - The verification size limit refused a sentence that groups the evidence of two full-text papers. That
    request is about 105,000 real tokens, comfortably within the model's limits.
  - NCBI moved its identifier service and refuses this client, so the lookup now uses Europe PMC first.

## 3. Budget

From the projection the pipeline makes at CP2 (the one that governs spending), for seven papers and 1,600 words.
Per-paper costs are taken at the 90th percentile; the margin is included.

| Stage | Projected | Spending limit (+25% for retries and repairs) |
|---|---:|---:|
| Scope, search, screening | about $1–4 | set from actual spend at CP2 |
| Extraction and validation | $9.90 | $12.38 |
| Synthesis | $11.43 | $14.29 |
| Outline and writing | $8.67 | $10.84 |
| Verification | $13.65 | $17.06 |
| Critique and editing | $4.08 | $5.10 |
| **Total** | **$47.79 (historical provisional)** | **$60.67** |

Proposed `pilot7` limits, for your approval: **review pause at $25 and at $48, hard stop at $65**. The smoke
test must use the pilot run ID; its receipts and uncertain reservations count inside the combined cap.
These figures are NOT spending authorization. The pre-CP2 stages are cheap: screening runs on Haiku, and search planning
takes one or two GPT-6.1 calls.

**What these figures rest on.** They are projections from the October run's costs re-priced, plus assumed output
sizes. The early check is the first real measurement. If the projection made at CP2 exceeds the hard stop, the
run stops at CP2, before any extraction is paid for.

## 4. What needs you, in order

1. **Check `docs/pilot7/outline.json`** against your outline. I kept your wording, and split each section's
   instructions into `questions`, `guidance` and `avoid`.
2. **Approve the spending limits** above, or give your own; I change one line of `config/pipeline.yaml`.
3. **Merge PR #5.** I then seal a fresh runtime from the merged commit (v16 predates these contracts).
4. **Settle the held smoke charge first.** One earlier smoke request (HTTP 400, `req_011ChM1MMKaDrZauPitV2pKC`)
   still holds $0.019586. Read what Anthropic billed for it in the console (Usage / Cost, 2026-11-24
   02:58-03:15 UTC), then run `litreview settle-smoke-hold <id> --reservation <key> --billed-usd <amount>
   --evidence "<what you saw>" --by "<name>" --request-id req_011ChM1MMKaDrZauPitV2pKC --provider anthropic
   --model claude-sonnet-5-5` (the old receipt does not record the last three). Without it, no smoke test can be sent.
   Create the run first with the command below. **Approve the live smoke test separately**, using the current
   estimate, then run `litreview smoke-test --run-id <id> --approve-usd <explicitly approved amount> --by "<name>"`.
   Uncertain dispatches retain their reservations and block retries until reconciled. Received receipts recover
   without duplicate charges. No smoke test or paid call was executed in this continuation.
5. **Start the pilot** in that fresh runtime:
   `litreview new --topic docs/pilot7/topic.md --outline docs/pilot7/outline.json --corpus-mode OPEN_CORPUS --profile pilot7`,
   then `litreview run <id>`. Approve each checkpoint as it comes.

The run stops for you at CP1, CP2 (your selection), CP_EARLY, CP_SYN, CP3 and CP_LEDGER, and at any spending
review point, scientific hold or retrieval failure it cannot resolve itself.

## 5. Known limits of this pilot

- **Seven papers cannot answer every subsection.** Expect gaps, especially in 2.2 (carrier, payload and release)
  and 2.3 (exposure over time). They are reported as gaps, not padded.
- **Access is limited.** Paywalled papers are read from their abstracts. Supplements and figure images are never
  read.
- **Chapter length is a target, not a guarantee.** Each chapter is measured against 800 words at export (±15%).
  A chapter far short of 800 words means the evidence ran out, and the report says so.
- **The search queries are the model's.** You see the search plan's warnings at CP2, but the queries themselves
  are not shown for approval before they run.


Continuation verification and limitations are recorded in `HARDENING_RESULTS.md`. A PMC lookup miss establishes
only that no PMC copy was listed; publisher, other repositories, preprints and author copies remain unchecked.
DOI plus PMCID can verify a paper without PMID; all supplied identifiers must match and cached XML re-verifies.
Figure legends are text only. Image inspection is always false in this route and travels to independent
validation and downstream verification. Subsection 2.2 includes the requested carrier-label caution.
