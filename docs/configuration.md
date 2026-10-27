# Configuration

Everything you change between runs lives in `config/` and `.env`. No code edits are needed.

## 1. API keys — `.env`

`.env` does not exist until you create it. In the repository folder:

```powershell
copy .env.example .env      # Windows PowerShell
```

Open `.env` in VS Code (it appears in the Explorer; files starting with a dot are not hidden there)
and paste each key directly after `=`, with no quotes or spaces. Required keys depend on which
providers `config/pipeline.yaml` uses — `litreview check` lists exactly which are missing.

| Key | Where to get it | Needed for |
|---|---|---|
| `ANTHROPIC_API_KEY` | platform.claude.com → Settings → API keys | Claude agents |
| `OPENAI_API_KEY` | platform.openai.com/api-keys | A02, A03, A06, A08, A10 |
| `MOONSHOT_API_KEY` | platform.kimi.ai → API keys (international) | A11 |
| `LANGSMITH_*` | smith.langchain.com → Settings → API keys | optional tracing |
| `NCBI_API_KEY`, `S2_API_KEY` | NCBI account settings; Semantic Scholar | higher rate limits |
| `SMTP_*`, `NOTIFY_EMAIL_TO` | Gmail App Password (myaccount.google.com/apppasswords) | email notifications |

Never paste keys into chat, issues, commits or prompts.

## 2. Models — `config/pipeline.yaml`

| Agent | Provider | Model | $ in / out per M tokens | Why |
|---|---|---|---|---|
| A02-SP Scope | OpenAI | gpt-6.1-sol | 2 / 10 | Judgement; runs once |
| A03-LM Search | OpenAI | gpt-6.1-sol | 2 / 10 | Query design |
| A04-CQ Screening | Anthropic | claude-haiku-5-5 | 0.10 / 0.50 | High volume, cheap; you review every record at CP2 |
| A05-KE Extraction | Anthropic | claude-sonnet-5-5 | 2 / 10 | Long papers; measured: 4 span failures in 447, no fabrication |
| A06-SV Validation | OpenAI | gpt-6.1-sol | 2 / 10 | Audits Claude's extraction |
| A07-SYN Synthesis | Anthropic | claude-opus-5 | 5 / 25 | Hardest reasoning step; Opus 5.5 refused this topic family |
| A08-OL Outline | OpenAI | gpt-6.1-sol | 2 / 10 | Structured planning |
| A09-WRI Writing | Anthropic | claude-opus-5 | 5 / 25 | Prose quality |
| A10-RV Verification | OpenAI | gpt-6.1-sol | 2 / 10 | Audits Claude's prose |
| A11-RC Critique | Kimi | kimi-k3.1-pro | 2 / 10 | Third vendor: independent reader |
| A12-EDI Editing | Anthropic | claude-sonnet-5-5 | 2 / 10 | Meaning-preserving edits |

**Refusal routing.** Safety classifiers on some models decline biomedical topics by mistake (Opus 5.5
declined a drug-repurposing oncology review twice, category `bio`). Refusals are never retried. Every
agent call is recorded in `records/model_record.jsonl` with model, agent, outcome and the run's topic
family (`litreview new --family NAME`). The record is tracked in git, so qualification evidence
accumulates across machines and survives a fresh clone: commit it after a run. It merges with git's
`union` driver (`.gitattributes`), so two machines' appends never conflict. A model that has refused
in a family is not used again for it: the agent moves to its next alternate (`routing.alternates` in
`pipeline.yaml`; every agent has one), or the stage stops before any call. `litreview check`
summarizes the record per family and pings every alternate.

If every candidate for an agent has refused a family, the run stops with "No qualified model for
AGENT", naming each model tried, the agent it refused at and its category, so you can judge whether
to reword the topic (a new family) or treat the family as blocked. This is deliberate: no model is
added just to fill the slot. The dead end is recorded (`NO_QUALIFIED_MODEL`, shown by `litreview
check`). Every run checks routing when it starts and stops before spending anything if an agent it
still needs has no qualified model. Refusals disqualify a model for the whole family, but each records
the agent it happened at, so the rule can be narrowed to per-agent if the evidence supports it.

An alternate that would cost more than `routing.max_cost_multiple` (default 1.5x) times the primary
stops the run before any call and asks. The multiple is priced from the run's own calls on the primary,
or from the largest rate ratio if there are none. `litreview approve-alternate RUN AGENT` accepts it for
that run, and is logged as your decision. A05 and A12 on Opus 5 always ask (2.5x on run 20261025-100039).
If an agent's output came from two models, `provenance_summary.json` lists it under `mixed_model_agents`;
for the A07 job it also records which model produced each turn (`synthesis_models_by_turn`).

Alternatives already priced in `prices.yaml`: `gpt-6-luna` ($0.10 / $0.50), `kimi-k2.6` ($0.95 / $4), `claude-opus-5-5` ($4 / $20; refuses some biomedical topics).

To change a model: edit the alias under `models:` or the `model:` of one agent. Keep auditors on a
different vendor from what they audit — `pytest` fails if they share one.

## 3. Prices — `config/prices.yaml`

Standard rates checked 2026-10-16 from each provider's pricing page (links in the file). The budget
monitor uses them to stop a run at `run.spend_cap_usd`. Re-check before long runs.

Cache rates (`cached_input`, `cache_write`) price prompt-cache reads and writes, which every
provider reports per call; `litreview costs` shows cached tokens per agent. Where a rate is not set,
those tokens are billed at the full input price, so spend is never undercounted; `litreview check`
lists the gaps.

Batch rates live in a separate entry, `<model>-batch`, with the same fields. A batched call on a model
without one is billed at standard rates. Long-context tiers (`long_context_threshold`, `long_*`) apply
within whichever table is used: batching halves the price above the threshold but does not remove the
jump. GPT-6.1 doubles input and raises output 1.5x above 272k prompt tokens.

**Batching** (`batch:` in `pipeline.yaml`). A05 and A06 per-paper calls go through the vendors' batch
APIs at 50% off. A06 is batched only while `loops.max_reextractions` is 0. Each batch works as follows:

1. One real paper runs interactively first. If the model refuses, nothing is submitted, and the
   stage stops at the cost of one paper.
2. The batch is not submitted if its projected cost exceeds what is left under `spend_cap_usd`. A
   submitted batch cannot be stopped, so the run refuses rather than asks.
3. An intent record is written before the batch is created. If the run stops at any point,
   `litreview run` reattaches to the batch rather than resubmitting it, including when the batch ID was
   never saved.
4. Results are ingested one at a time, and each item's cost is logged once.
5. Items that came back as invalid JSON or truncated are retried interactively, with JSON repair.
   Expired items are resubmitted. Refused items go to the alternate through the cost check.

Expect under an hour; the vendors allow 24 hours. Kimi has no batch endpoint, so A06 on its Kimi
alternate runs interactively, at about twice the batched GPT-6.1 cost, and the cost check asks first.

## 4. Databases — `config/sources.yaml`

Enabled: PubMed, Europe PMC, PubTator3, OpenAlex, Semantic Scholar, ClinicalTrials.gov.
Identifier lookups (no keys needed): HGNC, MyGene.info, UniProt, ChEMBL, PubChem, Cellosaurus,
EBI OLS4 (MONDO, HP, CL, UBERON, GO, NCBITaxon).

Optional, off by default:
- **DrugBank** — licensed. To use it, set `drugbank: enabled: true` in `config/sources.yaml` and
  `DRUGBANK_API_KEY` in `.env`, then run `litreview check --apis`. It is a cross-check only: ChEMBL
  stays the source of `drug_status_verified`; when DrugBank's approval groups disagree, or list the
  drug as withdrawn, the entity gets a `drug_status_conflict` note for the reader.

Not wired, by design:
- **HMDB** — no public REST API; PubChem/ChEBI cover metabolites.
- **BioGRID** — interaction networks aren't needed to write a narrative review.
- **Neo4j** — the knowledge graph belonged to the drug-repurposing framework; this pipeline stores
  everything as JSON per run.

## 5. Tracing — LangSmith

Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in `.env`. Every model call then appears in the
`LANGSMITH_PROJECT` project as "<agent> · <model>", tagged with run ID and step, with token counts.
Traces contain prompts and paper text, so keep the project private.

## 6. Verify

```powershell
litreview check                 # config, prices, keys
litreview check --ping --apis   # + one tiny call per LLM provider (< $0.01) and each database
```
