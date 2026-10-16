# Prompt lineage

Prompts were distilled from the drug-repurposing framework (v0.1, October 2026). Core
protections were kept; drug/target/condensate-specific rules and LLM-orchestrator governance
were removed; deterministic work moved to code. Each prompt's header lists exact section mapping.

| This system | Derived from | Change |
|---|---|---|
| `orchestrator.py` (code) | A1-O | LLM orchestrator → deterministic state machine; intake logic moved to A02-SP |
| A02-SP | A1-O §9–§10 | New agent; intake, readiness gate, disconfirming evidence, selection criteria |
| A03-LM | A2-LM (access-contract version) | Plans and repairs queries; code executes |
| A04-CQ | A3-CQ (canonical reconciled) | Eligibility + proposed themes/tiers; every paper shown to the researcher |
| A05-KE | A4-KE | General scientific vocabulary (entity types, study systems, context) |
| A06-SV | A5-SV | Span checking moved to code; evidence profiles per study system; theme-level pass |
| A07-SYN | A11-SYN | Proposed interpretations for researcher adoption; gap analysis; outline moved to A08 |
| A08-OL | A11-SYN §14, §18–20 | New agent; journal-fitted outline, budgets, display items |
| A09-WRI | A14-WRI | Sentence tags; language policy shared |
| A10-RV | A12-RV | Deterministic checks in code; no plan-review pass |
| A11-RC | A13-RC | Non-specialist reader pass added; no plan-review pass |
| A12-EDI | A15-EDI | REVISION / LINE / PROOF modes; tag preservation |
| `shared/language_policy.md` | A14-WRI §5–§11, A15-EDI §9 | One policy for writer, verifier, critic and editor |

Not carried over: A6-KGC, A7-GI, A8-MR, A9-MC, A10-DCR (knowledge graph, mechanism reasoning,
candidate ranking) — specific to drug repurposing.
