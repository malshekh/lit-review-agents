# Revised CP2 proposal - run 20261123-214928

**CP2 remains pending. No corpus freeze or paid call was made.** This revision implements the researcher-requested list from the existing screened pool; it is not a corpus approval.

The original automatic proposal and review files are preserved under `cp2_revision_20261125/original` in the run. Added: R0078, R0115, R0039. Removed from the draft: R0004, R0131, R0032, R0060. Those removals are researcher-requested selection changes, not new scientific exclusions. Search and screening were not repeated.

| Publication | Role / manuscript coverage | Target, specimen, model output and reason | Actual access and identity |
|---|---|---|---|
| **R0078**: Israel AR et al. (2026). [Optical Spectral Fingerprinting Enables Sensitive Detection of Anthracycline Chemotherapeutics in Synthetic Clinical Biofluids.](https://doi.org/10.1021/acs.nanolett.6c01777) | Direct oncology; Learning from signals and fingerprints; Evaluating accuracy, uncertainty and generalization; Drug identity and concentration | Four anthracyclines; synthetic urine/sweat. Concentration-category classification and reported spectral separation; numerical-estimation and post-dose claims are not established by the saved abstract. Adds an optical nanotube sensing modality. | Published full-text XML: PMC13397890, PMID 42409644; own title/DOI/PMID matched. **Image-only Table 1 blocks strict source materialization.** Full-text priced; not yet extractor-ready. |
| **R0115**: Chen B et al. (2025). [Application of surface-enhanced Raman scattering combined with artificial intelligence for multiplex detection of chemotherapeutic agents used in solid tumors.](https://doi.org/10.1007/s00216-025-06241-z) | Direct oncology; Learning from signals and fingerprints; Drug identity and concentration | Six chemotherapeutic drugs in serum (experimental setting unknown at screening). CNN classification and reported numerical regression. Multiplex example; no independent analytical reference, simple baseline or split unit established from the abstract. | Matched abstract only: PMID 41324706, DOI 10.1007/s00216-025-06241-z. Wrong PMCID quarantined. Publisher page has abstract and purchase/subscription options, no article body. |
| **R0090**: Litti L et al. (2021). [3D Printed Microfluidic Device for Magnetic Trapping and SERS Quantitative Evaluation of Environmental and Biomedical Analytes.](https://doi.org/10.1021/acsami.1c09771) | Direct oncology; Learning from signals and fingerprints; Evaluating accuracy, uncertainty and generalization; Drug identity and concentration; Exposure trajectories and limitations | Erlotinib in aqueous standards and ethanol-deproteinized spiked human plasma; PLS numerical concentration. Preserves weaker plasma signal, higher LOD, interference and no post-dose measurement. Simpler calibrations concern other analytes. | Verified PMC8397251 XML; title, PMID 34256559 and DOI 10.1021/acsami.1c09771 rechecked. Cached strict source verified before budgeting. |
| **R0116**: Ilchenko O et al. (2024). [Optics miniaturization strategy for demanding Raman spectroscopy applications.](https://doi.org/10.1038/s41467-024-47044-7) | Direct oncology and methods; Learning from signals and fingerprints; Evaluating accuracy, uncertainty and generalization; Drug identity and concentration | Methotrexate in PBS/methanol standards; SERS/PLS concentration. Instrument-reference example; HPLC comparisons apply to other analytes, not MTX. Included in six; omitted in the requested five-paper fallback. | Verified PMC11001912 XML; title, PMID 38589380 and DOI 10.1038/s41467-024-47044-7 rechecked. Cached strict source verified before budgeting. |
| **R0058**: Al-Shaebi Z et al. (2026). [Impact of dataset partitioning on the reliability of SERS-machine learning models for antimicrobial resistance classification.](https://doi.org/10.1016/j.aca.2026.346185) | Methods; Learning from signals and fingerprints; Evaluating accuracy, uncertainty and generalization | Bacterial resistance classes from SERS spectra; clinical isolates. Retains contrary evidence that spectrum-level splits inflate performance relative to isolate/subject-level evaluation. Not anticancer-drug evidence. | Matched abstract only: PMID 42838683 and DOI 10.1016/j.aca.2026.346185. Publisher HTTP 403; institutional page is metadata without a downloadable article. |
| **R0039**: Kota Shiba et al. (2018). [Functional Nanoparticles-Coated Nanomechanical Sensor Arrays for Machine Learning-Based Quantitative Odor Analysis](https://doi.org/10.1021/acssensors.8b00450) | Methods; Designing sensors and probes; Learning from signals and fingerprints; Evaluating accuracy, uncertainty and generalization | Water/ethanol/methanol in humidified gas; nanoparticle-coated nanomechanical arrays and GPR concentration prediction. Abstract reports model feedback followed by two new coatings and improved accuracy: design plus interpretation, not oncology exposure. | Matched abstract only: PMID 30110149 and DOI 10.1021/acssensors.8b00450. Publisher HTML/PDF HTTP 403. OpenAlex flags OA, but no verified full text was obtained; this is an access failure, not evidence of paywall. |

## Identity diagnosis and quarantine

R0115 first acquired `pmcid=9421940` in the saved PubMed query result `data/search_results/5d24cb9eb12b5433efb44ca144f737165b3a88386d035c85c84b9931dc1b9dc2.json`, before deduplication. The parser used `.//ArticleId`, which reaches cited-reference identifiers. Its first descendant PMCID was from the cited Makker et al. *Endometrial Cancer* article (PMID 34887451; DOI 10.1038/s41572-021-00324-8). R0115 has no PMCID in its own `PubmedData/ArticleIdList`. The raw XML reproduces the defect; `R0115_identity_quarantine.json` records the exact reference subtree, own IDs and response hash. The canonical saved record now has `pmcid=null`; the original record/query cache is preserved.

All six were compared against their own PubMed title, DOI and PMID before any full-text budget was calculated. The other five do not have the reference-ID leak. R0078 uses the published PMID 42409644 / PMC13397890 / DOI 10.1021/acs.nanolett.6c01777; OpenAlex also links a preprint version, which was not substituted or counted as another publication. All six DOI/PMID pairs are distinct. All matched abstracts agree with the originally screened abstracts after formatting normalization.

The parser now reads only the article-owned identifier list. Lookup results must match the requested PMID/DOI. Full-text retrieval and caches require matching title and identifiers before screening, extraction or full-text budgeting. A bare PMCID or a well-formed PMCID pointing at another publication is insufficient. Unverified cache data is quarantined. Title normalization ignores case, punctuation and typography, not substantive words.

## Actual retrieval and source readiness

Access for the six: **3 identity-verified full texts and 3 matched abstracts**. R0090 and R0116 passed the strict cached-source check. R0078 passed XML identity and body checks, but its table `tbl1` is a graphic rather than a machine-readable table. The existing strict gate still refuses it. Its raw XML is preserved with SHA-256 `27be543d0c151e3666a67f25dda764d8ac136229cdebea8d69df1abbccbb0811`; it is conservatively budgeted as full text. No table values were transcribed, no images or supplements inspected, and no A05/A06 scientific extraction/validation was run. **Full-text extraction remains untested.** Both corpus options retain this readiness blocker.

Free routes actually attempted: current PubMed and Europe PMC metadata for each record; OpenAlex locations; Europe PMC published full text for R0078; revalidation of cached PMC XML for R0090/R0116; publisher pages for R0115/R0039/R0058; the indicated publisher PDF for R0039; the institutional metadata page for R0058; targeted searches for free author/repository copies. No subscription was used, paywall bypass attempted, author contacted, or API key loaded. R0039 OA labels conflict with successful accessibility here: HTTP 403 is reported as route failure. Unpaywall was not attempted; public OpenAlex location records were checked.

The attempted PMC9421940 XML endpoint returned HTTP 500. Its different-publication identity is nevertheless established by its own PMC page and the exact R0115 reference entry. That XML failure is not treated as evidence for R0115 or as a scientific exclusion. Detailed request URLs, status codes, timestamps and hashes are in `initial_identity_requests.json` and `free_routes.json`; raw responses stay in the run.

## Coverage and writing schedule

Both options cover T1-T5 and T8. **T6 (nanomedicine-associated measurements) and T7 (exposure trajectories) are uncovered.** The Exposure trajectories and limitations subheading has measurement/matrix-limit evidence from R0090, not serial or continuous drug-exposure evidence. Buffer and spiked-serum/plasma measurements do not establish post-dose performance. These are limits of the proposed corpus, not field-wide gaps. R0058 preserves a selected contrary methodological result; R0090 retains adverse matrix/interference observations. No new screening verdict or evidence role was invented.

The production A09 loop dispatches each ID in the approved plan `writing_order`. The scope-constrained outline contains **six manuscript subheadings plus two chapter-opening sections**; eight discovery themes are a separate structure. An offline regression exercises the actual writer loop and dispatches those eight IDs. A08 has not yet run, so there is no approved live writing schedule. **The forecast retains eight section units**, with up to two retrieval rounds each and separate front matter: 25 A09 requests at the current no-redraft limit. No reduction to six calls was assumed.

Each chapter remains approximately 800 words excluding headings/references (1,600 main-text words total), including its opening and subsections. The forecast now propagates this target into writing, critique and editing prose sizing as well as A10; the old generic 5,000-word sizing is corrected. Front-matter/legend allowances, output caps, all models, 30% forecast uncertainty margin, 25% stage recovery allowance and configured retrieval/retry loops are unchanged.

## Revised costs - all five holds included

No new paid dispatch occurred. Recorded spend remains **$2.0849717**; five unresolved holds remain **$0.124671**. Current combined exposure is **$2.2096427**. Smoke exposure remains **$0.3785106** under the separate $1 allowance. The hard combined cap is $50 and review pauses remain $25/$48.

| Account | Requested six | Five-paper fallback, omit R0116 |
|---|---:|---:|
| Full-text / abstract pricing levels | 3 / 3 | 2 / 3 |
| Projected remaining, uncertainty margins included | $38.65 | $34.96 |
| Central cumulative exposure: spent + holds + remaining | **$40.8596427** | **$37.1696427** |
| A02-A04 stage limit (includes prior stage spending) | $2.29 | $2.29 |
| A05-A06 stage limit | $6.24 | $5.20 |
| A07 stage limit | $11.61 | $10.41 |
| A08-A09 stage limit | $8.98 | $8.48 |
| A10 stage limit | $17.06 | $15.26 |
| A11-A12 stage limit | $4.63 | $4.57 |
| All stage limits, existing 25% recovery allowance retained | $50.81 | $46.21 |
| Already-paid nonstage smoke costs | $0.0991156 | $0.0991156 |
| All five retained holds | $0.124671 | $0.124671 |
| **Complete stage-limit envelope** | **$51.0337866 - exceeds $50** | **$46.4337866 - within $50** |

Already-paid A05/A06 engineering checks are included in their stage group; nonstage smoke costs are added separately, preventing double counting. The six-paper envelope exceeds the cap by $1.0337866. The fallback has $3.5662134 of cap headroom after its envelope. These are planning envelopes, not a promise of completion under every possible response/recovery path; each actual call still requires its own bounded reservation. R0078 table remediation has no priced paid call here. No allowance was increased, hold settled, or charge assumed free.

The CP2 account display now reports over-cap envelopes without clamping them to $50. Central projections and available room for stage limits explicitly count retained reservations. `revised_budget.json` preserves every forecast line, current model/pricing configuration, stage caps and the arithmetic for both options.

## Verification and review status

Fix commit: `33f0e37c2646f69b676a7cc87bd0a473af3df556`. Full offline suite: **1,173 passed** (213.23 seconds). Regressions cover article-owned PubMed IDs versus cited references, a valid PMCID for the wrong publication, title mismatch, wrong-source cache quarantine before budgeting/handoff, image-table refusal after identity verification, actual eight-unit writer dispatch, 1,600-word sizing and retained-hold over-cap accounting. Synthetic fixtures were updated to include matching article titles and real lookup identity fields; scientific guards were not weakened.

All 32 strict receipts and the archived engineering extraction, independent validation and original failed functional verdict remain unchanged (55 migration-pinned files checked). No scientific approval or successful receipt was reused incompatibly; provider schemas and model assignments did not change. The sealed v32 source and manifest remain unchanged. This offline revision uses the tested fix commit; **a new sealed runtime containing the fix is required before any paid continuation**.

PR #5 is already merged; the same working branch will carry a linked follow-up PR. CP2 remains pending. The requested six is the current draft; the five-paper option is priced only and has not replaced it. No corpus is frozen, no paid source processing has started, and no further scientific checkpoint is approved.
