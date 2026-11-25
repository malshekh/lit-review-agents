# Checkpoint 1 — Scope & perspective

**Topic (verbatim):** Write the first two chapters of a narrative review on AI-enabled nanobiosensing for cancer therapy.

Central question: How does AI contribute to sensor design and interpretation, and how reliably can these systems identify anticancer drugs and characterize exposure across biological matrices and time?

Investigate this question without assuming that AI improves every sensor or that laboratory performance establishes clinical usefulness.

The structure, section questions, word targets and instructions are in the outline supplied with this run (input/outline.json).


**Normalized topic:** The first two chapters of a narrative review examining AI contributions to nanosensor and probe design, molecular recognition and signal interpretation, followed by the reliability of anticancer-drug identification, concentration estimation, nanomedicine measurement and temporal exposure assessment across biological matrices, without presuming AI superiority or clinical usefulness.

**Specification state:** READY_WITH_ASSUMPTIONS

## Perspective options

### P1: The researcher-defined review examines what AI contributes to nanosensor design and interpretation and which evaluation conditions justify drug-identification and exposure claims.
- Organizing principle: Preserve S1.1–S1.4 on design, learned recognition, signal-to-task matching and evaluation, followed by S2.1–S2.4 on drug measurement, nanomedicine components, temporal exposure and interpretive limits.
- Why timely: The supplied outline identifies an unresolved assessment need: distinguishing computational contributions and laboratory measurement results from evidence for reliable exposure characterization; no recent field-wide development has been verified.
- Contribution: The intended contribution is a connected assessment linking physical sensing processes, computational outputs, evaluation units and exposure interpretation. Whether existing reviews already provide this synthesis remains to be checked.
- Competing positions: Studies with matched simpler comparators may find no incremental benefit from AI, or may find that preprocessing or sensor chemistry explains apparent gains.; Independent evaluations may establish robust transfer across specimens, matrices, batches or time, challenging an overly restrictive assessment of generalizability.; Independent evaluations may instead show performance loss or leakage-sensitive results, challenging claims of reliable recognition or concentration estimation.; Validated reference comparisons and longitudinal measurements may support exposure claims beyond isolated laboratory demonstrations; their absence must not be assumed.; Some relevant sensing tasks may be adequately addressed by conventional calibration, whereas others may require learned interpretation of overlapping or multidimensional responses.
- Risks: Direct anticancer-drug exposure studies combining a functional nanosensing component and a substantive AI contribution may be sparse.; Broad methodological evidence from Chapter 1 could be incorrectly presented as direct evidence for anticancer-drug exposure in Chapter 2.; Terminology may obscure whether a system measures a drug, a carrier-associated label, a surrogate or a model-derived quantity.; Overlapping subsection topics require explicit assignment rules to prevent duplicated study summaries.; No subsection word targets are present in the supplied outline object; chapter allocations cannot be checked against the journal's full-review word limit.
- Title candidates: AI-enabled nanobiosensing requires task-specific evaluation to substantiate anticancer-drug exposure claims.

## Selection criteria (frozen once approved)
```json
{
  "inclusion": [
    {
      "criterion": "A record must directly address at least one supplied subsection question; assign one or more T1\u2013T8 themes and state the specific connection.",
      "reason": "Relevance is determined by the fixed outline rather than agreement with an anticipated conclusion."
    },
    {
      "criterion": "For core empirical coverage, require a functional nanoscale sensing component and an identifiable computational contribution to component design, recognition, signal processing, prediction or evaluation.",
      "reason": "Prevents incidental use of AI or nanomaterial terminology from defining eligibility."
    },
    {
      "criterion": "For Chapter 1, include non-drug analytes or non-cancer systems only when they directly inform an outlined design, recognition, signal-task or evaluation question; label their application scope explicitly.",
      "reason": "Allows relevant methodological evidence without treating it as validation for anticancer-drug sensing."
    },
    {
      "criterion": "For Chapter 2, require measurement of an anticancer drug, a relevant metabolite, a nanomedicine component or a release-related process, or direct methodological evidence needed to interpret those measurements.",
      "reason": "Keeps exposure coverage tied to the specified therapeutic context."
    },
    {
      "criterion": "Retain eligible evidence from buffer, synthetic fluids, spiked biological specimens and post-administration specimens, recording these settings separately.",
      "reason": "Enables assessment of evidence progression without equating simplified and clinical matrices."
    },
    {
      "criterion": "Include null results, poorer performance, failed transfer, conventional-method comparisons and methodological challenges when they address an outline question.",
      "reason": "Contrary evidence is necessary to evaluate incremental contribution and reliability."
    },
    {
      "criterion": "Include relevant work across in vitro, ex vivo, animal and human settings, while preserving organism, specimen, compartment and experimental context.",
      "reason": "The outline imposes no organism restriction, but conclusions must remain bounded by the studied system."
    },
    {
      "criterion": "Retain potentially relevant abstract-only records with their access limitations; use only information stated in the abstract and seek fuller access where needed.",
      "reason": "Access limitations are not scientific negative findings or automatic grounds for exclusion."
    },
    {
      "criterion": "Use reviews and methodological literature for definitions, context, evaluation principles and citation discovery; trace empirical performance claims to primary evidence when available.",
      "reason": "Separates contextual synthesis from direct support for study-specific results."
    }
  ],
  "exclusion": [
    {
      "criterion": "Exclude records with no identifiable connection to any S1.1\u2013S2.4 question.",
      "reason": "Maintains the researcher-defined scope."
    },
    {
      "criterion": "Exclude standalone delivery or formulation optimization without a sensing function.",
      "reason": "AI-assisted formulation design does not establish sensing or a sensing-feedback loop."
    },
    {
      "criterion": "Exclude response, toxicity and treatment-decision studies unless a separable sensing-method or exposure result answers an included subsection question.",
      "reason": "Reserves later-chapter content while retaining directly relevant measurement evidence."
    },
    {
      "criterion": "Exclude stand-alone computational drug or exposure predictions unconnected to an included sensing measurement or sensing-design task.",
      "reason": "The review concerns AI-enabled nanobiosensing rather than general predictive pharmacology."
    },
    {
      "criterion": "Exclude duplicate reports as separate evidence units; link preprints, conference reports and journal versions of the same work.",
      "reason": "Prevents double counting while preserving distinct results or relevant version differences."
    },
    {
      "criterion": "Exclude retracted findings as affirmative scientific support; retain retraction information if needed to explain a directly relevant controversy.",
      "reason": "Avoids treating invalidated findings as reliable evidence."
    },
    {
      "criterion": "After relevance screening, deprioritize redundant studies only with a documented significance-based reason independent of result direction.",
      "reason": "Supports selective narrative coverage without preferentially excluding null or contrary findings."
    }
  ],
  "time_window": "Provisional: no lower publication-date cutoff; search through the actual final search date, which must be recorded when searching occurs.",
  "languages": [
    "No language restriction at discovery; interpretation requires source text accessible to the research team or a reliable translation. Unassessable records remain pending rather than scientifically excluded."
  ],
  "source_types": [
    "Primary research articles",
    "Primary methodological studies",
    "Reviews and perspectives for context and citation discovery",
    "Preprints, explicitly flagged",
    "Published conference papers",
    "Published conference abstracts, with abstract-level claim limits"
  ],
  "preprint_policy": "Preprints may be included and must be flagged; they may not be the sole support for a major point. Link subsequent published versions and document material differences.",
  "significance_signals": [
    "A clearly documented methodological advance with experimental evaluation of a model-recommended sensing component or condition.",
    "A comparison that isolates the incremental contribution of AI against matched conventional calibration or simpler models.",
    "Independent evaluation across biological specimens, individuals, matrices, sensor batches, laboratories or time.",
    "Explicitly characterized drug identity, concentration measurand, matrix and independent analytical reference.",
    "Evidence distinguishing carrier-associated signals from intact carrier, payload or released drug.",
    "Longitudinal measurements or temporally separated validation that distinguish observations from model-derived exposure estimates.",
    "A strong null, negative, replication or contrary result that materially changes interpretation of reliability.",
    "A methodological analysis exposing evaluation-unit errors, data leakage or unsupported exposure inferences."
  ],
  "exclusion_reason_vocabulary": [
    "OUT_OF_SCOPE_TOPIC",
    "NO_RELEVANT_NANOSENSING_ROLE",
    "NO_RELEVANT_COMPUTATIONAL_ROLE",
    "DELIVERY_ONLY",
    "LATER_CHAPTER_ONLY",
    "PREDICTION_WITHOUT_SENSING_LINK",
    "DUPLICATE",
    "RETRACTED",
    "LOWER_SIGNIFICANCE_THAN_ALTERNATIVES"
  ]
}
```

## Theme framework (proposed by A02)

- **T1 AI-assisted design and optimization of sensors and probes** — How are computational models used to select or optimize the physical components of a nanosensing system? Discuss relevant examples of selecting sensing materials, surface chemistry or recognition elements. Discuss relevant examples of designing or optimizing probe sequences. Discuss relevant examples of selecting complementary components for sensor arrays. Discuss relevant examples of optimizing fabrication or measurement conditions. Explain what enters the model, what it predicts or recommends, and whether the recommendation was experimentally evaluated. Distinguish designing a sensing component from selecting useful features in measurements already collected. (includes: materials; surface chemistry; recognition elements; probe sequences; array components; fabrication and measurement conditions; excludes: feature selection on already collected measurements; drug-delivery design without a sensing function; Drug-delivery design, unless it directly involves a sensing function.)
- **T2 From individual recognition events to learned molecular fingerprints** — How can models interpret patterns across sensor responses to recognize analytes or characterize biological samples? Explain machine perception through the relationship between interactions at the sensing surface, the resulting spectral or multisensor response, the features used by the computational model, and the predicted analyte identity, concentration category or sample characteristic. Clarify how this differs from interpreting a single sensor response through a conventional calibration relationship. (includes: spectral fingerprints; multisensor arrays; pattern recognition; excludes: Implying that learned recognition eliminates the importance of sensor chemistry.; Implying that a predictive fingerprint necessarily establishes its biological mechanism.)
- **T3 Matching learning tasks to biosensor signals** — Which computational tasks suit different biosensor signals, and why? Organize the discussion around signal, then analytical task, then method, then output. Optical or Raman spectra: preprocessing, denoising, feature extraction, classification and concentration estimation. Multisensor-array fingerprints: analyte discrimination, pattern recognition and multianalyte analysis. Electrochemical responses: calibration, interference discrimination and concentration estimation. Repeated measurements: drift correction, tracking and temporal prediction. Explain model families only where they clarify an included study. Distinguish exploratory dimensionality reduction from predictive classification or regression. Compare with simpler analytical approaches where the evidence permits. (includes: optical and Raman spectra; multisensor arrays; electrochemical responses; repeated measurements; excludes: Assuming that greater model complexity means better performance.)
- **T4 Interpreting performance and generalization** — What does a reported performance result establish, and under which evaluation conditions? Distinguish analytical performance: measurement accuracy, precision, selectivity and useful concentration range. Distinguish predictive performance: classification or regression performance on appropriately separated evaluation data. Distinguish generalization: performance across new biological samples, individuals, matrices, sensor batches or time points. Identify the independent evaluation unit. Introduce these evaluation principles here; their consequences for drug-exposure measurement belong to Chapter 2. (includes: analytical performance; predictive performance; generalization; evaluation units; excludes: Describing multiple spectra from one specimen as multiple independent biological samples.)
- **T5 Identifying anticancer drugs and estimating their concentrations** — What drug-related information do AI-enabled nanosensing systems actually produce? Distinguish detecting drug presence, identifying a drug, classifying a concentration into categories, and estimating a numerical concentration. For the selected studies, connect the drug, sensing mechanism, biological matrix, computational task and evaluation result. Separate experiments in buffer, synthetic biofluids, spiked biological specimens and specimens collected after administration. Where reported, identify the reference analytical method. Where reported, distinguish parent drug from metabolites, and total from unbound concentration. (includes: anticancer drugs; biological matrices; reference methods; excludes: Describing concentration classification as continuous quantitative measurement.; Describing synthetic-fluid performance as established patient performance.)
- **T6 Measuring nanomedicines: carrier, payload and release** — When a nanomedicine is sensed, which component or process does the signal represent? A carrier-associated label does not by itself establish intact-carrier abundance, released drug concentration, or biologically available payload. Distinguish measurements of the nanocarrier or a carrier-associated signal, of the drug payload, of encapsulated and released drug, and of release-related changes or distribution. Explain the specific contribution of AI to interpreting these measurements. Evaluate whether sensing supplies feedback for assessing or refining a delivery system. (includes: nanocarrier signals; payload; release; distribution; excludes: treatment selection; dose adjustment; Inferring a demonstrated feedback loop merely because AI was used to design the formulation.; Detailed treatment selection and dose-adjustment strategies.)
- **T7 From individual measurements to exposure over time** — How can sensor measurements support temporal exposure assessment, and which parts are measured versus modeled? Distinguish single measurements, serial sampling, continuous or near-continuous sensing, pharmacokinetic estimation and prediction of future concentrations. When measurements are coupled to pharmacokinetic or machine-learning models, identify the observations supplied to the model, the quantities estimated, the assumptions required, and how temporal predictions were evaluated. Address sampling frequency, response lag, reversibility, drift and recalibration where relevant. (includes: serial and continuous sensing; pharmacokinetic models; temporal prediction; excludes: Treating repeated technical measurements as longitudinal monitoring.; Presenting a predicted concentration-time curve as continuously measured data.)
- **T8 Limits to interpreting measured concentrations as biological exposure** — What prevents the reported measurements from supporting broader exposure claims? Synthesize limitations demonstrated or left unresolved by the selected evidence: matrix interference and sample preparation; transfer across drugs, specimens, individuals and sensor batches; limited concentration ranges or temporal evaluation; differences between the sampled compartment and the tumour; missing independent reference measurements. Explain the consequence of each limitation. Distinguish not investigated, insufficiently reported, and tested with poor performance. Close with what the selected evidence supports and what remains necessary for reliable exposure assessment. (includes: matrix effects; transferability; compartment versus tumour; reference measurements; excludes: none stated)

Why this number: One theme per subsection of the researcher's outline (8 subsections).

To change the framework, put the edited version in `edited_theme_framework` (same shape: `primary_themes`, `count_justification`).

## Assumptions
- The supplied researcher_outline object is the operative outline. Its subsection questions and exclusions are fixed; no alternative perspective or primary-theme structure is proposed.
- For topic boundaries, nanobiosensing provisionally requires a nanoscale component with a functional sensing role, not merely a nanoscale delivery vehicle. A biological recognition element is not mandatory for chemical drug-sensing platforms relevant to the outline.
- For topic boundaries, no organism or matrix restriction is imposed. Chapter 1 may draw on directly relevant methods outside anticancer-drug sensing, but such evidence does not establish Chapter 2 exposure performance.
- For topic boundaries, discovery has no lower date cutoff or language restriction. The final search date and any practical translation limitations must be recorded during literature work.
- For audience readiness, the journal's non-specialist scientific readership is adopted because the researcher supplied no narrower audience.
- For competing-position readiness, the listed challenges are provisional screening targets rather than verified positions in the literature; their actual presence and evidential support require literature inspection.
- AI terminology is treated broadly enough for discovery to capture machine learning, learned chemometric models and model-guided optimization. Conventional calibration and exploratory dimensionality reduction remain explicit comparators and must not automatically be relabeled as AI-enabled prediction.
- Reference methods and conventional sensors may be retained as direct comparators or methodological context even when they do not themselves contain nanoscale or AI components.
- No chapter or subsection word allocations are inferred: the supplied outline object contains none, and the journal's 5,000-word limit applies to the full review.

## Questions for you
- The supplied outline object contains no word targets. What combined or chapter-level word allocation should the first two chapters use within the full review's 5,000-word main-text limit?

Fill in `CP1_decision.json`, then run `litreview approve <run_id> CP1`.

## Immutable run-level corpus authority
```json
{
  "broad_discovery": true,
  "citation_expansion": true,
  "mode": "OPEN_CORPUS",
  "papers": []
}
```
Confirm this policy explicitly; agents cannot change membership or expansion permissions.

## Recorded instruction clarifications (not checkpoint decisions)

The scope model was given the pre-A08 outline brief, which deliberately omits word
budgets. Its request above for chapter targets is therefore already answered by
the researcher's existing instruction and input/outline.json: Chapter 1 targets
approximately 800 words and Chapter 2 approximately 800 words, excluding headings
and references, with flexible subsection allocations. The full-review 5,000-word
journal limit does not replace this two-chapter pilot target. No further word-count
decision is needed. The original model proposal and raw reply are preserved;
this addendum supplies an existing constraint, not a scientific approval.

The final pilot corpus is limited to seven unique publications discovered and
screened independently. There are no seed publications or selected corpus yet.
The engineering test excerpt is outside the discovery corpus. Unsupported areas
must be reported as limitations of the selected evidence, without padding or
claiming a field-wide evidence gap. No source-access or comparator limitation is
automatically a scientific exclusion. Full-text extraction remains untested.

CP1_decision.json is unchanged and unfilled; no checkpoint is approved. Review
perspective P1, selection criteria, the eight outline-defined themes and provisional
date/language/preprint assumptions before providing the CP1 decision.
