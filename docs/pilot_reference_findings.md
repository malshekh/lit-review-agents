# Pilot reference findings (evaluation key, draft)

**Status: UNVERIFIED DRAFT ? NOT APPROVED as a human gold-standard reference key. Requires researcher review and approval before use.** Drafted on 2026-10-30 by Claude from the sources
listed below, retrieved through PubMed / PubMed Central. This record is a proposed pilot evaluation key, pending human approval: the run's A05
extractions, A06 dispositions, A07 contradiction handling and the manuscript are compared against it. It is not
evidence for the review, never enters the pipeline, and must be checked against each paper (including figures and
tables, which were not available as text) before it is used. Items marked **VERIFY** depend on content not seen.

Scope rule used: every result the paper reports about disulfiram (DSF), its copper complex, or combinations, with
its conditions (system, line, dose, schedule, comparator, endpoint) and whether it is the authors' own observation,
their interpretation, or a claim attributed to others. Negative and null results are listed as findings.

## 1. Liu et al. 2021, Int J Mol Sci, PMID 34638842, PMC8508702 (full text)
[DOI 10.3390/ijms221910496](https://doi.org/10.3390/ijms221910496)

**Systems.** Human GBM lines 1306MG and U87MG; radiation-resistant (RR: 1306MG 3.5GR6, six 3.5 Gy fractions;
U87MG 2GR4, four 2 Gy fractions) and radiation-TMZ-resistant derivatives (RTR: 1306MG R6T3, U87MG R4T3; three
250 µM TMZ treatments). In vivo: luciferase-labelled RR/RTR cells, orthotopic (striatum), male NOD/SCID mice.
**Doses.** DSF at a 20% growth-inhibition dose: **8 µM for 1306MG lines, 150 nM for U87MG lines** (text, §2.2 and
§4.3). Galunisertib 100 µM in vitro; NCT-501 300 nM (1306MG) / 100 nM (U87MG). In vivo DSF 50 mg/kg, galunisertib
75 mg/kg, from day 10 to day 55, twice weekly (schedule from §2.4). No copper supplementation is reported.
**VERIFY:** the pilot criteria record a 150 µM vs 150 nM inconsistency between a table and the text; the text seen
here says 150 nM throughout; the table/figure value must be checked in the PDF.

| # | Finding (observed unless stated) | Conditions | Direction |
|---|---|---|---|
| L1 | RR and RTR cells secrete more TGF-β than parental cells (e.g. 1306MG 25.7 vs 3.5GR6 1607.7 vs R6T3 1207.0 pg/mL) | ELISA, in vitro | increase |
| L2 | RR/RTR upregulate TβRI, TβRII, Slug, Snail, p-Smad2, N-cadherin, fibronectin | western blot | increase |
| L3 | RR and RTR activate ALDH; ALDH1 expression up in U87MG RR/RTR | ALDEFLUOR; western | increase |
| L4 | DSF (GI20 dose) did **not** affect 2D migration of parental 1306MG or U87MG | wound healing | **null** |
| L5 | DSF reduced 2D migration of 3.5GR6, R6T3 and 2GR4 | wound healing | decrease |
| L6 | DSF did **not** affect 2D migration of RTR U87MG R4T3 (33.9 vs 38.4%, p = 0.1496) | wound healing | **null** |
| L7 | DSF did not affect 3D migration of parental U87MG; reduced it in 2GR4 and R4T3 | Transwell | null / decrease |
| L8 | DSF + galunisertib reduced migration more than either alone (2GR4, R4T3) | Transwell | decrease |
| L9 | DSF + galunisertib combination index: slightly synergistic in 3.5GR6 (0.895) and R6T3 (0.897), synergistic in 2GR4 (0.672), **nearly additive in R4T3 (0.970)**, **moderately antagonistic in parental 1306MG (1.203) and U87MG (1.333)** | CompuSyn, viability | mixed: synergy and antagonism in one paper |
| L10 | DSF suppressed tumour-sphere growth of 3.5GR6 and R6T3; DSF + galunisertib more than either alone | 3D spheres, 21 days | decrease |
| L11 | **DSF alone and galunisertib alone did not affect in vivo growth** of RR U87MG 2GR4, RR 1306MG 3.5GR6 and RTR 1306MG R6T3; D + G suppressed growth in all three | orthotopic, IVIS | **null** (single agents) / decrease (combination) |
| L12 | Survival: U87MG 2GR4 vehicle median 54 days, DSF, G and D + G medians not reached; **1306MG 3.5GR6: no survival difference among groups** | Kaplan-Meier | **null** for 3.5GR6 |
| L13 | No body-weight effect of DSF, G or D + G | in vivo | null (tolerability) |
| L14 | Exogenous TGF-β1 did not alter ALDH activity in RR/RTR lines; TβR inhibition reduced ALDH activity | ALDEFLUOR | null / decrease |
| L15 | DSF reduced TGF-β secretion, TβRI phosphorylation and expression, Smad2, Slug, N-cadherin, fibronectin in RR/RTR | ELISA, western | decrease |

**Interpretations (authors', not observations).** ALDH activity "may be potentially involved" in regulating TGF-β
signalling; combining DSF and galunisertib "may be an effective therapeutic strategy" for recurrent GBM.
**Stated limitations.** DSF may act ALDH-independently; stemness assessed only by sphere formation; mechanism
needs isoform-specific genetic work.
**Attributed claims (secondhand, must stay attributed).** The discussion states that a phase II trial found that
combining TMZ and DSF "did not significantly improve the prognosis of recurrent GBM patients" (the trial is
PMID 30771200, below); also a single-patient report (Karamanakos) and galunisertib trial results.

## 2. Skrott et al. 2017, Nature, PMID 29211715, PMC5730499 (full text)
[DOI 10.1038/nature25016](https://doi.org/10.1038/nature25016)

**Scope warning.** Pan-cancer, not glioblastoma. No GBM-specific in vivo model; U87-MG appears only in a cell-line
panel (per-line results in Extended Data: **VERIFY**). Registry analyses are cancer overall and breast, prostate and
colon; brain tumours are not analysed separately.

| # | Finding | Conditions | Direction |
|---|---|---|---|
| S1 | Cancer-specific mortality lower in continuing vs previous DSF users, overall and for colon, prostate, breast, including metastatic disease (HRs and CIs in a figure/table: **VERIFY**) | Danish registries 2000-2013, ages 35-85, liver/kidney cancers excluded, propensity-score Cox model | association |
| S2 | Previous DSF users had higher cancer-specific mortality than never users | same | association |
| S3 | Authors: the registry findings do "not [allow] conclusions about causality" | own caveat | limitation |
| S4 | MDA-MB-231 xenografts: tumour volume at day 32 suppressed 57% (DSF) and 77% (DSF + copper gluconate), p = 0.0038 for DSF/Cu vs DSF | nude mice, 8 per group, oral DSF 50 mg/kg + copper gluconate 0.15 mg/kg daily, blinded | decrease |
| S5 | CuET (ditiocarb-copper) detected in plasma, liver, **brain** and tumour; tumour levels almost an order of magnitude above liver and brain | mice, 5 days DSF or DSF/Cu | measurement |
| S6 | CuET formed in humans taking DSF for alcoholism | patients | measurement |
| S7 | CuET more cytotoxic than DTC; LD50 ≤ 100 nM in 3/3 breast lines; similar in lung, colon, prostate lines | CFA, XTT | decrease (viability) |
| S8 | Most lines die by apoptosis-independent death; only the most sensitive (AMO-1, Capan1) show apoptosis markers | in vitro | mechanism |
| S9 | CuET does **not** inhibit 20S (CT-, C-, T-like) or 26S proteasome activity, nor p97 ATPase activity | biochemical | **null** |
| S10 | CuET inhibits p97-dependent degradation (Cdc25A, Nrf1 cleavage), immobilises poly-Ub proteins, induces UPR | cells | inhibition |
| S11 | CuET binds NPL4 (ITC, nanomolar; one site); no binding to the zinc-finger mutant; DARTS consistent | purified protein | binding |
| S12 | NPL4-GFP overexpression (not UFD1-GFP or p97-GFP) dampens CuET cytotoxicity | cells | rescue |
| S13 | NPL4 immobilised in tumours from DSF- or DSF/Cu-treated mice (candidate biomarker) | MDA-MB-231 xenograft sections | measurement |
| S14 | BTZ/CFZ-adapted and non-adapted myeloma lines equally sensitive to CuET | cells | equal sensitivity |

**Construct distinctions to preserve.** NPL4-GFP (overexpression rescue) vs GST-NPL4 WT/MUT (ITC, DARTS) vs MUT-NPL4-GFP
(spontaneous aggregates, toxic). **Interpretations.** CuET is "the" active metabolite; NPL4 aggregation "explains
major cell phenotypes"; additional targets "cannot be excluded" (authors' hedge).

## 3. Huang et al. 2019, J Neurooncol, PMID 30771200 (abstract only; no PMC full text)
[DOI 10.1007/s11060-019-03125-y](https://doi.org/10.1007/s11060-019-03125-y)

| # | Finding | Conditions | Direction |
|---|---|---|---|
| H1 | Objective response rate **0%** (primary endpoint) | open-label single-arm phase II, 7 centres, recurrent TMZ-resistant GBM, 23 enrolled, 21 evaluable | **negative** |
| H2 | Clinical benefit (response or stable disease ≥ 6 months) 14% | same | weak |
| H3 | Median PFS 1.7 months; median OS 7.1 months | same; no comparator arm | descriptive |
| H4 | One patient (4%) dose-limiting toxicity (grade 3 ALT elevation); "well tolerated" | same | safety |
| H5 | Median DSF/Cu exposure 1.6 cycles (range 0.1-12.0) | same | exposure |

**Conditions.** Monthly TMZ plus DSF 80 mg orally three times daily and copper 1.5 mg orally three times daily;
progression within 3 months of last TMZ; IDH-mutant and secondary GBM excluded. **Authors' conclusion.** "well
tolerated but has limited activity for unselected population". **Attributed premise.** "Preclinical studies have
suggested promising activity ... including re-sensitization to temozolomide".

## 4. Lun et al. 2016, Clin Cancer Res, PMID 27006494 (abstract only)
[DOI 10.1158/1078-0432.CCR-15-1798](https://doi.org/10.1158/1078-0432.CCR-15-1798)

| # | Finding | Conditions | Direction |
|---|---|---|---|
| N1 | Montelukast, clioquinol and DSF cytotoxic against a panel of patient-derived brain tumour-initiating cells (BTICs) | high-throughput screen, in vitro | decrease |
| N2 | DSF with copper: low-nanomolar efficacy in BTICs, including TMZ-resistant and quiescent stem-like cells | in vitro | decrease |
| N3 | Low-dose DSF-Cu augmented TMZ activity in vitro | in vitro | enhancement |
| N4 | DSF-Cu prolonged in vivo survival in patient-derived BTIC models from newly diagnosed and recurrent tumours | in vivo (doses not in abstract: **VERIFY**) | increase (survival) |
| N5 | DSF-Cu acts as a proteasome inhibitor and impairs DNA repair, enhancing alkylating agents and radiation | mechanism | inhibition |

**Authors' recommendation (interpretation).** DSF-Cu "should be considered as an adjuvant therapy ... in both newly
diagnosed and recurrent settings". Note that N5's proteasome-inhibition claim conflicts in mechanism with S9 (CuET
does not inhibit 20S/26S proteasome), a second, mechanistic disagreement across papers.

## 5. Li et al. 2015, Cancer Lett, PMID 26254539 (abstract only; only if a fifth paper fits)
[DOI 10.1016/j.canlet.2015.07.029](https://doi.org/10.1016/j.canlet.2015.07.029)

| # | Finding | Conditions | Direction |
|---|---|---|---|
| Y1 | DSF inhibits HUVEC proliferation, migration, invasion, adhesion and tube formation | in vitro | decrease |
| Y2 | DSF inhibits microvessel formation; copper improves it; **copper alone had no effect** | aortic ring, Matrigel plug | decrease / **null** (Cu alone) |
| Y3 | DSF/Cu suppresses VEGF secretion in U87 cells via EGFR/c-Src/VEGF | in vitro | decrease |
| Y4 | DSF/Cu increased anti-tumour effect in subcutaneous and intracerebral U87 xenografts, lowering microvessel density and VEGF | in vivo | decrease |

## The required contradiction: confirmed

**Lun et al. 2016 (N3, N4) against Huang et al. 2019 (H1-H3).** A preclinical result against a clinical trial,
on the same question: whether DSF/copper restores or enhances temozolomide activity in glioblastoma, explicitly
including the recurrent setting. Lun et al. report augmented TMZ activity in vitro and prolonged survival in
patient-derived models from recurrent tumours, and recommend adjuvant use in recurrent GBM; Huang et al. report a
0% response rate and limited activity of TMZ plus DSF/Cu in recurrent TMZ-resistant GBM. The trial's own premise
cites such preclinical work, and Liu et al. 2021 restate the trial's negative result (attributed).

**It must not be presented as like-for-like (comparability).** Differences that may explain the disagreement:
system (patient-derived BTIC xenografts vs patients); exposure (nanomolar DSF-Cu in vitro vs DSF 80 mg three times
daily orally, brain CuET exposure unknown; S5 shows lower CuET in mouse brain than in tumour); population (trial:
unselected IDH-wild-type, progression within 3 months of TMZ); endpoint (survival in models vs ORR, PFS, OS);
adherence (median 1.6 cycles). A correct pilot output states the contradiction with these differences and does not
resolve it.

**Secondary contrasts the pilot should also handle.** L11 (DSF alone, no copper, did not affect orthotopic growth)
against N4 and Y4 (DSF-Cu effective in vivo): different agent (with vs without copper), models and schedules, so
an apparent rather than direct contradiction. N5 against S9: proteasome inhibition asserted vs not found.

## Selection under the cap

The pair above uses PMIDs 27006494 and 30771200, both abstracts. If the projection forces a smaller selection, the
contradiction survives in any selection that keeps both of them (for example 1 full text + 2 abstracts). The
selection "2 full texts + 1 abstract (trial)" keeps only an attributed restatement of the trial in Liu et al. plus
the trial itself, but loses Lun et al.; the contradiction would then rest on L11/L12 (preclinical DSF alone, null)
against nothing positive, so it **does not** test the required contradiction.

Sources retrieved from PubMed and PubMed Central on 2026-10-30.
