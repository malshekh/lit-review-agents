# Pilot acceptance criteria

Status: **AGREED** by the researcher on 2026-10-29, with the revisions of that date to criteria 2 and 7, and
committed before the run. The result is judged against this file as committed, not against what the run
produces.

## What the pilot tests

The system as corrected after run 20261025-100039:
- the evidence eligibility and role rules;
- the separation of normalization from validity;
- the OLS4 and Cellosaurus resolution rules;
- the A05 v0.5 predicates and the A07 handoff contract;
- the revalidation review rule;
- the CP2 spend gate;
- the A06 instability test.

The question is whether extracted evidence keeps the following from A05 through A07 and A10:
- its identity;
- its relationship;
- its uncertainty;
- its attribution;
- its validation status.

## Preconditions (the freeze)

- **The run starts from a clean tree at the agreed commit.** The run records this in `input/code_version.json`.
- **Nothing in the system changes during the run.** This covers:
  - prompts, schemas and predicates;
  - normalization rules and ontologies;
  - eligibility and role rules;
  - configuration.
- **The repair loop stays off** (`loops.max_reextractions: 0`).
- **The run is new and separate.** No file is copied from another run:
  - retrieval, full text, extraction, validation and provenance are all the run's own;
  - only the researcher's topic statement and the seed identifiers are supplied.
- **Spend is capped at $35.00, and the cap is not raised.** CP2 refuses a selection projected over the cap.

## Selection

Papers are chosen to test hard distinctions, not easy extractions. The selection is made at CP2 by PMID; the
pilot's own record IDs will differ from the earlier run's.

**Full texts.** These are chosen to stress the context rules.

| PMID | What it tests |
|---|---|
| 34638842 (PMC8508702) | Disulfiram sensitizes therapy-resistant glioblastoma to a TGF-β receptor inhibitor. A combination study scored by combination indices, so synergy and antagonism appear in one paper; this is where `OTHER_SPECIFIED` failed before. It also has several U87MG-family lines, in vitro, 3D and in vivo work, several doses, and a dose-unit inconsistency inside the paper (150 µM in a table, 150 nM in the text). |
| 29211715 (PMC5730499) | Disulfiram targets cancer via NPL4. Four evidence systems in one paper: purified protein (ITC, DARTS), many cell lines, mouse xenografts and registry epidemiology. It also has construct distinctions (GFP-tagged against GST-tagged NPL4). |

**Abstracts.** No PMC full text exists, so these are priced as abstracts.

| PMID | What it tests |
|---|---|
| 30771200 | Multicentre phase II trial of temozolomide plus disulfiram and copper in recurrent, temozolomide-resistant glioblastoma: limited clinical evidence in humans. |
| 27006494 | Disulfiram with copper enhances temozolomide in glioblastoma: a second combination study, in vitro and in vivo, in abstract form. |
| 26254539 | Only if a fifth paper fits the cap. Copper and disulfiram anti-angiogenic activity in vitro, ex vivo and in vivo. |

## Criteria

Each criterion names what is measured, where it is read from, and the rule. "Recorded" means it is reported
whatever the value. "Pass" means the pilot fails that criterion if the rule is broken.

### 1. Entity normalization accuracy

**Recorded:**
- Every entity in the run's extractions, counted by `normalization_state`: RESOLVED, AMBIGUOUS, UNRESOLVED, CONFLICT and NOT_APPLICABLE.
- The same counts for each paper.

**Spot-check against the source.** Each of these is checked by hand:
- every RESOLVED entity in every paper;
- every CONFLICT entity;
- 10 AMBIGUOUS and 10 UNRESOLVED entities, or all of them if there are fewer, chosen at random with a recorded seed.

For each entity, the check asks whether the identifier names what the paper's mention names, using the paper's own expansion of any abbreviation.

**Pass:**
- **(a)** No RESOLVED entity's identity contradicts its source mention.
- **(b)** No identifier attached to a CONFLICT entity appears anywhere outside `normalization_audit.json` and `normalization_conflicts.json`. Specifically, not in:
  - `validated_findings.json`;
  - the A07 corpus;
  - display tables;
  - A10 input.
- **(c)** No abbreviation is RESOLVED except through an expansion found in the paper.

**Not judged:** the share of entities left AMBIGUOUS or UNRESOLVED. That is the cost of the rules, not an error.

### 2. A06 disagreement on repeated whole-paper validation

**Recorded** (from `data/instability_test.json`):
- Disposition agreement and role agreement as counts, for every finding in the repeated papers, with the blocked findings also reported on their own.
- The channel of each call (batch or interactive).
- Any paper skipped because its conditions changed.
- Any comparison invalidated by a replay input that does not match its hash.

**The comparison is controlled.** It is whole paper against whole paper, with:
- the identical saved input (prompt, paper text, extraction, entity identities, Gate 1 results);
- identical model settings.

No single-finding call is part of it.

**Replay inputs are verified by hash.** Each saved input is re-hashed against the hash taken at the original
call, before the repeat and again before the comparison. A mismatch invalidates that paper's comparison. It
is reported under `invalid` and counted in no agreement figure, and it produces no review item.

**Pass:** no paper is skipped for changed conditions; under the freeze, a skip means the freeze broke.

**Every role-changing disagreement is held for adjudication.** No reading is accepted by default. Each held
finding is decided against the source, the extraction and both readings, with its cause recorded (criterion 3).

**No threshold, and no change of procedure on this evidence.** The pilot reports agreement as counts. It does
not make repeated validation standard, whatever the agreement. The repeated papers are those with a blocked
finding, a sample enriched for problematic papers, and four papers cannot estimate how reliable A06 is in
general. With 20 to 40 blocked findings, even full agreement leaves a wide interval (30 of 30 gives roughly
88 to 100%).

### 3. Quarantine frequency, by cause

**Recorded:**
- Quarantined findings as a share of all validated findings.
- Each quarantined finding's cause, classified after reading the source, the extraction and both A06 readings:
  - `BIOLOGICAL_INTERPRETATION`;
  - `EXTRACTION_ERROR`;
  - `CHANGED_CONTEXT`;
  - `UNEXPLAINED_MODEL_VARIANCE`.

A reviewer may propose causes; the researcher confirms them.

**Pass:**
- Every quarantined finding is classified and decided (`litreview review-validation`).
- `CHANGED_CONTEXT` is zero. Nothing changes inside the run, so a non-zero count means the freeze broke.

**Decision rule.** The dominant cause names the next fix:

| Dominant cause | Next fix |
|---|---|
| Extraction error | A05 prompt work |
| Biological interpretation | A06 calibration |
| Unexplained variance where both readings state the same limits | A06 disposition definitions |
| Unexplained variance where the readings differ | Repeated validation |

### 4. Evidence-role enforcement

**Pass.** No finding whose status is anything other than SUPPORTING is used as SUPPORTING or CONFLICTING evidence:
- in any proposition the A07 job accepted;
- in any display table;
- in any manuscript claim A10 checks.

This covers NOT_ESTABLISHED, QUARANTINED, REJECTED, UNRESOLVED and held findings. In addition:
- Every SUBJECT_OF_APPRAISAL link carries its appraisal statement, the record that made the claim, and A06's rationale quoted verbatim.
- Every appraisal binding has an A10 verdict.

**Recorded:** how many attempts code rejected at each point. If there were none, the guard was not exercised by this run, and the report says so rather than counting it as a pass on evidence.

### 5. A07 completion

**Pass:**
- The synthesis job reaches COMPLETE within the cap.
- Every mandatory coverage item is SATISFIED.
- Every SUPPORTING finding is accounted for, either used or listed as unused with a reason.
- No finding that may not be cited is cited.

**Recorded:**
- the number of turns, and turns rejected (truncation or invalid output);
- output tokens per turn against the 48,000 cap;
- peak projected tokens against the context ceiling.

A stopped job is re-projected before it resumes; that is recorded, and does not by itself fail the criterion.

### 6. A10 verification

**Recorded:**
- the release disposition at each pass;
- detail rounds per pass (records requested, sent and ignored);
- input tokens per call.

**Pass:**
- Every A10 call's input is under 272,000 tokens, the long-context price threshold.
- No pass has more than one detail round.
- The final manuscript reaches a release disposition consistent with the deterministic checks. A blocking result is a valid outcome, not a failure of this criterion.

### 7. Actual cost against the CP2 projection, per stage

**Recorded:**
- the actual spend for each stage from `costs.jsonl`, set beside each line of the CP2 projection;
- spend before CP2, which is already in the projection's "spent" figure at CP2.

**Pass:**
- Total spend stays at or under both the cap and the projected total.
- No WORST_CASE line is exceeded. Exceeding one means the worst case is wrong, which is a defect.

**Any WORST_CASE line overrun triggers re-projection before the next call.** This happens when an agent's
spend since the projection exceeds its line, or when a call would go beyond the line's number of calls. Code
then supersedes the projection, and no further call is made until the run is re-projected from actual spend
(`Run._check_worst_case_line`). The overrun still counts against this criterion.

**The $35.00 cap is absolute.** Re-projection never raises it.

A MEASURED_P90 line may be exceeded by chance; each time it is, the excess and its cause are reported.

## Budget

These projections come from `litreview project` arithmetic, with per-paper rates measured on run
20261025-100039. A07 is priced on the corrected basis of 2026-10-29: 25,000 + 1,300 tokens per finding per
call. That is the largest call (FINAL) measured with the real payload builder and the token-counting
endpoint. The earlier basis was 821 per finding, which understated the current payload by about 35%.

| Selection | Projected after CP2 | With pre-CP2 at worst case | Status |
|---|---|---|---|
| 2 full texts + 1 abstract | $31.49 | $34.62 | Within the cap |
| 1 full text + 3 abstracts | $30.49 | $33.64 | Within the cap |
| 2 full texts + 2 abstracts | $33.93 | $37.08 | Within the cap only if pre-CP2 spend is $1.07 or less |
| 2 full texts + 3 abstracts | $39.60 | $42.77 | Over the cap; refused at CP2 |

Each projection includes:
- one whole-paper repeat per paper;
- A07 at worst case (5 or 6 calls, each a full 1-hour cache write plus 48,000 output tokens).

Spend before CP2 (scope, search, qualification) is priced here at worst case on the current routes: every
call at max_tokens, with the earlier run's call counts and input sizes. That comes to $3.13 to $3.17. The
earlier run actually spent $2.07 there, on different models. CP2 adds the actual pre-CP2 spend to the
projection and refuses any selection over the cap.

The runtime gate (`batch.gate_usd`, $150) is checked before every batch. In the pilot the $35 cap binds
first.
