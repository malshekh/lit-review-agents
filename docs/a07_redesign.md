# A07 bounded scientific synthesis

Implemented without paid calls, research agents, manuscript generation, or historical-run changes.

## Why the previous design failed

The old orchestrator sent the complete detailed corpus on every PLAN/GROUP/FINAL call. Grouping
bounded output, not input. FINAL appended all complete proposition bodies; PLAN enumerated finding
membership and coverage. The October 29 provider-counted replicated workload reached approximately
2.37M PLAN input and 2.61M FINAL input tokens at 120 papers, with 78,654 PLAN output tokens excluding
thinking. Caching cannot reduce context occupancy.

## Production design

`EvidenceRegistry` retains every validated finding, context, source reference, A06 disposition and
limitation. A07 also preserves source entity attributes from the extraction without altering A05/A06
scientific rules. Primary theme assignments are approved upstream; packet boundaries never become
new primary themes or manuscript sections. Long manifest identifiers have stable short aliases with
an explicit reverse mapping.

1. PLAN receives a compact global finding/entity/context index and global coverage/identity counts.
   It emits only proposed changes, scope concerns and unresolved questions. Code owns membership.
2. CP_SYN stops before GROUP. The researcher reviews approved themes/subthemes, explicit study IDs,
   unknown independence, unmapped/emerging findings, source-linked conflict IDs and proposed changes.
   Approving keeps the current framework. Adopting changes requires revising the upstream framework
   and regenerating affected evidence before a new plan; A07 never silently applies a proposal.
3. GROUP receives bounded findings, full contexts, source entity attributes and mandatory source units.
   Targeted retrieval searches the complete registry, including findings outside the current theme.
   Requests are bounded to 12 findings, with at most two additional rounds; unmet needs stop explicitly.
4. RECONCILE reviews each proposition against the global compact proposition index, in focal pages.
   Issues require detailed retrieved finding anchors. Contradictions retain both sides and attach
   limitations to every affected proposition. Shared evidence is recorded globally, not summed across
   packets. Unsupported interpretations stop for upstream/human review.
5. FINAL reads compact proposition/gap indexes and reconciliation, not all raw findings or full bodies.
   It emits thesis options and explicitly proposed interpretations. The package is assembled in code
   with complete evidence links, constraints, attribution, source units and coverage for A08/A10.

Distinct explicit study/dataset/cohort IDs are counted globally; they are NOT assumed independent.
Unknown independence remains null. Replication claims require separate human/A06 adjudication.

## Acceptance, recovery and admission

- Every call is admitted using a conservative UTF-8 byte token bound plus framing, system prompt and
  output reserve. This bound is independent of caching. Oversized single evidence units stop rather
  than being truncated. Mode output caps include provider reasoning: PLAN 4k, GROUP 12k,
  RECONCILE 6k, FINAL 6k. Schemas additionally bound every output array and scientific string.
- Only complete schema-valid, evidence-valid turns commit. A rejected proposition rejects the whole
  response. Source-grounded/appraisal roles use the existing evidence rules; forbidden types,
  unknown/unseen IDs, false source bindings and unaccounted packet evidence stop the job.
- All mandatory items must be satisfied globally. Paper coverage cannot be replaced by an
  insufficient-evidence gap if that paper has usable findings. Structural satisfaction is not a
  semantic entailment judgment, evidence of extraction recall or proof of scientific correctness.
- Identity includes the entire registry, approved themes, feedback, prompts, schemas, model/prices and
  settings. Accepted turn files are hash-checked. Atomic replacement of turn/log files prevents partial
  commit lines. Accepted turns are reused; stale inputs start a different job and require new approval.
- A07 reserves each actual serialized request at its output cap with no cache discount before dispatch.
  JSON auto-repair is disabled for these calls: rejected/truncated calls stop and require re-projection.
  Unknown API billing leaves a reservation held for manual usage reconciliation, preventing an unsafe
  automatic duplicate request. No API calls were made to test this behavior.
- Incomplete synthesis cannot pass CP3 approval or enter A08. The existing $35 pilot cap is unchanged;
  the $150 batch gate is separate. No configuration cap was raised to make tests pass.

## Offline evidence

Reproduce from repository root with the existing environment:

```powershell
./.venv/Scripts/python.exe -B tests/a07_capacity_simulation.py --output docs/a07_capacity_redesign.json
./.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider --basetemp tests/.tmp-a07-test tests
```

The capacity script replicates existing evaluation records, preserving findings and thematic source
records. It assigns synthetic approved primary theme IDs only for this structural experiment; it
does not claim these are 120 distinct scientific papers. Its model outputs mechanically demonstrate
coverage, not scientific synthesis. The committed JSON contains per-mode input/output bounds, caps,
call counts, costs, coverage and a same-workload legacy comparison.

| Papers | Findings | Mandatory items | Calls | PLAN input bound | FINAL input bound | Largest input + output reserve |
|---|---:|---:|---:|---:|---:|---:|
| 40 | 642 | 347 | 68 | 313,223 | 92,139 | 317,223 |
| 80 | 1,353 | 474 | 103 | 598,715 | 143,928 | 602,715 |
| 120 | 1,996 | 688 | 149 | 858,995 | 202,589 | 862,995 |

All complete with zero pending mandatory items or unaccounted findings, below the 900,000 admission
ceiling. All raw fixture responses fit their output bounds. The same-workload legacy builder uses
5,601,041 PLAN and 8,202,678 FINAL input-bound units at 120 papers. These byte upper bounds are NOT
provider token measurements and should not be numerically equated with October 29 tokenizer counts.

## Cost conclusions and remaining blockers

At 120 papers the illustrative A07 planning scenario is $33.60: assume three UTF-8 bytes per token,
fixture-sized structured outputs plus reasoning equal to 25% of output caps, no retrieval and no cache
savings. These assumptions are unmeasured. The byte-bound, every-output-cap, full-cache-miss scenario
is $153.09 for A07 alone before retrieval/retries. Adding historical batch approximations, repeat
validation, thematic validation, discovery and untouched A08-A12 projections produces $278.45.
Even substituting the illustrative A07 planning estimate into that latter pipeline scenario gives
about $158.96. These are scenarios, not bills or promises. The conservative projection may refuse a
run that would actually fit; per-call reservations still prevent A07 from crossing the absolute cap.

The $150 complete-pipeline objective is therefore NOT established. A08/A10 context and cost issues
remain outside this change. Provider-calibrated token usage, scientific error/omission benchmarks,
live reasoning output sizes and actual downstream costs need evaluation before paid scale-up.
Longer or denser future corpora can still be refused safely by admission; no unlimited-capacity claim
is made. Context safety, valid links and structural coverage do not establish scientific reliability.

Only internal planning, registry, provenance, validation and benchmark records are generated here.
No manuscript, display item, AI-disclosure prose, cover letter or supplementary narrative was created.

## Exact file inventory

Added:
- `src/litreview/synthesis_registry.py`
- `src/litreview/synthesis_bounded.py`
- `schemas/A07-SYN.bounded-plan.schema.json`
- `schemas/A07-SYN.bounded-group.schema.json`
- `schemas/A07-SYN.bounded-reconcile.schema.json`
- `schemas/A07-SYN.bounded-final.schema.json`
- `tests/test_synthesis_bounded.py`
- `tests/a07_capacity_simulation.py`
- `docs/a07_capacity_redesign.json`
- `docs/a07_redesign.md`

Changed:
- `config/pipeline.yaml` — A07 packet, retrieval, reconciliation and output limits; no cap increase.
- `prompts/agents/A07-SYN_Synthesis.md` — bounded scientific synthesis contract.
- `src/litreview/synthesis_job.py` — atomic ledger append and commit replay support; legacy helper retained.
- `src/litreview/orchestrator.py` — registry integration, approval, reservation and incomplete-package guards.
- `src/litreview/checkpoints.py` — CP_SYN and CP3 completeness validation.
- `src/litreview/cli.py` — CP_SYN approval command.
- `src/litreview/agents/base.py` — optional reserved call, with A07 auto-repair disabled.
- `src/litreview/budget.py` — admitted calls may consume their own reservation.
- `src/litreview/tools/cost_projection.py` — bounded A07 estimated envelope, explicitly not a hard upper bound.
- `tests/test_synthesis_job.py` — production packet/approval integration replaces full-prefix expectation.
- `tests/test_instability_and_review.py` — updated remaining-call projection expectations.
- `tests/test_runtime_gate.py` — bounded projection and retrieval-cost expectations.
- `tests/test_spend_and_publication_guards.py` — estimated-envelope basis and independent admission fixture.

A05/A06 prompts/rules, A10 implementation and historical run data are unchanged. The final full-suite
verification passed 243 tests using a workspace-local temporary directory; `git diff --check` passed.
