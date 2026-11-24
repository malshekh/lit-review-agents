# Interrupted hardening continuation

2026-11-23. Branch `claude/post-pilot-hardening`, existing PR #5. Baseline `c2a00e2`.

## Preserved from Claude

Seven modified tracked files and `tests/test_fulltext_identity.py` were present at handoff. They already
implemented provisional CP2 review and deferred freezing, free access checks before projection, conservative
full-text pricing for unresolved lookups, DOI/PMCID identity checks without PMID, separate legend/image flags,
accounting scaffolding, and the initial three-paper early-check changes. The pilot profile was already
`first_tranche: {papers: 3}`. None of that work was discarded or blindly replayed.

## Finished

- Kept the selection editable after budget rejection; regression changes selection and reapproves CP2 in the
  same run with unchanged discovery/screening data. The reviewed fingerprint must match before freezing.
- Confirmed DOI-only retrieval, cached XML identity checks, provenance and hashes. Missing PMC coverage is
  reported separately from an unavailable lookup and from a failed verification; other access routes are named
  as unattempted. Relevance remains independent of access.
- Propagated legend-versus-image access to extraction, independent validation and downstream agent requests
  and prompts. No text caption sets image inspection true.
- Reused the configured validation/repair path before CP_EARLY. The review includes extraction and validation
  costs separately, their sum compared with the matching CP2 quantity, actual levels, dispositions, comparator
  problems and unresolved access. The revised forecast includes remaining papers, downstream work, and
  conservative theme/retest reserves. Old full-text/abstract tranche preferences remain supported.
- Paid smoke CLI now requires `--run-id`; receipts, actual charges and uncertain reservations share that run's
  allowance. Received receipts recover idempotently. Uncertain dispatched calls remain held and require
  reconciliation, rather than being silently repeated. Derived stage limits leave room for smoke spend.
- Corrected remaining-versus-total account reporting; included unsettled exposure, recovery allowance and
  estimated provider allocation. Combined early extraction/validation allocation is an explicitly approximate
  equal split between their providers. Historical cost procedures remain labelled provisional.
- Added the requested carrier-label sentence in subsection 2.2 and explicit distinctions among corpus coverage,
  access limitations, reporting limitations and demonstrated scientific limits. Reports now tie chapter
  shortfalls to plan warnings/budgets, subsection counts, unmapped/held evidence, retrieval and verification
  records; those outcomes alone do not establish a field-wide gap.

## Offline evidence

Focused regressions passed, including CP2 rejection/reselection, all-abstract/all-full-text/mixed tranches,
legacy tranche resume, DOI-only cache checks, combined smoke/pilot cap, interrupted initial validation and
received smoke-receipt recovery. `tests/conftest.py` blocks sockets and name lookups. The rehearsal removes
provider keys, blocks network calls and uses scripted model output and checkpoint approvals.

The complete discovery-to-export rehearsal passed all nine route checks with seven papers, all eight outline
themes, CP1/CP2/CP_EARLY/CP_SYN/CP3/CP_LEDGER and downstream A07-A12. The replay produced five full texts and two
abstracts; this mix was obtained from fixtures, never imposed. See `OFFLINE_HARDENING_REHEARSAL.json` for actual
rehearsal outputs, early accounts, chapter counts and simulated spending. Local full artifacts remain under
`runs/offline-hardening-final/` (ignored by Git).

The scripted writer produced 71 and 91 words against 800-word targets. This validates measurement and shortfall
reporting, not scientific writing quality or achievement of pilot chapter lengths. Its fake token usage totals
about $9.66 under the real price table; actual provider spend in this continuation is $0. The first three
papers' extraction plus validation totals about $1.04 in simulated accounting. Neither figure is a launch quote.

The first full suite in the existing project virtual environment passed 1,007 tests. Final suite results are
recorded below after the two additional interruption regressions. System Python lacked `python-docx`; no
dependency installation was needed because the existing project virtual environment includes it. A temporary
encoding regression in the continuation was corrected before the passing rehearsal and suite.

## Launch remains human controlled

No paid call, live smoke test, spending approval or scientific approval was performed. The configured $65 cap,
$25/$48 review points and historical $47.79 projection are proposals, not authorization. Current-code live cost
and science remain unmeasured. Verify prices/model availability and review the outline; explicitly approve
spending, build a fresh runtime from the reviewed commit, create the run, and only then authorize the smoke
test with that run ID. Continue the run through each real human checkpoint. Never reuse rehearsal approvals.
An uncertain smoke dispatch must be reconciled from its receipt and provider billing before releasing its
reservation. No merge or force-push is part of this continuation.

Final verification: 1,009 tests passed in 188.14 seconds using the existing project virtual environment (python -m pytest -q -p no:cacheprovider). Final real-loop offline rehearsal: COMPLETE, all nine route checks passed. git diff --check passed. Actual paid spend: $0.
