# Bounded planning recovery

The initial A03 planning request returned length at its unchanged 12,000-token
cap, with 12,000 output tokens reported and zero response-text characters. It
cost $0.175606, was fully accounted and released its transient reservation. The
five original unresolved holds still total $0.124671. No request is unsettled,
no zero billing is assumed, and no original response or cost is deleted.

The replacement is task decomposition, not a token-limit/model increase or a
blind repeat: each approved subsection gets a separately identified A03 request
with one question and a compact specification. Its original schema and model
remain unchanged, output cap 12,000; the 150-record planning budget is divided
across eight units (18 per unit). Code merges canonical outputs, prefixes family
IDs, preserves all query provenance, and handles each unit's existing bounded
search repairs. Source outages alone do not cause another paid planning call.
The original failed A03-LM_plan dispatch is not called again.

All source, CP1 approval, receipts, costs and holds are copied to a fresh v29
runtime; v28 is not modified in place. CP2 remains the hard execution stop before
corpus freeze or paid extraction. The existing $50 cap and $25/$48 reviews remain.
Full suite: **1,159 passed** (212.44 seconds). Focused discovery/merge tests:
**31 passed**. No corrected live planning unit was sent during these tests.
