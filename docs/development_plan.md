# Development plan (2 weeks)

| Days | Work | Status |
|---|---|---|
| 1–2 | Repo, config, model wrappers, budget monitor, provenance, CLI | ✅ done |
| 3–5 | Distil reused prompts; write new A02-SP and A08-OL | ✅ done |
| 6–8 | Literature tools, orchestrator, checkpoints; end-to-end run on a small topic | ⏳ PubMed, Europe PMC, OpenAlex done; first real run pending |
| 9–11 | Auditors, compliance checker, reference formatter, email | ✅ code done; needs real-run testing |
| 12–14 | Full run on the real topic; tune prompts and model assignments | ⬜ |

## Open TODOs

- [ ] Set OpenAI model IDs in `config/pipeline.yaml` and all prices in `config/prices.yaml`
- [ ] First end-to-end run on a small topic (~30 papers) to calibrate costs and token limits
- [ ] `tools/literature/`: PubTator3, Semantic Scholar, ClinicalTrials.gov clients
- [ ] Citation expansion (OpenCitations, depth 1, from qualified supportive *and* contrary seeds)
- [ ] `tools/normalization.py`: Cellosaurus, HGNC/MGI, ChEMBL lookups
- [ ] Render final manuscript to `.docx` (journal prefers Word) and embed figures/tables
- [ ] Display-item builder: evidence tables generated from validated findings
- [ ] Optional: Anthropic/OpenAI batch APIs for A04/A05/A06 to cut per-paper cost
