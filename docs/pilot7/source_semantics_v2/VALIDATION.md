# Offline validation

- Full suite: `python -m pytest -q --tb=short` ? **1,143 passed**, 202.65 seconds.
- Final focused replay/production-boundary suite: `python -m pytest tests/test_source_semantics.py -q` ? **7 passed**, including the subsequently added raw-response/read-only replay entry-point regression.
- Complete-contract, ordinary-JSON and semantic focused suite: **70 passed**.
- Identity/review/semantic focused suite after neutralizing unsupported approval assumptions in two identity-only fixtures: **36 passed**.
- Bridge/writer suite: **52 passed**.
- `git diff --check` passed.

The full suite collected the first six new source-semantic tests. The seventh
new test was added afterward and passed in the final focused suite; CI will
collect 1,144 tests. The full suite's independent socket-denial fixture prevents
network dispatch. No provider keys were read or displayed by replay, no provider
call was made, and no scientific checkpoint was approved.

The production handoff test executes Run._validate_papers, exact A06 input saving,
Run._save_validation, Run._validated_findings and writer packet serialization with
an archived A06 response as offline plumbing data. This is not represented as a
new independent scientific assessment. The stale-input regression holds all
corrected functional findings for revalidation when only the original A06
fingerprints are available.

All 149 original live-run files were rechecked unchanged after the replay/tests.
This includes 25 strict-check receipts, the failed result, both raw model replies,
the financial ledger and all five unresolved reservations. The earlier failed
gate remains false; the versioned replay did not replace it or its fingerprint.
