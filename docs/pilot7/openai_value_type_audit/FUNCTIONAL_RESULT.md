# Live A05-A06 functional result

Run `20261123-214928`. Only the prepared functional task was dispatched. Its approved fingerprint remained `076cd17577f92a2b65429e62f368874a08da3030484ac5c517afca77e6c21e97`, and it reused the successful OpenAI A06 submitted-schema hash `157cbeb66719080072638fdd497a2d4f42ee6c1897a1f10c00271e84ca1389b6`. No further A08 or other strict check, scope call, or scientific checkpoint approval occurred.

The source is three cached abstract sentences from PMID 38768767 / DOI 10.1016/j.ijrobp.2024.05.009, concerning LC-MS measurement, plasma/tumor detection and DSF dose. The full supplied excerpt and its provenance remain in [source_and_expectations.json](../a05_functional/source_and_expectations.json), and exact finding quotes remain in the unmodified A05 raw/canonical files under the runtime. This source is an isolated engineering fixture outside discovery/corpus data.

| Finding | Extracted meaning | Supporting source location | Independent A06 result |
|---|---|---|---|
| F1 | Diethyl-dithiocarbamate-copper detected in plasma | Supplied Abstract, sentence 2, retained verbatim | SUPPORTED_WITH_CONSTRAINTS |
| F2 | Diethyl-dithiocarbamate-copper not detected in tumors; A05 uses NULL polarity | Supplied Abstract, sentence 2, retained verbatim | SUPPORTED_WITH_CONSTRAINTS |
| F3 | Maximum tolerated DSF dose with RT/TMZ: 375 mg/d | Supplied Abstract, sentence 3, retained verbatim; raw quantity/unit unchanged | SUPPORTED_WITH_CONSTRAINTS |

A06 constrained F1 to reported detection, without a numerical concentration, frequency or sampling time. For F2, non-detection does not establish molecular absence, failure of tumor penetration or lack of activity; detection limits and sampling details are absent from this excerpt. For F3, the value is the abstract's reported dose in the combination regimen; it does not establish safety or recommended dosing beyond that context. A06 also noted that the supplied sentences do not independently establish the study design.

**No expected scientific fact was omitted.** A05 produced all three findings, including the contrary/non-detection result and the reported dose. However, the automated functional gate remains **failed**: F1/F2 share matrix text `plasma and tumors`, whereas the fixture requires separate matrix strings; their shared comparator is `NOT_APPLICABLE`, whereas the fixture requires `NONE_REPORTED`; and F2 uses `NULL` rather than expected `NEGATIVE` polarity. These are reported separately from the actual A06 dispositions. No criterion was relaxed or waived.

The prepared runner initially stopped on the expectation mismatch before independent validation. A small audited continuation retained that failure and collected the already authorized independent A06 diagnosis from the saved locally valid extraction. It did not rerun A05 or modify its output. The canonical contract, supplied source, expected findings, A06 schema, fixed caps and approved fingerprint were unchanged. The functional result remains rejected, even though the independent validator supports the three claims with constraints.

A05 also labeled the metabolite `ENDOGENOUS_METABOLITE` and DSF `APPROVED_DRUG` without a source status citation in the supplied excerpt. Those labels remain visible in the raw/canonical output; they are not established by the three sentences. A06 did not issue an entity-type defect report. This is a remaining review concern, not a claim that the trial or field lacks evidence.

| Cost | Actual USD |
|---|---:|
| A05 extraction (one call) | 0.062332 |
| Independent A06 (one call) | 0.0431735 |
| Functional task total | 0.1055055 |
| Approved ceiling, including bounded repairs | 0.594 |

No format repair was used and no new unresolved hold arose. A06's actual billing includes 9,587 implicit cache-write tokens; the ledger preserved that class. Recorded run spending is **$0.1762446**. All five holds remain unresolved at **$0.124671**; cumulative recorded plus held exposure is **$0.3009156**, leaving **$0.6990844** under the $1 cumulative smoke cap. The $50 pilot cap and $25/$48 review points remain. All 25 existing smoke receipts and original hold records were verified unchanged, and raw functional responses/ledger receipts are preserved.

The final live runtime is `execution-20261124-v26-pilot7-functional-only-50usd`, commit `7da52ebd2db6d05c4bd387e389edf843b9a04830`, manifest SHA-256 `3315560c9d4977ce631a65db59f049d53e6f69b49530c6455151d0cefaeeca09`. It retains the original A06 schema, separately from the unexecuted OpenAI type fix. See `functional_result_summary.json` for artifact references and per-finding A06 constraints.

Further paid checks and scope remain paused. CP1 is not ready, no scientific checkpoint was approved, and full-text extraction remains untested.
