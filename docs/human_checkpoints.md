# Human checkpoints

You'll get an email at each one (if SMTP is configured). Files are in `runs/<run_id>/checkpoints/`.

## CP1 — Scope & perspective
Read `CP1_review.md`. In `CP1_decision.json`:
- `selected_option_id`: the perspective you choose (e.g. `"P2"`); `edited_angle`: your rewording, if any.
- `approve_selection_criteria: true`, or put your edited criteria in `edited_selection_criteria`.
- `answers_to_questions`: answers to the agent's questions.

Then `litreview approve <run_id> CP1`. To have the agent redo the scope with your feedback instead:
`litreview revise <run_id> CP1 --feedback my_feedback.md`.

## CP2 — Select papers
Open `CP2_records.csv` (Excel or VS Code). **Every** record is listed: all tiers, unresolved and
excluded, sorted by tier. Put `Y` in `select` for each paper to use; optionally set `tier_override`.
Check the bias report in `CP2_review.md` (contrary-evidence exclusion rate, excluded seeds,
papers per theme). Then `litreview approve <run_id> CP2`.

## CP3 — Approve the argument
Read `CP3_review.md`. In `CP3_decision.json`:
- `selected_thesis`: e.g. `"T1"`.
- `adopted_interpretations`: IDs of proposed interpretations you adopt as your own view; they are
  written as "we propose…". Everything not adopted is dropped.
- `edits`: any changes to the thesis or title wording.

Then `litreview approve <run_id> CP3`, or `litreview revise <run_id> CP3 --feedback …`.

## Other pauses
The run also pauses (status shows the reason) if A08 cannot fit the selected papers into the
journal limits, if critique cycles run out without acceptance, or if final verification does not
approve release. Each points you to the file to read.
