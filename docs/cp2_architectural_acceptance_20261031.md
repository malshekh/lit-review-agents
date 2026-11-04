# CP2 architectural acceptance and clean-restart decision

Date: 2026-10-31. Development branch: task3-integration; base HEAD 0fda4be62197b72b5ea632af0f125267ae1c24a9. No commit, promotion, replacement run, financial authorization, scientific checkpoint approval or paid model call was performed. Original run 20261030-175321 remains paused at CP2.

## Decision and requirement matrix

Recommend **Option A: a clean new Stage 1 run**, subject to separate approval and a newly frozen, verified runtime. **NO-GO for promotion/execution now**: this task produces an uncommitted development candidate, not a reviewed replacement configuration or deployment. The original runtime must not be patched.

PASS below means the specified offline architectural safeguard passed; it does not mean live-model scientific correctness or new deployment/account isolation has been established.

| Section | Offline verdict | Evidence and limits |
|---|---|---|
| 1 Deterministic membership | PASS | External PMID authority and immutable pre-A04 registry; deliberately false Huang/R0002 membership claim cannot alter membership. Scientific qualification remains A04's responsibility. |
| 2 Explicit FIXED_CORPUS | PASS | Persisted before agents/retrieval, CP1 confirmation, resume fingerprint checks, identifier-only query/source dispatch, expansion short-circuit; explicit OPEN_CORPUS preserved. |
| 3 A03 human input | PASS | Actual persisted warning inspected, underlying prompt/configuration conflict corrected; genuine NEEDS blocks before retrieval. Exact approved response resumes without regeneration. No claim that a live model cannot ask a redundant question. |
| 4 Complete human review | PASS | All six incident questions and criteria defects reach primary CP2 review verbatim with batch/record provenance. Issue acknowledgments bind to the current review fingerprint. |
| 5 Liu extraction material | PASS | Actual public XML exercised through stage_extract and production request serialization; body, structured table and ten linked legends retained. Missing required materials fail closed. Supplements and images explicitly uninspected. |
| 6 Restart comparison | PASS | Clean restart recommended after explicit comparison below; neither option created. |
| 7 Cumulative accounting | PASS | Reviewed cost authority required before run creation; prior full ledger hash and all events reconciled once, duplicate/omitted expenditure rejected. No replacement forecast/fingerprint issued before configuration review. |
| 8 Benchmark controls | PASS | Approved metadata unchanged; seal includes source material/provenance and CP3/A07 artifacts. Existing account-denial evidence remains applicable to original bundle only. New corrected bundle inventory/account verification remains a mandatory promotion gate. Vault not accessed. |
| 9 Offline integration/regression | PASS | 702 passed, no skips/deselections; Task 7 excluded; stress fixtures and all three historical assertions retained. |

## Remaining gaps found in the first candidate and development corrections

The first candidate guarded the staged pilot using inferred pilot/PAPERS state; it did not establish an immutable corpus authority before A02 or require CP1 confirmation. The correction persists input/corpus_policy.json and binds its fingerprint to state; missing/mutated/downgraded staged policies stop dispatch. OPEN_CORPUS requires explicit reviewed mode rather than a fallback from failed fixed-policy resolution.

A04 membership still needed an independent canonical artifact. Before screening, corpus_membership.json now fixes internal-record-to-PMID mapping and required access; conflicting mappings pause. Derived qualifications use this authority, retain incorrect model membership claims in the review, and block OUTSIDE_FIXED_CORPUS exclusions for designated publications.

A03 needed the policy in its actual PLAN/repair payload and an explicit exception to generic mandatory discovery prompt instructions. This is supplied without suppressing genuine NEEDS_HUMAN_INPUT. Approval is bound to agent, step, output, approved scope and policy. Replaying the same accepted output after resolution does not regenerate or repeatedly pause it; a new issue/configuration requires new review.

The initial XML check proved identity/body provenance, not source completeness. The actual public XML also exposed a concrete identity-parser incompatibility: Europe PMC uses pmcid/pmcaid/pmcaiid variants. All are now normalized and must agree. A public structural source contract requires substantive methods/results/discussion, the article table and ten figure IDs. Structured tables retain headings, expanded rows, raw cells, numbers, captions and footnotes. Legends retain figure IDs and graphic links. Verbatim spans remain alongside structured JSON for provenance checks. Missing required tables, legends or body sections stop before provider dispatch; no abstract fallback for Liu.

Source retrieval can precede a newly stale financial identity. Verified cached full text is now reused across the resulting financial pause, avoiding a refetch/timestamp/fingerprint loop. The finalized evaluation seal now includes fulltext, fulltext_provenance, source_readiness and canonical membership so later source mutation invalidates evaluator release.

Finally, a clean run previously risked a fresh budget ledger omitting prior incident spending. An explicit immutable cost-only evaluation authority now reconciles the complete prior ledger and holds; absence of authority stops before creating a run. This is accounting metadata, not inherited scientific evidence or checkpoint approval. Provisioning the real reviewed authority is deferred.

## Exact implementation locations

Paths below are relative to the development repository.

| Safeguard | File/function/line |
|---|---|
| Persisted modes, immutable policy | src/litreview/corpus_policy.py:10 default_policy; :18 initialize; :31 resolve |
| Identifier/source boundaries | corpus_policy.py:60 require_source; :69 require_records; :86 require_query; :105 registry |
| Policy before any agent; explicit scope provenance | src/litreview/orchestrator.py:60 new_run; :350 Run.agent; :546 Run.run; :624 stage_scope |
| CP1 explicit policy confirmation | src/litreview/checkpoints.py:50 policy rendering; :394 approve (confirmation at :402) |
| A03 blocking and retrieval dispatch | orchestrator.py:671 _agent_human_review; :681 stage_search; query admission :719; returned records :729 |
| Expansion guard and canonical A04 membership | orchestrator.py:760 stage_expand; :806 registry; :825 review origin; :834 invalid exclusion; :846 derived membership |
| Per-record issue completeness/current approval | checkpoints.py:97 write_cp2; :177 require_cp2_current; :365 write_agent_review; :415 acknowledgment check |
| Full-text requirement and actual A05 input | orchestrator.py:861 source restriction; :1034 stage_extract; tools/fulltext.py:59 verify_cached_source; :95 fetch_verified_sections; :136 _pmc_identity; :145 _grid; :179 _structured_material |
| Public structural inventory | schemas/source_material_contracts/34638842.json:1 |
| Stage 1-only CP2 cost display/admission | orchestrator.py:969 pilot.project; :984 _cp2_costs (Stage 1 branch :994) |
| Carry-forward costs, unchanged policy | src/litreview/evaluation_budget.py:16 validate; :55 prepare; :64 load; :79 prior; src/litreview/budget.py:150 spent |
| Source-bound financial identity | src/litreview/pilot_authorization.py:88 source_level; :123 identity; source/provenance hashes included |
| Finalized scientific release without key access | src/litreview/evaluation_release.py:15 _snapshot; :53 seal_stage1; :63 require_finalized_stage1 |
| Integration counterexamples | tests/test_cp2_architecture.py:50 onward; tests/test_cp2_integrity.py; tests/test_encrypted_benchmark.py source-seal mutation cases |

A03/A04/A05 prompt versions are 0.4/0.4/0.6. No model-route, cap or price changes. Task 7 files/configuration are not part of the tested incident-only runtime copy.

## A03: exact original persisted content

There is **no literal question field or human-review question in the original A03 artifact**. It would be inaccurate to invent a quotation. Its actual NEEDS_HUMAN_INPUT warning states:

> PubMed, Europe PMC and OpenAlex are enabled. No CORE_TOPIC or CONTRARY_EVIDENCE families have been compiled because their mandatory discovery routing conflicts with the fixed-corpus restriction. A pipeline exception for identifier-only retrieval requires human confirmation.

Source: original outputs/A03-LM_plan.json and data/search_plan.json, preserved unchanged. The inferred request is permission to bypass generic discovery requirements for identifier-only retrieval. It concerns discovery/retrieval permissions, not a missing scientific perspective. CP1 already fixed the three-paper scope in prose; the original generic prompt still mandated discovery and the request lacked deterministic policy authority. The same inconsistency explains both A03's warning and the contrary-evidence expansion defect. Supplying policy and correcting the conditional prompt removes that architectural ambiguity. Mocked COMPLETE responses demonstrate policy delivery, not live-model compliance. A genuine NEEDS response still fails closed.

## Liu material accessible to A05

One unpaid public-source retrieval was used for this audit, not an agent execution: https://www.ebi.ac.uk/europepmc/webservices/rest/PMC8508702/fullTextXML . No protected benchmark was used.

XML: 143,398 bytes; SHA-256 fafbbba12ce79bbee78681e32e1e9595ca9d4b261c96ca94131808a0cc5da44d. Identity agrees across PMID 34638842, PMCID PMC8508702 and DOI 10.3390/ijms221910496. The body includes substantive Materials and Methods, Results and Discussion. One machine-readable table has seven rows, six columns, a header row, 41 nonempty cells and 30 numeric cells. Ten legends are linked to figure IDs. Two supplementary nodes refer to the same ZIP; that ZIP and figure pixels were not inspected. They are marked NOT_RETRIEVED_NOT_INSPECTED / image-only information NOT_EXTRACTED; inaccessible details must not be inferred.

The actual stage_extract builder was exercised in a synthetic temporary run with the cached XML, then serialized through user_parts and Anthropic message_params without sending. The resulting A05 request is 129,411 bytes; section SHA-256 f15583f67ad9ca5bc8462e64fe13746e48f7b4fed5c4bacf0cfd5980a600cbd8. Structured table rows and all ten verbatim legends survive serialization. Lun/Huang payloads contain only Abstract. This establishes input availability and fail-closed behavior, not model extraction accuracy or independent verification of scientific findings.

## Option comparison

| Criterion | A: clean run | B: versioned child |
|---|---|---|
| Scientific reproducibility | Corrected policy from first dispatch; coherent new execution | Requires verifying reused material under changed code/source checks |
| Audit integrity | Incident preserved separately; clean execution trail | Lineage and artifact-by-artifact reuse manifest necessary |
| Contamination | No incident scientific outputs imported | Greater risk from unauthorized records and erroneous screening state |
| Checkpoints | New CP1/CP2/CP3 independently required | Must invalidate or justify every inherited decision |
| Accounting | Prior actual costs carried by cost-only authority | Same cumulative accounting required; no independent allowance |
| Complexity | Simple fresh run, explicit approved scope provenance | Migration/filtering/compatibility and partial-resume logic |
| Benchmark fairness | Stronger fresh evaluation without inherited model conclusions | Must disclose non-independent continuation and reused responses |

**Choose A.** The approximately $0.0154 avoidable expansion-screening cost and $0.0972214 total incident spend do not justify extra migration or contamination risk. This supersedes the first report's child-continuation preference. No child migrator or replacement run was created.

## Financial reconciliation

| Provider | Recorded actual USD |
|---|---:|
| OpenAI (A02/A03) | 0.0776570 |
| Anthropic (three A04 batches) | 0.0195644 |
| Kimi/other | 0 |
| Total | 0.0972214 |
| Outstanding commitments | 0 |
| Remaining absolute $35 ceiling | 34.9027786 |

The existing parent forecast is future $11.91079719375 including its modeled 5% retry share; applying the unchanged 30% margin gives $15.484036351875. Including actuals gives $15.581257751875, with $19.418742248125 forecast headroom. Provider totals under that **parent-continuation scenario**, including actuals and margin, are Anthropic approximately $11.7907133453 and OpenAI $3.79054440657; baseline Kimi $0. Those estimates fit the reported $15/provider funding, but are not balance verification and are **not the clean-restart forecast**.

A clean run repeats A02?A04 and uses corrected prompts and actual full-text material. It must be priced again after the replacement configuration is reviewed. Therefore no new forecast, financial fingerprint, authorization command or spending authority is issued here. Hard cap $35, review checkpoint $25, future admission margin 30%, Stage 2 prohibition and human scientific gates remain unchanged. Prior actuals must be included once, not margined again. Authority snapshots must contain only cost metadata and be readable by the execution account without exposing original research/history.

## Benchmark isolation and preservation

Approved key metadata: SHA-256 11f06c6af3f39067226af27e470d31ac688d3472707d9f52b5e7d239e82632bc; version v2-refined; human approval 2026-10-30; HUMAN_CONTROLLED_ENCRYPTED, HUMAN_ONLY, AFTER_FINALIZED_A07_CP3. No key content was opened, hashed, changed or regenerated; the vault was not mounted. Its dismounted condition remains researcher-attested, not a password/decryption test.

The existing direct LitReviewPilot probe (Public/LitReviewPilotPreflight-20261030/results/post_audit_financial_recheck_20261031T192210470624Z.json) established non-elevated identity and DENIED results for development_repository, development_git_pointer, original_git_history, historical_state, downloads_directory, evaluator_profile and evaluator_audit. It is evidence for the existing environment, not a fresh corrected bundle. The development repository's original history contains a prior unverified draft and must remain inaccessible to scientific execution. Never copy that history or broad docs into the runtime. The offline test copy uses an allowlist: 176 source/test/prompt/schema files matched the intended development candidate with zero mismatches; four Task 7-modified runtime files were restored to HEAD and its diagnostic module/test omitted. It excludes benchmark documents, original Git history, credentials and Task 7; synthetic fixture findings are not human gold answers. A future corrected runtime still requires its own full allowlist, secret/benchmark inventory and direct account-denial verification before GO.

Final A07/CP3 outputs, approvals, source material and provenance must be sealed before independent evaluation. The release API grants no plaintext key access; evaluator-side verification remains researcher-controlled and separate.

## Tests and preservation results

Final incident-only complete suite: **702 passed in 175.03 seconds**, no skips or deselections, exit 0. Includes all three historical-run-dependent tests, using a temporary copy of their 562-file fixture with unchanged assertions. Architecture integration cases: 22; first incident regressions: 30; new source-seal cases: 2 (54 incident/architectural additions over the original 648-test suite). Peak process working set: 701.14 MiB; peak pagefile usage: 720.04 MiB. These are process metrics, not tracemalloc allocation measurements.

All **45 incident files** hash-identical before/after; all **562 historical files** hash-identical. Frozen manifest SHA-256 remains c6205841bc386a11d4580cf12fe1d2c40562778a6b34a826eedee6ea3692cf5a; 6,003 entries checked. Its only mismatch is the previously documented records/model_record.jsonl pilot telemetry change, not a change made by this task. CP2 remains unapproved, stage cp2. Git diff --check passed; HEAD/branch unchanged; changes remain uncommitted.

Verification history is retained rather than hidden: an intermediate test edit caused an encoding collection error; after repair, the first final suite reported 700 passed / 2 failed because new source-seal assertions used POSIX separators for Windows manifest keys. Correcting those assertions to native Path formatting yielded the final 702-pass suite; production seal behavior did not require alteration for those assertion failures. Earlier development-only full run: 699 passed before the final verbatim-span and seal cases.

Evidence files in the private evaluator audit directory: cp2_architecture_accepted_full.txt / .jsonl, cp2_liu_a05_serialization_proof.json, cp2_architecture_preservation.json, cp2_architecture_test_inventory.json. The exact six-question fixture was compared against all three persisted incident A04 outputs; questions and criteria defects match exactly. No protected reference answers are in these reports.

The tests exercise Run.run orchestration, real admission/review paths and production request construction with mocked provider responses. They prove dispatch boundaries, serialization, invalidation, fail-closed behavior and resumption. They do not prove that a live LLM independently detects contradictions, correctly interprets studies or produces scientifically accurate extraction/synthesis. No paid scientific evaluation was executed.

## Proposed archival/restart sequence ? not executed

1. Review this candidate and the exact replacement scope configuration: fixed three papers, Liu full text, Lun/Huang abstracts, approved P1/T1?T5/criteria and all seven qualifications. Record parent CP1 hash as provenance; do not import its approval as new CP1 approval.
2. Keep all 45 incident artifacts immutable, annotate the incident externally, and retain CP2 withheld. Do not rewrite its outputs, financial ledger or original history.
3. After separate approval, selectively commit only incident-remediation changes; exclude Task 7, benchmark drafts, temporary diagnostics and historical data. Freeze a new allowlisted runtime, never patch v2.
4. Provision a researcher-reviewed cost-only evaluation authority binding the full parent cost ledger SHA and all five cost events exactly once, with zero unresolved holds. The scientific account must not need original repository access.
5. Verify new bundle inventory/hashes, configuration and source contracts under actual non-elevated LitReviewPilot, including original repository/history/Downloads/evaluator access denials. Keep the vault dismounted.
6. Only after reviewed configuration and frozen version exist, prepare a fresh Stage 1-only projection and fingerprint including repeat work, prior actuals, retry exposure and provider totals. Obtain separate financial approval. No Stage 2 reservation.
7. Create a fresh run with explicit reviewed scope provenance and FIXED_CORPUS before A02. Require normal CP1/CP2/CP3 and any genuine CP_AGENT_REVIEW; do not automatically approve or resume.
8. Finalize and seal scientific outputs before researcher-controlled independent benchmark evaluation.

**NO-GO for promotion or execution until those review/deployment/financial steps are separately completed.** The offline candidate may be considered for that review; no claim of publication readiness or live scientific correctness follows.
