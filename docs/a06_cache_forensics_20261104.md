# A06 cache forensics and development optimization ? 2026-11-04

## Verdict and boundaries

The cache cause is established structurally. The development optimization is offline-validated, with a separately approved live cache benchmark still required. No provider generation, scientific restart, financial approval, runtime promotion or benchmark-key access occurred. The active v8 runtime remains unchanged. Real optimized savings and scientific equivalence of live model outputs are not yet demonstrated.

## Source reconciliation

Active scientific runtime: `stage1-a06-batched-v8-20261103`, run `20261031-213324`. Frozen manifest SHA-256: `532683a10e183bb82a29bfea7d0a3558b7a61bfe292e8875cb5f410a34213718`. Reverification: 6,472 immutable files plus 12 reconciled model-record telemetry appends.

Integration HEAD `daaebcaf538aafb07b6635d3a9f4aabeb281346d` did not contain committed `a06_batches.py`; the working copy did. The original module is byte-identical in v8 and the integration worktree. The frozen runtime excluded Task 7 diagnostics; integration base.py/router.py include those unrelated edits. Orchestrator and authorization differences include earlier A03/A05/financial repairs. Only A06-specific hunks, the general bounded module and synthetic tests were synchronized here, in commit `65f1b62`. The original integration worktree/branch was not changed.

The verified origin is `https://github.com/malshekh/lit-review-agents.git`. At inspection, remote task3-integration was `43f533a`; the local approved memory, corpus-integrity and inventory fixes are preserved as ancestors, not rewritten. No complete frozen bundle, raw payload, ledger, scientific output or new reference-key material is included in the new commits. A reference draft already existed in the remote ancestry; this work neither reads nor adds its contents.

## Actual provider, requests and rates

All 13 receipts say OpenAI / `gpt-6.1-sol`, matching the configured primary route. No fallback is evidenced. The runtime client calls Chat Completions synchronously, not the vendor Batch API. Code/config reconstruct the default endpoint as `https://api.openai.com/v1/chat/completions`; original HTTP URLs, headers and response IDs were not captured.

Frozen prices and current official standard short-context pricing agree: ordinary input $2/M, default 30m writes $2.50/M, reads $0.10/M, output $10/M. Writes replace ordinary input pricing, rather than adding to it. See [official pricing](https://developers.openai.com/api/docs/pricing). No long-context threshold is crossed by these recorded requests.

The original requests sent no explicit cache options, breakpoints or retention override. Default automatic caching applies. The pipeline cache_ttl field is Anthropic-only here; its 5m default did not request 5m OpenAI storage. The old summary?s ?5-minute? caption was misleading; development reporting now labels this bucket default retention without changing historical token counts or charges. Current [OpenAI caching guidance](https://developers.openai.com/api/docs/guides/prompt-caching) documents 30m default writes.

All counts below are provider-usage-derived normalized ledger values; dollars are internal price-table calculations, not an independently obtained provider invoice. `in` is total prompt usage (ordinary + reads + writes). Ordinary input was 3 tokens per call; 1h writes were zero. Times are ledger clock strings without timezone. Durations approximate start-to-ledger elapsed time (not provider latency) using the recorded epoch and ledger clock. Provider stop reasons and reasoning-token breakdowns were not retained. Successful JSON/schema/coverage acceptance is independently visible; it does not recover an exact finish_reason.

| Call | Ledger time | Approx seconds | in | write | read | out | Recorded USD | Accepted |
|---|---|---:|---:|---:|---:|---:|---:|---|
| original 32k | 2026-11-01T11:12:28 | 275.7 | 138,927 | 138,924 | 0 | 32,000 | 0.6673160 | no ? truncation |
| B001 try1 | 2026-11-03T23:07:29 | 90.2 | 58,671 | 58,668 | 0 | 8,420 | 0.2308760 | yes |
| B002 try1 | 2026-11-03T23:09:13 | 99.9 | 59,204 | 53,397 | 5,804 | 9,231 | 0.2263889 | yes |
| B003 try1 | 2026-11-03T23:10:49 | 92.1 | 59,057 | 53,250 | 5,804 | 8,970 | 0.2234114 | yes |
| B004 try1 | 2026-11-03T23:12:53 | 120.1 | 59,094 | 53,287 | 5,804 | 8,924 | 0.2230439 | yes |
| B005 try1 | 2026-11-03T23:14:38 | 101.3 | 60,374 | 54,567 | 5,804 | 8,344 | 0.2204439 | yes |
| B006 try1 | 2026-11-03T23:16:42 | 119.9 | 63,015 | 57,208 | 5,804 | 8,951 | 0.2331164 | yes |
| B007 try1 | 2026-11-03T23:18:32 | 106.1 | 62,807 | 57,000 | 5,804 | 8,969 | 0.2327764 | yes |
| B008 try1 | 2026-11-03T23:20:23 | 107.1 | 62,309 | 56,502 | 5,804 | 8,927 | 0.2311114 | yes |
| B009 try1 | 2026-11-03T23:22:03 | 96.5 | 62,968 | 57,161 | 5,804 | 8,510 | 0.2285889 | yes |
| B010 try1 | 2026-11-03T23:23:41 | 94.4 | 60,407 | 54,600 | 5,804 | 8,221 | 0.2192964 | yes |
| B011 try1 | 2026-11-03T23:25:18 | 93.3 | 61,297 | 55,490 | 5,804 | 7,879 | 0.2181014 | yes |
| B012 try1 | 2026-11-03T23:27:05 | 102.5 | 60,976 | 55,169 | 5,804 | 9,026 | 0.2287689 | yes |

Every bounded call was try1; no batch retried. Gaps between successive bounded starts were 94.3?123.8 seconds, below the default retention interval. The long gap since the failed whole-paper attempt does not explain repeated writes within the bounded sequence.

Exact A06 totals: 39 ordinary input, 805,223 default writes, 63,844 reads and 136,372 output tokens; $3.3832399. Write cost $2.0130575, read cost $0.0063844, ordinary cost $0.000078, output cost $1.36372. The failed attempt is included exactly once: $0.667316. Twelve accepted units cost $2.7159239. Cumulative scientific spending after them is $7.3163356, matching the displayed $7.32. A06 read discounts saved $0.1213036 against ordinary input; write premiums added $0.4026115: net cache effect ?$0.2813079.

## First difference and cache boundary

Original wire bodies were not saved. Deterministic reconstruction uses the exact frozen builders and saved full A06 input. All 12 reconstructed payload fingerprints match their accepted batch manifest. With compact UTF-8 JSON request serialization, B001/B002 first differ at zero-based character **64,878**, byte **65,068**. These are reconstruction offsets, not claimed captured SDK wire offsets. The first payload field difference is `/extraction/contexts/0/fields/evidence_system`; no scientific value needs reproducing.

Within the user text, the difference is character 38,018. The actual `paper_text` JSON key begins at character 59,740, after the mismatch. The system is identical (25,221 characters). There are no dynamic timestamps/request IDs in these message bodies; varying extraction contexts/entities/findings precede the source. Batch IDs and requested finding IDs also occur in variable content. The response format is identical `json_object`; the original full output JSON schema was enforced locally, not transmitted as a separate JSON schema. System format instructions were identical.

Local o200k_base counts: system 5,801, common user prefix 7,615, combined visible-text prefix 13,416 tokens. The explicitly named model has no tokenizer mapping in the available package, so these are estimates excluding hidden/framing tokens, not provider-counted totals. The 5,804-token reads closely match the system estimate plus framing, strongly consistent with reuse ending there. Provider lookup diagnostics were not saved, so the exact server boundary cannot be proven.

Root cause: automatic caching had no explicit reusable-paper boundary, and the user message changed before the full source. A long common substring later in a prompt is insufficient. [The Chat Completions API reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) supports explicit-only mode and text-block cache breakpoints.

## Before and after

Before: system instructions ? compact JSON with batch-varying extraction context/findings ? paper text ? gate results/index/unit metadata; automatic cache placement.

After: identical system ? one canonical shared block (scope, source, full-paper finding index, record/access identity, source hash, unchanged output schema) ? explicit boundary ? batch extraction/context/findings, gates and unit metadata. Source content is preserved verbatim in JSON values. The shared block is built/serialized once and referenced across all units. Variable data is ordinary input rather than a speculative cache write. Source/schema/scope or paper/access identity changes alter the prefix.

Implementation: `a06_request.py:12` builds shared context; `:23` splits variable data. `a06_batches.py:31` builds work units, `:64` validates them, `:81` merges, `:114` audits/resumes. `agents/base.py:79` uses the shared request parts. `llm/openai_compatible.py:25` builds both interactive and vendor Batch bodies, with explicit settings at `:37`. `orchestrator.py:350` preserves normal guarded dispatch; `:1027` prevents oversized vendor Batch bypass. `tools/cache_cost.py:2` provides a pure offline scenario model.

Production output cap remains 64k; batch size remains ?15 and one truncation retry per batch. No scientific prompt wording, model route, evidence eligibility, checkpoints or spending policy changes. Kimi receives ordered content with no OpenAI-only fields. Existing Anthropic blocks and routing remain independent. Current Chat Completions request-level 12h is unsupported in the documented schema and rejected by this builder; no endpoint migration or deprecated retention parameter is introduced.

## Conditional cost comparison ? not a live benchmark

The local optimized shared prefix is approximately 49,210 tokens including system; variable portions range 10,001?14,347. Shared-prefix warm reads would total 541,310 across 11 later calls, versus observed 63,844 reads. This is modeled eligibility, not measured hits. Total local input rises from 730,059 to 736,686, chiefly because the exact output schema is now explicit. Scientific output is held fixed at observed 104,372 tokens for comparison.

| Configuration | Conditional 12-unit USD | Status |
|---|---:|---|
| A: no caching, standard input | 2.5171 | modeled |
| B: 30m shared prefix, first cold then 11 warm | 1.5132 | modeled |
| B: every prefix cold/missed | 2.8124 | modeled adverse |
| C: hypothetical 12h, first cold then warm | 1.6362 | modeled only; no current Chat request dispatch |
| Original bounded execution | 2.7159 | observed usage ? configured prices |

Conditional saving versus observed bounded execution: **$1.2027**, about 44.3%. The suggested $1.30 is not established by measured optimized behavior. Zero optimized provider calls have been made. Longer retention adds an initial write premium and has no modeled advantage over 30m for the observed ~2-minute spacing. Cold misses can erase savings; do not promise them across 120 heterogeneous papers.

## Scientific quality and regression scope

The accepted original R0001 result has 180 dispositions, 180 unique IDs, complete coverage and retained source/validation provenance. These checks establish structure, not independent correctness of every judgment.

Mocked original/optimized comparisons retain identical findings, numerical/unit restrictions, positive/negative/null/contrary qualifiers, mechanistic uncertainty and missing-access limits through the same deterministic merge. Tests also exercise abstract-only sources, source/schema/paper identity, dangling/unknown IDs, full-source mismatch, truncated rejection, exhausted retry, accepted-unit reuse, actual Run.agent accounting and the installed SDK request transformation before a mocked HTTP post. A07 evidence/constraint/eligibility regressions remain in the complete suite. No live optimized dispositions exist for scientific comparison, and no protected answer key was consulted.

The failed whole-paper raw response is empty and usage is 32,000 completion tokens. The runner rejected truncation and saved no accepted whole-paper validation. Reasoning-token consumption is not separately recoverable; excessive findings/repetition cannot be diagnosed from an empty response. The $0.667316 is an unrecoverable historical charge and remains counted. Bounded calls used 7,879?9,231 completion tokens and all 12 were accepted; this run avoided recurrence, while tests prove a future truncated batch cannot invalidate completed units or be accepted as complete.

Final offline suite: **740 passed in 186.12s**, zero skips/deselections. Focused A06 suite: **30 passed**. The three historical-dependent tests ran successfully against a temporary copy; all 562 original files were hash-verified unchanged. Peak process working set on the final run is recorded in the external audit log. `git diff --check` passed. `litreview check` resolved all routes/prices; it reported missing API credentials in this intentionally credential-free development worktree. That is not a production credential or authentication test. The branch intentionally excludes unrelated A03/A05 and Task 7 tests; its total therefore differs from the prior 891-test integration suite. Historical-dependent tests run against an isolated temporary copy with original assertions intact, not silently skipped.

## Proposed separately approved benchmark ? hard cap $1.00

No benchmark executed. Proposed three calls using two authorized, already accepted representative full-source work units, stored only in a separate evaluation area/ledger: A no-cache unit 1; B cold explicit-prefix unit 1; B warm-prefix unit 2. Preserve identical instructions/source/schema and complete submitted ID sets. Use 12k completion caps for this diagnostic only (observed units needed <9.3k); if any output truncates or is incomplete, reject it and stop without retries. These diagnostic outputs never enter the scientific run. Production retains 64k.

Admit the three-call experiment only after a supported provider token count or otherwise defensible bounded request cost shows all three full output allowances fit $1.00; otherwise reduce the experiment or return for review without calls. Expected measured-density cost is approximately $0.65?$0.85, not a spending authorization. Disable automatic API retries. Reserve remaining benchmark budget before each call; charge failures too. Unsupported extended retention is not tested on this endpoint. No Stage 1 money or authorization is reused.

Collect model/endpoint, source/schema/request hashes, SDK/provider response IDs, elapsed time, provider usage and finish reason, normalized disjoint token classes, acceptance coverage and price-based charge; no prompt text, source findings, secrets or benchmark answers in reports. Usage-priced estimates must be labeled separately from invoice/dashboard reconciliation. Success requires substantial shared-context reuse on the final call, lower matched-work cost, full schema/ID acceptance and unchanged scientific constraints. A miss or inconclusive result is reported without repeated paid experiments.

## Remaining decisions

Separate approval of the ?$1 benchmark is required before any new provider spending. Actual optimized cache reuse, billed savings and live scientific equivalence remain unresolved until that evaluation. Runtime promotion is a later, separately reviewed action. No Stage 1/Stage 2 execution or approval is performed here.

### Runtime / integration SHA-256 comparison

These hashes describe the original v8 and the preserved integration working tree before this isolated optimization.

| File | Frozen v8 SHA-256 | Integration SHA-256 |
|---|---|---|
| `src/litreview/a06_batches.py` | `c7625b0b7afaf37247f480a5567dcb02e9618d4269dd9055dc0f08d526d5db68` | `c7625b0b7afaf37247f480a5567dcb02e9618d4269dd9055dc0f08d526d5db68` |
| `src/litreview/orchestrator.py` | `413dcc7c3e490bde98f06dfedecf66c88da970940b17f21cf0e1e2d2e2789fb9` | `413dcc7c3e490bde98f06dfedecf66c88da970940b17f21cf0e1e2d2e2789fb9` |
| `src/litreview/pilot_authorization.py` | `ff20ce4f970b2610e09bff6fa5752a8fa84e98fe789492bcebf8858dbab99d47` | `ff20ce4f970b2610e09bff6fa5752a8fa84e98fe789492bcebf8858dbab99d47` |
| `src/litreview/agents/base.py` | `6c152eec6d6d4964bbd6754c7850a0cfcaab14d88641b056ab67589bf97b92d8` | `2f312212c793ca35f02e663c757103c199407398d4b3c484b25ae15c59a4aa2a` |
| `src/litreview/llm/openai_compatible.py` | `144ae67bf84c4575abcea5fc3da908999b42e58d96fafb5777d88dd00b8eb2d8` | `e5baca66cff1c3aae53f2af7216acd66771f460eb753d4a170962d2a970a9491` |
| `config/pipeline.yaml` | `aaae72be94582ff07b2fc2e67c5c53d84a4a0f96b596684443c8b04421f4c7ac` | `e291daa710cd9d90af1132cbd3aa1603b8990affd1eb638b23079b223efbc3e6` |
