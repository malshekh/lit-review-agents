# Language Policy — Narrative Review Pipeline

Version: 0.1 (draft) · Supplied to A9-WRI, A10-RV, A11-RC and A12-EDI. All four must use the same version; if the writer, verifier and editor apply different rules, they disagree about what is permitted and loop.
Source lineage: consolidates the LanguagePolicy role described in A14-WRI v0.1 §5.3–5.4, and the writing rules of A14-WRI §6, §8–§11 and A15-EDI §9, generalized from condensate biology to any biomedical or life-science review.

## 1. The failure this policy is written against

Unconstrained, a language model writing science drifts into prose that is fluent, abstract, gently hedged and empty:

> "These findings suggest a potential role for this pathway in modulating disease-relevant processes, highlighting the importance of further investigation into this emerging area."

It names no entity, states no finding, hedges by reflex, and overclaims nothing, so no verifier can fault it. That is the worst outcome available: prose that passes every check and communicates nothing.

Signatures to eliminate:
- **Abstraction where an entity belongs** — "signalling dynamics" instead of "phosphorylation of STAT3 at Y705".
- **Nominalization where a verb belongs** — "modulation of", "involvement in", "performed an investigation of".
- **Reflexive hedging** — "potential", "may possibly suggest", stacked regardless of the evidence.
- **Empty significance** — "highlighting the importance of", "an emerging area", "plays a key role", "promising".
- **Filler openings** — "It is worth noting that", "Interestingly,", "In recent years,".
- **The generic close** — "further research is needed" without saying what research would answer what question.

## 2. Claim-strength lexicon

Verbs carry evidential weight. Choose by what the proposition establishes, never for variety.

| Evidence (from the proposition's ceiling and qualifiers) | Appropriate verbs | Never |
|---|---|---|
| Association, correlation (observational, single time point) | was associated with, correlated with, was more frequent in | caused, drove, led to, regulated |
| Prediction (in silico) | was predicted to, docking indicated a possible | bound, inhibited, targeted (as demonstrated) |
| Measured change after intervention, in one system | reduced, increased, did not alter (in [system]) | reverses disease, is therapeutic |
| Requirement shown by loss of function | was required for (in [system]) | is the cause of |
| Replicated across independent systems | consistently reduced, in [n] independent studies | proves, establishes definitively |
| Authors' interpretation | the authors proposed, interpreted this as | showed, demonstrated |
| Adopted author interpretation (`AUTHOR_INTERPRETATION`) | we propose, we suggest, one interpretation is | it is clear that, this establishes |

Hedge exactly once, at the strength the evidence warrants. A strong, replicated finding is stated plainly. A single small study is described as a single small study — not hedged into vagueness.

## 3. Attribution matches authority

- "Smith et al. reported" / "one study found" — a single source.
- "Three independent studies found" — only with an independence count from A6-SV.
- "The evidence reviewed here indicates" — a theme-level record.
- "We propose" — only an adopted `AUTHOR_INTERPRETATION`.
- Never "it is well established that" unless the proposition says so with its sources.

## 4. Context and qualifiers

Species, system, construct, dose and population travel with the claim, in the same sentence or established in the paragraph so a reader cannot mistake the scope. "In mouse hepatocytes", "at 10 µM, above reported plasma concentrations", "in a single cohort of 120 patients".

Tense follows status: past tense for specific reported experiments; present tense for definitions, figure content and established relationships; conditional language for hypotheses.

## 5. Terminology and nomenclature

- **One term per concept, throughout.** Related terms are not stylistic synonyms; substituting one for variety changes the science.
- **Gene and protein names.** Use the approved symbol supplied by the plan (HGNC for human, MGI for mouse, others as normalized). Gene symbols italic, protein names roman, following species convention. Never interchange the gene and protein name. Alternative names given once at first mention: "X (also known as Y)", never "X/Y".
- **Chemicals.** Systematic (preferably IUPAC) or approved non-proprietary names as supplied; brand names only where the plan requires them.
- **Abbreviations.** Minimize. Define at first use in the text and separately in each legend and in the abstract. Never introduce a one-off abbreviation.
- **Units.** SI, with a space between number and unit (10 µM, 5 mg kg⁻¹), thousands separated by commas.

## 6. Transitions

| Kind | Examples | Rule |
|---|---|---|
| Organizational — asserts nothing | "Turning to the in vivo evidence…", "In contrast to the cell-free data, the cellular experiments…" (methods), "Second," | Use freely |
| Asserting — claims a scientific relationship | therefore, consequently, thereby, which suggests, consistent with this mechanism, collectively demonstrates, this explains | Only where a proposition states that relationship |

**Test:** remove the transition. If the passage now asserts less, the transition was asserting something and needs a proposition.

A methodological contrast ("one study used purified protein, whereas another used patient cells") is organizational. A biological claim ("the two studies reveal complementary phases of one mechanism") requires authority.

## 7. Readability for a non-specialist scientific reader

The journal's readers include researchers outside the field, educators and policymakers.
- Explain necessary background briefly, but only from planned propositions; never supply an explanation from general knowledge.
- Prefer the plain word where it loses nothing; keep technical terms that carry distinctions.
- One controlling idea per paragraph; a topic sentence that says what scientific issue the paragraph addresses.
- Every "this", "it", "these" has one clear referent.

## 8. Journal mechanics

- No footnotes.
- Citations by record ID only (`[@R123]`); numbering and Nature style are applied by code.
- Display items cited in order of first appearance (`{{F1}}`, `{{T1}}`).
- Abstract: unstructured, no references, no undefined abbreviations.
