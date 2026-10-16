# Architecture

## Principles

1. **The researcher is the author.** Perspective, paper selection and conclusions are decided at
   three checkpoints. Agents propose; the provenance log records who decided what.
2. **Code does what code can do exactly.** Searching, deduplication, span matching, number
   matching, citation checks, word counts and reference formatting are deterministic Python.
   LLMs are used only where judgement is needed.
3. **Every claim is traceable.** Finding → verbatim span (A05) → validated disposition (A06) →
   proposition (A07) → sentence tag (A09) → verification (A10).
4. **Auditors use another vendor.** Claude produces; OpenAI verifies (A06, A10); Kimi critiques
   (A11). An auditor never shares a vendor with the work it checks (tested in
   `tests/test_llm_routing.py`), so they don't share the same blind spots.
5. **Contrary evidence is protected at every stage.** Mandatory contrary searches (A03), no
   exclusion for unwelcome results (A04), null findings extracted (A05) and validated as supported
   (A06), carried at equivalent strength (A07–A12).

## Stages

| # | Stage | Agents / tools | Output (`runs/<id>/data/`) |
|---|---|---|---|
| 1 | scope | A02-SP | `spec.json` |
| 2 | **CP1** | researcher | `spec_approved.json` |
| 3 | search | A03-LM (PLAN, REPAIR ≤2), search clients, dedup | `search_plan.json`, `records.json`, `search_log.json` |
| 4 | qualify | A04-CQ (batches; full text for unresolved) | `qualifications.json`, `bias_report.json` |
| 4b | expand | citation expansion (Semantic Scholar, depth 1, from qualified supportive *and* contrary seeds) → A04-CQ on new records | `records.json`, `expansion_log.json` |
| 5 | **CP2** | researcher (every record shown) | `selected_corpus.json` |
| 6 | extract | full-text fetch, A05-KE, identifier lookups (HGNC, MyGene, UniProt, ChEMBL, PubChem, Cellosaurus, OLS4) | `extractions/`, `fulltext/`, `normalization_cache.json` |
| 7 | validate | span check (Gate 1), A06-SV per paper (≤1 re-extraction), A06-SV per theme | `validations/`, `validated_findings.json`, `theme_records.json` |
| 8 | synthesize | coverage manifest (code), A07-SYN | `synthesis_package.json` |
| 9 | **CP3** | researcher | `synthesis_approved.json` |
| 10 | outline | A08-OL | `manuscript_plan.json` |
| 11 | draft | A09-WRI → A10-RV (≤1 redraft) | `manuscripts/` |
| 12 | review loop | A11-RC → A12-EDI REVISION → A10-RV (≤2 cycles) | `rc_latest.json`, `rv_latest.json` |
| 13 | finish edit | A12-EDI LINE → A10-RV → A12-EDI PROOF → A10-RV FINAL | `rv_final.json` |
| 14 | finalize | reference numbering + Nature format, compliance, email | `final/` |

## Run folder

```
runs/<run_id>/
  input/          topic.md, notes.md, seeds.txt
  checkpoints/    CPn_review.md, CPn_decision.json, CP2_records.csv, CPn_approved.json
  data/           everything in the table above
  outputs/        raw and parsed output of every agent call
  final/          manuscript.md, compliance.json, costs.txt, provenance_summary.json
  state.json      current stage and status (resume point)
  costs.jsonl     one line per model call
  provenance.jsonl  one line per agent call, tool run and human decision
```

## Stopping and resuming

A run stops at a checkpoint, when the spend cap would be exceeded, when an agent fails twice
to return valid output, or when a loop limit is reached without acceptance. `litreview run <id>`
resumes from `state.json`; finished per-paper work is never repeated.
