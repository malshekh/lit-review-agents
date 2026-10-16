# Prompts

Every agent's system prompt is assembled from three files:

```
shared/core_rules.md          always included
shared/language_policy.md     included for A09, A10, A11, A12 (writing side)
agents/<agent>.md             the agent's own prompt
```

Each prompt header gives its version, role, position in the pipeline, and **source lineage**
(what was kept, removed or added relative to the drug-repurposing framework).

## Agents

| ID | Prompt | Role | Does | Human checkpoint after |
|---|---|---|---|---|
| A02-SP | [Scope & Perspective](agents/A02-SP_Scope_Perspective.md) | Stage | Turns the topic into a specification; proposes 2–3 perspectives and selection criteria | **CP1** |
| A03-LM | [Literature Mining](agents/A03-LM_Literature_Mining.md) | Stage | Designs database-specific queries (incl. mandatory contrary-evidence searches); repairs failing queries | |
| A04-CQ | [Corpus Qualification](agents/A04-CQ_Corpus_Qualification.md) | Stage | Screens eligibility; proposes themes and significance tiers (sorting aids only) | **CP2** |
| A05-KE | [Knowledge Extraction](agents/A05-KE_Knowledge_Extraction.md) | Stage | Extracts study design, systems, entities and findings with verbatim spans | |
| A06-SV | [Scientific Validation](agents/A06-SV_Scientific_Validation.md) | Auditor | Validates each finding; finds conflicts, counts independent studies, maps evidence reach | |
| A07-SYN | [Synthesis & Gaps](agents/A07-SYN_Synthesis.md) | Stage | Builds propositions, themes, gaps; proposes theses and interpretations | **CP3** |
| A08-OL | [Outline](agents/A08-OL_Outline.md) | Stage | Section plan, word/reference budgets, figures and tables, title, abstract plan | |
| A09-WRI | [Writing](agents/A09-WRI_Writing.md) | Stage | Writes the manuscript from the plan, tagging every sentence | |
| A10-RV | [Verification](agents/A10-RV_Verification.md) | Auditor | Checks every claim against its evidence; final release decision | |
| A11-RC | [Critique & Readability](agents/A11-RC_Critique.md) | Auditor | Reader-centred critique, incl. a non-specialist reader pass | |
| A12-EDI | [Editing](agents/A12-EDI_Editing.md) | Stage | Revision, line edit and proof, without changing meaning | |

A01 (Orchestrator) is not an LLM agent here: it is `src/litreview/orchestrator.py`.

## Editing a prompt

1. Edit the `.md` file and bump its `Version:` line.
2. If you change the output fields, update the matching `schemas/<agent>.schema.json`.
3. Run `pytest` — it checks every prompt and schema loads.
4. Commit with a message naming the agent and what changed, e.g. `A05-KE v0.2: add organoid fields`.
