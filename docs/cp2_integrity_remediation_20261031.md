# CP2 scientific-integrity incident: root cause and development remediation

2026-10-31. Parent run: `20261030-175321`. **CP2 approval withheld; execution remains NO-GO.** Frozen runtime `stage1-runtime-task6d-20261030` / `620a91697b3ab0e114d1e61b330defee6327f33f` remains unchanged. No paid call, research retrieval, scientific checkpoint approval, spending authorization, vault access, merge, push or commit occurred during this work.

Development corrections and synthetic regressions are prepared, uncommitted, in `task3-integration`. They have NOT been copied into the frozen runtime. Pre-existing Task 7 edits and the pre-existing deletion of `docs/pilot_reference_findings.md` are preserved. Task 7 diagnostics remain disabled; they must be excluded from any incident-only promotion unless separately reviewed. No benchmark contents were read or used in tests.

## Incident findings and exact frozen code paths

Frozen paths below are under `C:/Users/maykh/LitReviewStage1/execution-20261030-v2/src/litreview/`. Development references later in this report refer to the integration worktree. These two versions must not be conflated.

| Finding / priority | Root cause in frozen implementation | Classification | Demonstrated impact | Why previous tests missed it |
| --- | --- | --- | --- | --- |
| Unauthorized expansion / P0 | `orchestrator.py:692-718`, `Run.stage_expand`, reads global expansion enablement and calls `choose_seeds`. `tools/literature/expansion.py:19-32` selects qualified contrary records independently of the A03 family list. Huang R0002 was contrary; an empty family list did not disable that branch. No fixed-corpus dispatch guard exists. | Policy enforcement | 30 additional forward-citation records entered records.json and were screened in B002/B003; $0.0154465 of additional recorded screening. All 30 remained EXCLUDED; the three intended papers remained QUALIFIED. | `tests/test_expansion_and_dedup.py:6` deliberately proves contrary seeds are included outside named families, appropriate for open-corpus work. It never combines this with a staged fixed corpus. Screening tests use legacy/non-staged state and do not assert zero dispatch for unapproved identifiers. |
| A03 NEEDS_HUMAN_INPUT ignored / P0 | `orchestrator.py:628-654`, `stage_search`, executes plan query families immediately after receiving JSON. `_execution_report` (670 onward in frozen file) checks source errors and seed recall, not semantic plan status. | Human-review/policy enforcement | Known-item queries and all subsequent A04 screening proceeded without resolving A03's explicit protocol exception. A03 itself was an authorized planning call; the failure starts at continuation. | Mock plans contain successful query families; tests check retrieval/financial mechanics and usually omit NEEDS_HUMAN_INPUT. No post-response semantic-status stop was asserted. Ordinary conftest also mocks financial guards except marked guard tests. |
| Wrong R0002 assertion / P1 | `orchestrator.py:728-736` passes batch records and expansion seed_record_id, but no canonical registry linking an absent seed to its PMID. A04 B002/B003 turned incomplete local context into an unsupported assertion that R0002 was outside the corpus. | Model interpretation/identifier error, amplified by missing grounding | False human-review questions/warnings. The actual record still correctly maps R0002 to Huang PMID 30771200, and Huang remains QUALIFIED/CORE. No actual bibliographic substitution or incorrect exclusion of Huang occurred. | Schema-valid strings and record dispositions do not establish natural-language truth. Tests check IDs/provenance and screening fallback, not cross-batch seed namespace grounding. |
| Six questions omitted / P0 | `_qualify_pending` at `orchestrator.py:735-745` persists per-record qualifications; top-level queues/criteria defects survive only in raw outputs. `checkpoints.py:89-143`, `write_cp2`, renders counts, CSV, bias and themes without those fields. A03 status/limitations also are not surfaced. | Checkpoint presentation/enforcement | Primary CP2 review omitted B001's one, B002's three and B003's two questions and B002 criteria-defect discussion. Raw outputs remain intact. No CP2 approval occurred, so downstream harm was prevented by researcher review. | `test_screening_provenance.py:64` checks screener identity and split bias display; `test_theme_framework.py` checks themes/emerging evidence. Neither asserts preservation of top-level review queues or acknowledgment before approval. |
| Full-pipeline OVER_CAP display / P1 | `orchestrator.py:835-853`, `_cp2_costs`, unconditionally calls generic `cost_projection.for_selection` at 844. That includes A08-A12 and inferred seven themes. Actual staged admission at `orchestrator.py:820-825` correctly calls `pilot.project(STAGE_1)`. | Financial checkpoint presentation | Misleading ~$54.73 OVER_CAP display. No demonstrated cap increase, Stage 2 approval or Stage 2 call. The correct Stage 1 projection is $15.5812578 including actual spending. | `test_pilot_authorization.py:29` tests Stage 1 project lines and excludes manuscript agents; it does not render `_cp2_costs` or inspect CP2_review.md. Generic report and scoped admission were tested separately. |
| Liu full text absent; verification gap / P0 before extraction | Screening is abstract-first (`orchestrator.py:730-757`); qualified Liu bypasses optional full-text screening. Materialization is deferred to `stage_extract`, `orchestrator.py:875-888`. `fetch_sections` (`tools/fulltext.py:15-39`) fetches sections but does not verify article IDs; failures return empty and extraction falls back to abstract. `content_level` (`tools/cost_projection.py:117-122`) uses PMCID/section count, not verified identity/body provenance. | Expected deferred work PLUS a reproducible source-verification gap | No Liu full-text retrieval/inspection or A05 call has occurred. This is not a demonstrated live download failure. Synthetic counterexamples show an unverified two-section cache is accepted by the old builder; abstract-only records with a PMCID can also cause full-text fetches. Neither latter scenario has occurred in the live run. | Prior financial tests pin source labels and test identity changes, not XML-to-publication identity/body checks. Legacy tests mock section maps and exercise downstream findings, not the actual source-materialization boundary. |

Cost impacts overlap: B002/B003 are part of the A04 continuation after the ignored A03 status. Do not add those causal amounts together as independent spending.

## Scientific assessment

All three designated publications remain QUALIFIED: Liu R0001 SUPPORTING, Huang R0002 CORE, Lun R0003 CORE. Their PMIDs, authors and titles in the saved records match the designated identities. No substitutions or selected_corpus artifact exist. Thirty neighbours were retrieved and screened, but none entered an approved evaluative corpus. There are no extraction/validation artifacts. R0002's false outside-corpus claim is a model error, not evidence that Huang's PMID is wrong.

The six questions are in raw A04 outputs; they were not deleted from history. Their absence from the main review is nonetheless a substantive oversight failure. In particular, expansion suggestions must not be interpreted as permission to expand the approved corpus.

Liu's source remains a PMCID plus abstract, not inspected full text. The original financial/source-level guards may stop an abstract fallback indirectly, but they do not prove that a cached/body-containing text belongs to the right publication. Identity, body presence and provenance must be checked directly before dispatch. A section-count label does not provide that guarantee.

## Minimal development corrections prepared

| Correction | Implementation | Scope / limits |
| --- | --- | --- |
| Fixed identifier boundary | New `corpus_policy.py:10-45`; orchestrator `_execute_plan` and `_qualify_pending` validate queries/returned records before dispatch or screening; `stage_expand` exits before seed choice/network/screening in staged fixed mode. | Uses the existing explicit `pilot.PAPERS` authority, not a guess from scientific prose. PubMed/Europe PMC queries must be identifier-only and contain approved PMIDs. Unexpected source results cause a visible pause before scientific screening. A provider can return an erroneous response despite a valid query; that is rejected, not silently included. Open-corpus legacy behavior, including contrary-evidence expansion, is retained. |
| Genuine human-input checkpoint | `_agent_human_review`, `checkpoints.write_agent_review`, new CLI checkpoint `CP_AGENT_REVIEW`. | NEEDS_HUMAN_INPUT stops before query dispatch or further screening. Approval is bound to output, step, agent and approved scope, with explicit continuation and resolution notes. It cannot waive fixed IDs, access limits or financial gates. Accepted A04 dispositions are saved before pausing; resume does not re-screen them. |
| Canonical identifiers | Explicit record_id / PMID / DOI / fixed-membership / required-access registry in A04 input and CP2 review. Structured wrong/duplicate IDs, PMID-as-record-ID and false OUTSIDE_FIXED_CORPUS classifications are blocked. | Raw model prose is preserved for audit, not silently rewritten. Supplying a registry does not prove a live model will stop making natural-language mistakes. Human review sees authoritative mapping alongside raw claims. |
| Complete CP2 review | Persist top-level warnings, limitations, queues, criteria defects and registry in screening_review.json. Include A03 status/warnings and source readiness. Bind approval to current review/source fingerprints, require explicit acknowledgment/notes, archive prior CP2 views and retain CSV choices across regeneration. | Six-question preservation is tested, not presumed. Structured conflict cannot be overridden merely by acknowledging a note. Source changes invalidate approval/review. Human notes do not themselves establish scientific correctness. |
| Stage-scoped cost view | `_cp2_costs` uses `pilot.project(STAGE_1, records=qualified)` and a Stage 1-only JSON display for staged runs. | Same provider prices, $35 cap, $25 review checkpoint, 30% future margin and Stage 2 prohibition. Legacy generic reports remain available outside staged mode. No new cache discounts or paid calls introduced. |
| Required source verification | `tools/fulltext.py:56` verifies cached provenance and `:92` materializes/validates XML PMID/PMCID/DOI and nonempty body. Exact XML bytes retained base64 with hashes for reinspection. Both full-text screening and extraction use it for required Liu text. | Abstract-only Lun/Huang never trigger full-text fetches even if metadata later contains a PMCID. Missing/invalid/mismatched/abstract-only XML or unverifiable/tampered cache pauses before model dispatch. Source evidence hashes join financial identity. Identity/body verification does not certify scientific completeness, appendix retrieval or correct interpretation. |

No scientific findings, tiers or author interpretations are generated or rewritten by these corrections. The existing live qualifications are preserved. Source parsing remains conservative: unsupported/malformed body layouts stop rather than silently establish full-text readiness. Liu's actual XML has not been fetched or validated in this task.

## Reproductions and verification

Nine counterexamples were run against the actual frozen functions, with synthetic temporary runs and mocked dispatch; the frozen module path was explicitly verified. All nine fail the required assertions in the frozen implementation: fixed expansion, broad/unapproved query, unexpected returned PMID, outside-corpus screening, ignored human input, Stage 1 cost display, six-question visibility, unverified full-text cache and abstract-only access with a PMCID. This establishes runtime counterexamples, not paid live-model interpretation failures.

`tests/test_cp2_integrity.py` adds 30 parametrized offline cases. Requirements covered:

- Zero expansion or out-of-corpus screening dispatch in fixed mode; query preflight occurs before the first source request. Unexpected provider records cannot enter screening.
- Existing three qualified records survive unchanged; no unnecessary new screening.
- A03 human-input stop before retrieval; fingerprint changes invalidate prior review. A04 human pause/resume retains accepted qualifications without duplicate model calls.
- R0002 maps to PMID 30771200; external PMID strings cannot masquerade as record IDs; false structured outside-corpus membership is rejected.
- All six questions and criteria defects appear in the primary CP2 package. Approval requires acknowledgment; changed sources invalidate it; regeneration preserves edits and archives previous views.
- Stage 1 report excludes A08-A12 and agrees with scoped budget admission.
- HTTP/parse/identity/body failures, missing cache provenance and source/cache tampering block dispatch. Verified synthetic Liu XML is accepted and reused. Lun/Huang remain abstract-only despite PMC metadata.

Focused related suite: **86 passed** (30 new cases plus existing screening, expansion, theme and pilot-finance tests). Working-tree full-suite checkpoints: **708 passed in 165.47s** and **710 passed in 162.93s**, no skips; these preceded the final access-aware pricing and stale-regenerated-review refinements. The final incident-only patch is separately validated against the committed baseline with Task 7 excluded: **678 passed in 168.29s**, no skips, deselections or resource failures (648 original tests plus 30 incident regressions). Peak working set **690.03 MiB**; peak process commit/pagefile usage **719.18 MiB**. This validates the incident-only patch without Task 7. Logs: `$env:TEMP/cp2_incident_only_corrected_full.txt` and `.jsonl`.

The first isolated-copy attempt was misconfigured: placing its repository directly under Windows Temp put pytest's synthetic evaluator keys inside REPO_ROOT.parent, correctly triggering the existing key-isolation guard (56 setup errors). Omitting .gitignore and two safe metadata validation reports caused three additional fixture failures (617 passed). A repeated run was stopped once that layout problem was identified. The corrected copy uses a nested workspace and includes exactly those required non-benchmark metadata files; no guard, threshold or test is weakened or skipped. An additional unchanged Task 7 focused invocation lacked sandbox permission to pytest's temp root (32 fixture errors); with permitted, fresh temporary storage it passed **34/34 in 4.31s**. Failed/aborted setup runs are retained as evidence and are not counted as passing validation.

All network connections and provider calls are blocked/mocked in regression tests. Three historical-dependent tests use the established temporary fixture-copy harness; they are not skipped or weakened. These tests establish structural safeguards and preservation/validation, not a live LLM's ability to discover or correctly interpret scientific relationships. They do not inspect the protected reference key.

## Preservation and financial reconciliation

**All 45 original live-run files are byte-for-byte unchanged** from the before-task snapshot. CP2 remains unapproved and the state remains paused. All immutable frozen files match the manifest; the only pre-existing permitted difference is `records/model_record.jsonl` from the five already completed pilot calls. All **562 original historical-run files** remain unchanged. No original artifact, checkpoint, configuration, spending authority or baseline tag was rewritten.

Incident-only source/test content fingerprint: `18543e0cc3e34baa4de433d2047b4eb52af45ea31dd969292d277d6b7d726ff0`. This identifies the seven uncommitted source/test files, not an execution authorization. The incident-only test copy matches these bytes exactly and excludes Task 7 source/configuration changes. The report is the eighth incident file.

The original run still has CP1 approved, CP2 withheld, Stage 2 unauthorized, and zero outstanding reservations. Five prior model calls total **$0.0972214**: OpenAI $0.0776570 and Anthropic $0.0195644. The additional expansion-screening calls cost $0.0154465; that cost remains counted, not erased or refunded by this report.

Recomputed unchanged Stage 1 projection:

| Item | USD |
| --- | ---: |
| Actual recorded spending | 0.0972214 |
| Commitments | 0 |
| Future including existing 5% retry allowance | 11.9107972 |
| Future including 30% margin | 15.4840364 |
| Actual + margined future | **15.5812578** |
| Remaining actual $35 cap | 34.9027786 |
| Forecast headroom | 19.4187422 |

Supplemental routing-aware allocation, using the previously disclosed historical ratios for combined paper stages: projected total including actual/margin **Anthropic $11.7907; OpenAI $3.7905**. Kimi/other have no baseline planned Stage 1 spend. Each fits the user's originally reported $15 provider funding, assuming no other account charges. No live balance was queried; provider allocations are estimates, not provider-specific hard ceilings.

No source verification request, re-screening or new scientific generation was executed. The forecast has not measured Liu full-text request sizes or model responses. Actual source/evidence additions and any necessary retries must be reprojected using the candidate's production builders before execution.

**No replacement live financial fingerprint or spending-authorized baseline was issued.** Development changes do not authorize modifying the existing execution environment. Any new runtime/source/configuration/corpus/provenance bytes require new runtime/configuration/run/financial fingerprints, a new pending request and explicit human review. Old fingerprints must never be relabelled as covering this patch. Task 7 changes must not slip into that promotion. Current configured limits remain unchanged.

## Safe continuation decision and minimal rollout plan

**Do not resume the original run under either its old code or a copied-in patch.** Under old code the failures remain. A new code version invalidates scientific/financial identity, and the new hard boundary rejects the existing 33-record working set. Naively calling the new stage logic can also invalidate accepted-output replay and cause redundant paid work. Rewriting records.json down to three entries in place would obscure the actual incident.

Recommended: a **new versioned child continuation run**, not a fresh scientific evaluation from scratch. It is a new run record with explicit migration/lineage; original ID/files remain an immutable incident baseline. This is a proposed procedure, NOT implemented or authorized here:

1. Researcher reviews the candidate patch, tests, current incident disposition and migration plan. Commit only reviewed incident changes separately; do not mix Task 7 diagnostics into the runtime.
2. Produce a new sanitized runtime from the reviewed commit. Verify source/vendor inventory, isolated non-elevated LitReviewPilot identity, protected-path access denials, no benchmark/plaintext/development-history material, and disabled diagnostics. Preserve old freeze unchanged.
3. Prepare an explicit migration manifest binding parent run and hashes. Import only approved CP1 scope/criteria/themes/qualifications, the three designated bibliographic records and their existing source-provenanced qualifications. Preserve all original raw outputs, 30 excluded neighbours, warnings and history in the parent/audit archive. Do not import an approval for CP2 or any financial authority.
4. Attribute inherited artifacts to their original agent/model/prompt/version; never represent them as outputs of the new code. Import prior actual costs once as identified carry-forward accounting. The child must retain the same **global $35 evaluation cap**, $25 review point and $0.0972214 already spent, not receive a fresh $35 allowance. Audit totals must deduplicate lineage rather than sum parent and carry-forward ledgers as new charges. Implement/test this migration explicitly before use; no migration tool has been claimed ready here.
5. Resolve the inherited A03 identifier-only protocol exception through the fingerprinted human-input review; regenerate a complete three-record CP2 package with canonical registry and all incident dispositions. Keep all 30 additions excluded. Human CP2 review/approval remains required.
6. Prefer explicitly authorized source preparation before the regenerated CP2 review: materialize and verify Liu's authorized full text, without model calls. The normal expected stage remains extraction, but preparing it before the replacement CP2 package permits review of actual source readiness and stable source fingerprints. Preserve raw source/provenance and bind them into the new review/authorization. Never upgrade Lun/Huang access or use the evaluator key.
7. Recalculate production request/cost limits and fingerprints after source materialization and migration. Test stale approvals, interruption/resume, carry-forward budget accounting and zero out-of-corpus dispatch using this exact candidate bundle. Obtain final human financial authorization for the exact new package, then a separate explicit launch decision.

A full restart rerunning A02/A03/A04 is not scientifically required by the observed incident: valid metadata/qualifications and the human scope can potentially be reused with explicit lineage. Such reuse is conditional on the migration checks and human review above; it is not proof of source completeness or a waived checkpoint. If lineage/cost/source identity cannot be verified, a clean new run is the fallback, with old spending still included in the same evaluation cap.

## Explicit remaining validation requirements before promotion

- Test the actual child migration tool before using it: parent SHA preservation; exact three-ID filtering; original qualifications/attribution retained; all prior costs carried exactly once; no duplicated model calls; no inherited CP2/financial approval; no Stage 2 reservations.
- Run verified Liu source materialization only when explicitly authorized; check its real XML layout, identity, sections/figures/tables and access completeness. Synthetic XML tests establish the guard, not actual source availability or scientific completeness.
- Repeat bundle-level offline identity/access/inventory/request-builder/financial preflight against the final incident-only sanitized runtime. Generate final fingerprints only after the reviewed commit, source records and migration inputs are fixed.
- A later paid scientific evaluation remains separately authorized. No mock test proves live-model truth, contradiction discovery or correct interpretation; canonical identity checks and complete human review reduce propagation risk without establishing scientific accuracy.

## Remaining decisions

- Accept/revise the development patch and new human-review control; no frozen promotion yet.
- Approve a child-continuation/migration design, including once-only cost carry-forward and parent evidence isolation.
- Decide how/when to authorize public Liu full-text materialization; no retrieval has occurred here.
- Review the regenerated CP2 package and new final financial request only after those steps.

CP2 remains withheld. No executable financial-authorization or launch command is provided by this incident report.
