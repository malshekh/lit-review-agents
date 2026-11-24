# Task 1 — Scientific evidence integrity and release gates

Implemented on **`codex/task1-evidence-integrity`**, based on
`554e9715b65db70107056b2b9bfef0e6e991206a`. Changes are uncommitted and unmerged.
The deterministic regressions pass; this is not a scientific-accuracy or full-pipeline-readiness claim.

## Confirmed defects and corrections

| Defect / previous behavior | Implemented behavior |
|---|---|
| A06 SUPPORTED overrode failed source provenance | Recompute Gate 1 from current full text and extraction. Failed span, numerical/unit provenance, premise quote or explicit section check cannot supply any evidence role. |
| Provenance blocks were automatically REJECTED | BLOCKED_PROVENANCE and recoverable deterministic failures are HELD_FOR_CORRECTION. Alignment/extraction rejections and quarantines remain ineligible; no supported disposition is fabricated. |
| Missing quote boundaries lost recoverable evidence | Expand only unique, bounded, literal ellipsis passages or an immediately trailing recorded numerical value/unit. Recheck the entire finding. Preserve original/replacement spans, source section and offsets in `span_corrections`; persist the source repair atomically before A06 sees it. |
| A06 COMPLETE could omit findings or reference other findings | Paper schema requires finding-level results. Runtime requires exactly the submitted ID set, once each, with allowed dispositions, explicit unresolved reasons and valid scientific annotation references. Invalid responses are recorded as rejected and cannot replace accepted validation. |
| Theme validation had no independent acceptance contract | PER_THEME requires its own scientific result objects, matching theme and in-scope conflict references, without paper-level disposition requirements. |
| Cached projections and legacy validation metadata could authorize evidence | Rebuild projections from source extractions and complete A06 records. Missing/changed validation input fingerprints require revalidation; failed provenance remains held. Cached eligibility and ontology identity cannot promote it. |
| CP3 approval could outlive its package or overlook invalid references | Validate synthesis evidence links, source/proposition references and mandatory/finding accounting. Bind the CP3 decision to the exact synthesis-package fingerprint and recheck at consumption. Missing packages cannot be approved. |
| A10 COMPLETE/fingerprint alone could authorize incomplete accounting | Check occurrence inventory fingerprint, unique/exact verdict coverage, scientific check dimensions and global counts. At release, compare reviewed global IDs with the actual registry, propositions, gaps and reconciliation issues. |
| Revalidation/review writes could be interrupted between artifacts | Atomic validation/review writes plus a persisted pending-review record allow deterministic recovery before evidence use. A new validation cannot silently lose its quarantine. |
| A prior human decision could be reused for a different reading | Active decisions are matched to the old/new validation and evidence version; a different comparison requires a new decision. Existing human-decision provenance remains recorded. |
| Provider output could carry internal metadata | Strip provider-supplied underscore-prefixed replay/review/identity fields before deriving trusted metadata in code. |

Gate 1 checks recorded values, numeric p-values/sample sizes/uncertainty fields, and reported units.
It still cannot establish whether a number belongs to the correct biological arm or supports the asserted
mechanism; those are scientific judgments. No neighboring statistical sentence is automatically adopted
merely because it contains the desired numbers.

## Known R0030 cases

- **F18:** existing spacing/display-reference normalization passes; the original quote is retained.
- **F20:** the explicit ellipsis has one literal expansion in the supplied source. The full passage,
  including omitted treatment-arm qualifications, is restored and passes Gate 1. A06 must then validate
  the repaired extraction; repair itself supplies no supported disposition.
- **F21:** statistics lie outside the quoted sentence. The code does not infer their relevance or attach
  them automatically. The finding stays held until corrected and revalidated.

Historical R0030 files were read only. Tests operate on copies and temporary synthetic runs.

## Exact implementation locations

| File | Functions / changes |
|---|---|
| [scientific_validation.py](../src/litreview/scientific_validation.py:9) | New `require_complete`, `require_theme`, `require_package`, `source_fingerprint` deterministic contracts. |
| [span_check.py](../src/litreview/tools/span_check.py:40) | `numbers_match`, `passed`, `repair_findings`. Exact-source recovery and independent numerical/unit checks. |
| [evidence.py](../src/litreview/evidence.py:51) | `status_of`, `classify`: provenance ceiling and recoverable holds; `review_changes`: retain both compared validation entries. |
| [A06 schema](../schemas/A06-SV.schema.json:1) | Conditional PER_PAPER/PER_THEME required fields and disposition structure. |
| [orchestrator.py](../src/litreview/orchestrator.py:698) | `_record_review`: version-bound decisions and atomic persistence. |
| [orchestrator.py](../src/litreview/orchestrator.py:778) | `_save_validation`, `_recover_validation_review`, `_write_validation`, `_require_complete_validation`, `_prepare_validation`: acceptance, source identity, repair and recovery. |
| [orchestrator.py](../src/litreview/orchestrator.py:867) | `stage_validate`, `_instability_test`, `_theme_pass`: validate new/stored/repeated results and separate theme contracts. |
| [orchestrator.py](../src/litreview/orchestrator.py:1071) | `_validated_findings`, `revalidate`, `_findings`: authoritative provenance/eligibility projection, source/finding fingerprints and fresh revalidation inputs. |
| [orchestrator.py](../src/litreview/orchestrator.py:1490) | `stage_cp3`: evidence/package and exact human-approval identity checks. |
| [orchestrator.py](../src/litreview/orchestrator.py:1604) | `_verification_registry`, `_verification_current`: package integrity and actual global evidence-accounting checks. |
| [checkpoints.py](../src/litreview/checkpoints.py:141) | `write_cp3`, `approve`: package-bound checkpoint decisions and complete/eligible evidence references. |
| [verification_job.py](../src/litreview/verification_job.py:91) | `current` only: reject structurally incomplete verification despite a COMPLETE label. |

The A07 and A10 architectures and public interfaces are preserved. A06 dispositions, defect reports,
constraints, attribution, hedging, experimental context and appraisal roles are retained. Repaired findings
carry the original quotation and correction history. Stored findings now carry `provenance_gate1` and
source/finding fingerprints. Existing unversioned evidence does not silently gain current authorization.
Older CP3 approvals need a review of the current fingerprint; no historical approvals were rewritten.

## Validation

**331 tests passed**, including 29 new parameterized integrity cases in
[test_scientific_integrity_gates.py](../tests/test_scientific_integrity_gates.py:1) and two additional
final-release accounting cases in [test_finalize.py](../tests/test_finalize.py:67).
The earlier audit's two defect-demonstration tests now assert the corrected behavior.

Covered cases include fabricated quotes; wrong doses/units; invalid premise quotes and locations;
formatting and literal-boundary recovery; ambiguous recovery refusal; missing/duplicate/unexpected A06
IDs; invalid dispositions/defect references; incomplete validation before A07; independent A07/A10 role
refusal; stale source inputs; missing mandatory coverage; stale CP3 approval; incomplete A10 reports;
missing actual global entries; interrupted commits; quarantine recovery; and stale human decisions.

Unrelated display, identity, repeat-validation and export tests previously used partial A06 results or
quantities absent from their synthetic source quotes. Those fixtures now supply complete validation and
source records through [evidence_fixtures.py](../tests/evidence_fixtures.py:1). The existing scientific
assertions remain exercised; the new failure tests explicitly cover the formerly permissive inputs.

Commands:

```text
python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp tests/.tmp-task1-approved
python -B -m litreview check
git diff --check
```

`litreview check` passed without live connection probes. Diff checks passed. No paid calls, research
execution, new research manuscript, historical-run writes, additional agents, merges or commits occurred.
Budget/routing configuration was not changed; no spending cap was increased.

## Task 2 integration boundary and remaining risks

No A08/A09 writing architecture, downstream evidence-packet generation or context-admission module was
changed. Potential merge conflicts are concentrated in **orchestrator.py** (`_findings`, `stage_cp3`,
`_verification_registry`, `_verification_current`) and shared finalization test fixtures. Task 2 must
retain authoritative source projection, the package fingerprint check, provenance metadata and the exact
global-ID release comparison. `verification_job.py` changes are confined to `current`; its packet
construction, retrieval and synthesis interfaces are unchanged.

The new provenance metadata changes registry/version fingerprints. Previously accepted A07/A10 state
cannot be treated as current merely to avoid revalidation. Pending review metadata must survive any
artifact migration or bridge serialization. None of these changes resolve Task 2's context-size or
full-pipeline financial blockers.

Remaining scientific risks are semantic: claim entailment, contradiction discovery, treatment-arm and
model matching, appraisal preservation in prose, source attribution and study-independence interpretation
still need a blinded live-model evaluation with human scientific adjudication. Structural tests establish
the deterministic gates and recovery behavior, not scientific accuracy or publication readiness.
