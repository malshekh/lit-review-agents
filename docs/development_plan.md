# Development plan (2 weeks)

| Days | Work | Status |
|---|---|---|
| 1–2 | Repo, config, model wrappers, budget monitor, provenance, CLI | ✅ done |
| 3–5 | Distil reused prompts; write new A02-SP and A08-OL | ✅ done |
| 6–8 | Literature tools, orchestrator, checkpoints; end-to-end run on a small topic | ✅ 6 databases, citation expansion, identifier lookups; ⏳ first real run pending |
| 9–11 | Auditors, compliance checker, reference formatter, email | ✅ code done; needs real-run testing |
| 12–14 | Full run on the real topic; tune prompts and model assignments | ⬜ |

## Open TODOs

- [x] Models and prices for Claude, OpenAI and Kimi (checked 2026-10-16)
- [x] PubTator3, Semantic Scholar, ClinicalTrials.gov clients
- [x] Citation expansion (Semantic Scholar, depth 1, supportive and contrary seeds)
- [x] Identifier lookups: HGNC, MyGene (mouse/rat), UniProt, ChEMBL, PubChem, Cellosaurus, OLS4
- [x] LangSmith tracing (optional)
- [ ] Fill in `.env`, run `litreview check --ping --apis` on your machine
- [ ] First end-to-end run on a small topic (~30 papers) to calibrate costs and token limits
- [ ] Before Dec 11, 2026: move A04-CQ from gpt-5-mini to gpt-6-luna (snapshot shutdown)
- [ ] Optional: DrugBank lookups (licensed API), depth-2 citation expansion
- [ ] Render final manuscript to `.docx` (journal prefers Word) and embed figures/tables
- [ ] Display-item builder: evidence tables generated from validated findings
- [ ] Optional: Anthropic/OpenAI batch APIs for A04/A05/A06 to cut per-paper cost
