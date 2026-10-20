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
| `OPENAI_API_KEY` | platform.openai.com/api-keys | A04, A06, A10 |
| `MOONSHOT_API_KEY` | platform.kimi.ai → API keys (international) | A11 |
| `LANGSMITH_*` | smith.langchain.com → Settings → API keys | optional tracing |
| `NCBI_API_KEY`, `S2_API_KEY` | NCBI account settings; Semantic Scholar | higher rate limits |
| `SMTP_*`, `NOTIFY_EMAIL_TO` | Gmail App Password (myaccount.google.com/apppasswords) | email notifications |

Never paste keys into chat, issues, commits or prompts.

## 2. Models — `config/pipeline.yaml`

| Agent | Provider | Model | $ in / out per M tokens | Why |
|---|---|---|---|---|
| A02-SP Scope | Anthropic | claude-opus-5-5 | 4 / 20 | Judgement; runs once |
| A03-LM Search | Anthropic | claude-sonnet-5-5 | 2 / 10 | Query design |
| A04-CQ Screening | OpenAI | gpt-5-mini | 0.25 / 2 | High volume, cheap; you review every record at CP2 |
| A05-KE Extraction | Anthropic | claude-sonnet-5-5 | 2 / 10 | Long papers, careful reading |
| A06-SV Validation | OpenAI | gpt-6.1-sol | 2 / 10 | Audits Claude's extraction |
| A07-SYN Synthesis | Anthropic | claude-opus-5-5 | 4 / 20 | Hardest reasoning step |
| A08-OL Outline | Anthropic | claude-sonnet-5-5 | 2 / 10 | Structured planning |
| A09-WRI Writing | Anthropic | claude-opus-5-5 | 4 / 20 | Prose quality |
| A10-RV Verification | OpenAI | gpt-6.1-sol | 2 / 10 | Audits Claude's prose |
| A11-RC Critique | Kimi | kimi-k3 | 3 / 15 | Third vendor: independent reader |
| A12-EDI Editing | Anthropic | claude-sonnet-5-5 | 2 / 10 | Meaning-preserving edits |

Alternatives already priced in `prices.yaml`: `gpt-6-luna` ($0.10 / $0.50, cheaper and newer
than gpt-5-mini — switch A04 to it before the gpt-5-mini snapshot shuts down on Dec 11, 2026),
`kimi-k2.6` ($0.95 / $4), `claude-haiku-5-5` ($0.10 / $0.50).

To change a model: edit the alias under `models:` or the `model:` of one agent. Keep auditors on a
different vendor from what they audit — `pytest` fails if they share one.

## 3. Prices — `config/prices.yaml`

Standard rates checked 2026-10-16 from each provider's pricing page (links in the file). The budget
monitor uses them to stop a run at `run.spend_cap_usd`. Re-check before long runs.

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
