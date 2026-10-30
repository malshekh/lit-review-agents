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

1. **Routing per paper.** Each item routes on its own, and an auditor never runs on the vendor that
   produced the work it audits: A06 routes each paper on the provider that actually produced that paper's
   extraction (the last call logged for it). Items are grouped by model into provider-specific batches,
   and the rule is checked again before anything is uploaded. If the extraction's vendor cannot be
   determined, the paper is not validated.
2. **Probe.** One real paper per model runs interactively first. If the model refuses, nothing is
   submitted, and the stage stops at the cost of one paper.
3. **Chunks and reservations.** Items go in chunks of `batch.chunk_size` (20), each its own batch with
   its own fingerprint and reservation. A chunk's worst-case cost (every item at the configured
   `max_tokens`, the same limit as an interactive call, and every Anthropic item paying a cache write) is
   reserved under a lock before submission and held until the chunk settles, when its actual cost replaces
   the reservation and frees room for the next. For A05 a chunk reserves about $7. At most
   `max_chunks_in_flight` (1) chunks are outstanding. A chunk that does not fit waits for an outstanding
   one to settle; if it does not fit with nothing outstanding, the stage stops: the run refuses rather than
   asks. Batching never lowers `max_tokens`: a batched call may produce exactly what an interactive one
   may. Interactive calls also count held reservations. `litreview costs` shows what is reserved.
   **Runtime gate** (`batch.gate_usd`, $150). Before any chunk is reserved, four amounts are added:
   - spent;
   - committed (held by unsettled batches);
   - projected (the rest of the run, without this chunk's items or any in flight);
   - this chunk's worst case.

   If the total exceeds the gate, the stage stops instead of waiting: scope is revised, scientific checks
   are not cut. Every check is recorded in provenance (`batch_gate`). A run with no measured rates, or no
   gate configured, submits no batch. The gate is separate from `run.spend_cap_usd`, which stays absolute.
4. **Fingerprint.** Before the batch is created, the run records an intent with a fingerprint: run ID,
   stage, a submission ID, the request IDs (each step plus the submission's nonce) and the SHA-256 of the
   frozen request manifest (`data/batches/manifests/`).
5. **Recovery by identity.** If the batch ID was never saved, time, item count and input file only
   nominate candidates. A candidate is adopted only when confirmed against the manifest: on OpenAI by
   the hash of its input file, on Anthropic by its request IDs once it has ended. A batch that cannot be
   confirmed leaves the submission UNRESOLVED and the run paused; a replacement is never submitted
   automatically. "Never created" is concluded only from a complete listing of a closed 15-minute
   creation window. Batch creation is never retried by the SDK, since a retry after a timeout can
   create a second batch.
6. **Ingestion.** Results are ingested one at a time, and each item's cost is logged once. The
   reservation shrinks as costs are logged and is released when the batch settles.
7. **Failures.** Items that came back as invalid JSON or truncated are retried interactively, with JSON
   repair. Expired items are resubmitted as a new submission. Refused items go to the alternate through
   the cost check.

The vendors allow 24 hours. Turnaround and throughput at full scale are unmeasured: the 2-item tests in
`records/batch_tests.jsonl` established compatibility only (6 minutes on Anthropic, 63 on OpenAI). Kimi has
no batch endpoint, so A06 on its Kimi alternate runs interactively, at about twice the batched GPT-6.1
cost, and the cost check asks first.

**Savings reporting.** `litreview costs` reports cache savings apart from the batch discount, so each can
be judged on its own: cache reads saved (cached tokens at input minus read rate), cache-write premiums
over the input price (5-minute and 1-hour separately), their net, and the batch discount (the same calls
at standard rates minus what they cost). The 1-hour configuration pays only if reads saved exceed the
1-hour write premium at scale.

**A10 input scope.** A10 receives in full only the validated findings the manuscript's claims are bound to
(through sentence tags and the plan's title, abstract, heading and display propositions), with their
contexts and source passages. Every other finding goes in a contradiction index: ID, assertion
(A06's plain-language limit) and disposition, about 53 tokens a line against 514 for a full record
(run 20261025-100039). A finding that contradicts a claim is not cited by it, so it must stay visible.
A10 lists index entries that seem to bear on a claim in `detail_requests`; one detail round sends those
records in full (at most 40), and its output replaces the first. `litreview costs`, the final
`provenance_summary.json` and an `a10_detail` notification after a run's first A10 pass report how often A10
asks, how many records, how often it hits the cap, and first-call against detail-call cost and size. Passes
that routinely ask for 40 mean one large call has become two medium ones, and the scoping may not pay.
Every request also says why, and the report breaks requests down by reason and by the check that
triggered them: `UNCITED_CONFLICT` (the contradiction index working as designed) or `MISSING_FROM_SCOPE`
(a record A10 needed for a bound claim, meaning the scoping rule draws the line in the wrong place; if
these are half or more of the requests, the verdict says so). It also counts requests for findings from
papers the manuscript cites, independently of A10's own label.

A10 and A11 also run off every vendor that actually produced the manuscript: the producer of every
A09-WRI and A12-EDI output in the run, checked before each call, not only in the configuration. If those
cannot be determined, neither runs.

**Evidence eligibility and roles** (`src/litreview/evidence.py`). What a validated finding may be used
for is decided by its A06 disposition alone; entity normalization never decides it. Each use of a finding is
a link with its own role, so one proposition can cite validated findings as `SUPPORTING` or `CONFLICTING`
and a `DOES_NOT_ESTABLISH` finding as `SUBJECT_OF_APPRAISAL` ("X reported Y; its evidence does not establish
it"). Allowed: a supported disposition (status `SUPPORTING`) as support or conflict; `NOT_ESTABLISHED` as an
appraisal subject only; `REJECTED`, `UNRESOLVED`, `HELD_FOR_CORRECTION` and `REVALIDATION_REQUIRED` in no
role. An appraisal link must carry its own statement, the record that made the claim, and A06's rationale
quoted verbatim; an appraised claim never counts as support (a `SOURCE_GROUNDED` proposition needs a
supporting or conflicting link; `CLAIM_APPRAISAL` propositions are about the claim). Code enforces this
wherever findings are consumed, each independently: the A07 job rejects any proposition or gap with a link
its finding may not serve; display tables leave such findings out; and before every A10 pass code lists
claims resting on unusable evidence and every sentence bound to an appraisal, and merges them into A10's
output whatever A10 concludes. A claim whose support is entirely unusable is BLOCKING, an appraised claim
promoted into an established one (`APPRAISED_CLAIM_PROMOTED`) is BLOCKING, and an appraisal binding A10 left
without a verdict makes a final pass `INCOMPLETE_VERIFICATION`.

**Identities are separate from validity** (`src/litreview/tools/normalization.py`). OLS4 is searched on labels
and synonyms only; only a unique exact label in the ontology's own terms resolves. An abbreviation resolves
only through the paper's own expansion ("disulfiram (DSF)"), which takes precedence over any ontology hit on
the abbreviation; without one it is AMBIGUOUS or UNRESOLVED. When the source's expansion and the ontology
contradict, the entity is `CONFLICT`. Cellosaurus candidates are lines whose identifier or synonym matches
the mention exactly (no row cutoff); a derivative and its parent never stand in for each other, and an
ambiguous result lists each candidate with its own problematic-line note and a warning that
misidentification is possible. A06 judges alignment against the source mention, and reports a
code-attached identifier that contradicts it in `normalization_conflicts` instead of blocking. A
conflicting identifier is stripped from the entity everywhere (only `usable_identity()` of a RESOLVED entity
is ever passed on), kept in `data/normalization_audit.json` with the mention and source spans, and added
to `data/normalization_conflicts.json`, which every later normalization in the run checks. Each validation
records the identities A06 saw; a finding whose identity changes afterwards is `REVALIDATION_REQUIRED`, so
correcting an identifier never promotes a finding by itself.

`litreview renormalize RUN` re-runs normalization with the current rules (no model calls), archives the
previous extractions and validations under `data/renormalization/`, and lists the papers needing
revalidation with the cost of their last A06 call. `litreview revalidate RUN --records ...` (or
`--all-needed`) runs a fresh A06 validation of those papers; their theme records are then stale and
synthesis waits for `litreview revalidate RUN --themes`. `litreview gate2-report RUN` reports recovery and
new error side by side.

**Revalidation review** (`evidence.review_changes`). When a paper is revalidated, a disposition that changes
with no change to the finding's extraction, and no correction of an identity A06 had objected to, is not
applied: an improvement, or a finding losing the role it had, is `QUARANTINED` (usable in no role) until you
decide it with `litreview review-validation RUN FINDING --keep-old|--accept-new|--hold --note "..."`, after
reading the source, the extraction and both A06 readings. `--hold` (KEEP_QUARANTINED) is a decision that
neither reading is confirmed; the finding stays out of every role and every recovery tally. Every decision
carries the disagreement's cause (`--cause`, alone or with the decision): `BIOLOGICAL_INTERPRETATION` (the
extraction is faithful; the readings differ on what the evidence warrants), `EXTRACTION_ERROR` (the extraction
misrepresents the source; the readings differ on whether that blocks it), `CHANGED_CONTEXT` (a demonstrated
input difference accounts for it) or `UNEXPLAINED_MODEL_VARIANCE`. The command lists quarantined findings by
cause, which says whether the fix is prompt work or repeated validation. A narrowing that changes no role is
applied and noted. A06 is not deterministic at temperature 0.0 (run 20261025-100039: one of three findings
changed disposition between two byte-identical calls), so a revalidation result is a second reading, not a
correction, unless the input changed. The reading a decision keeps is the one the finding carries everywhere:
disposition, constraints and limit as well as eligibility (`evidence.effective_validations`).

**A06 instability test** (`pipeline.yaml -> validation.instability_test`). After per-paper validation, every
paper with a blocked finding is validated once more, whole paper against whole paper: the input saved at the
original call (`data/a06_inputs/`) is replayed unchanged (prompt, paper text, extraction, entity identities,
Gate 1 results) under the same model settings, and a paper whose conditions changed since is skipped, never
compared. The replay input is re-hashed against the hash taken at the original call, before the repeat and
again before the comparison; a mismatch invalidates that paper's comparison (`invalid`, counted nowhere).
`data/instability_test.json` records agreement for every finding in the repeated papers and for the blocked
findings on their own, as counts, with the channel (batch or interactive) of each call. A finding whose two readings
give it different roles is quarantined for human review; where the roles agree, the more cautious reading
stands. The original validation file is never replaced. One repeat per paper is priced in the CP2 projection.

**Handoff contract** (`src/litreview/handoff.py`). Every validated finding carries `predicate` and
`predicate_detail`, `polarity`, `direction`, `modality`, `assertion_type`, `attributed_to`, `origin`,
`alignment_disposition` and its eligibility, and synthesis does not start if any is missing. A07 receives
them as fields (it gets no spans). A05-KE v0.5 adds predicates for interactions (`SYNERGIZES_WITH`,
`ANTAGONIZES`, `ADDITIVE_WITH`, `POTENTIATES`), `NO_SIGNIFICANT_DIFFERENCE` (non-significance, not absence of
effect) and intrinsic predicates that may have no object (`OBSERVED_OUTCOME`, `TOLERATED`,
`MAXIMUM_TOLERATED_DOSE`, `HALF_LIFE`); `OTHER_SPECIFIED` must name its relation in `predicate_detail`
(schema and code). Older extractions keep `OTHER_SPECIFIED` with the relation in the warrant note, marked
`LEGACY_WARRANT_NOTE`.

**Cost projection at CP2** (`src/litreview/tools/cost_projection.py`). `litreview cost-rates RUN` measures
per-paper (A05 + A06, by content level, 90th percentile) and per-theme costs into `records/cost_rates.json`.
CP2_review.md shows the projection; approving CP2 refuses a selection projected over the cap, with A07 to
A12 priced at worst case (configured max_tokens, A07 paying a cache write on every call). A07's input per
call is its largest call, FINAL: 25,000 + 1,300 tokens per finding, measured with the real payload builder and
the token-counting endpoint (the earlier 821 understated the current payload by about 35%). After CP2, no
agent call runs without a projection within the cap in `data/cost_projection.json`; `litreview project RUN`
re-projects what a run still has to spend: the per-paper work not yet done or in flight, and every
downstream agent whose last stage is still ahead. A WORST_CASE line is a bound. Once an agent's spend since the
projection exceeds its line, or its next call would go beyond the line's number of calls, the projection is
superseded and nothing more is called until the run is re-projected. Each A07 turn is priced as one attempt: a truncated turn is paid,
produces nothing and stops the job, so it supersedes the projection, and resuming requires a new one priced
from actual spend (turns already committed are not priced again).

**Downstream admission** (`admission`, `src/litreview/admission.py`). Before every A08, A09, A11 and A12
request, the exact serialized request is bounded in UTF-8 bytes (never below its token count) and must fit
the routed model's window (`admission.context_windows`) with its output reserve (`max_tokens`, plus
`reasoning_reserve_tokens` for providers where reasoning is not established to count within it). A request
that cannot be bounded, or whose model has no recorded window, is refused. Kimi K3.1 Pro has no recorded
window, so A11 on Kimi is refused until a documented value is added. A request that does not fit is
subdivided by a fixed rule or the stage stops. A09 writes one section per request, and a section too large
for one request stops the stage: the plan must split it. A12 edits the whole manuscript, or one unit at a
time (front matter, then each section) when the whole does not fit. A08 and A11 are single requests and stop.
Nothing is truncated or dropped to fit.

A request whose bound is above the model's long-context threshold (GPT-6.1: 272k) is repriced in full, so it
is dispatched only if the current projection priced that many long-context calls for the agent
(`long_context_calls`); otherwise the projection is superseded and the run re-projected. Each request then
passes the runtime gate (`batch.gate_usd`, the same $150 stop as batches: spent + committed + projected +
this request) and holds a reservation for its bound under `run.spend_cap_usd` until it settles. The A08 to
A12 projection lines (`src/litreview/tools/downstream_projection.py`) come from the same request builders
(`REQUEST_BOUND` once the approved package exists, `ESTIMATED_ENVELOPE` before it), price input at the byte
bound divided by 1.8 (below every free provider count measured), and are re-made at the start of each of
those stages. Spend or calls past a line supersede the projection before the next call.

**The bridge** (`bridge`, `src/litreview/bridge.py`). Code, not a model, hands the approved synthesis to the
writing agents. A08 receives a compact argument map and one line per element, and returns a plan and an
allocation ledger: every proposition, gap and adopted interpretation is `DISCUSSED`, `GROUPED_WITH`,
`TABLE_ONLY` or `NOT_INDIVIDUALLY_DISCUSSED` (with a reason). Mandatory elements are always written: conflicts,
contrary CORE evidence, researcher-verified inconsistencies, system gaps and NARRATIVE coverage. Groups have
at most `max_group_size` members. The plan is checked by code, and with `ledger_approval` the run stops at
`CP_LEDGER` (`litreview approve RUN CP_LEDGER`) before anything is written.

A09 then writes section by section from packets. Each packet holds A07's records verbatim, the findings
behind them, the union of a group's qualifications, and the contrary context from other sections. Each
request also carries the outline and all earlier prose. A gate runs after every section: tags, numbers,
citations, display references, heading and terminology. A09 may request evidence from the registry at most
`max_retrieval_rounds` times per section. After assembly, one A12 `INTEGRATION` pass runs, then A10.

The single display item is the comparative table `T1`, built by code with `table_max_rows` rows.
`output_limits` size A09 and A12 requests to the unit written. Fingerprints of the text, plan and
evidence-registry version stamp every A10 approval; A11 and A12 refuse a stale one.

**Evaluation-only runs** (`src/litreview/publication.py`). `litreview mark-evaluation-only RUN --reason ...`
stamps the run's synthesis in its own data; CP3, the outline, display tables, verification, critique and
every later stage refuse a stamped synthesis, in that run or any run it is copied into.

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
