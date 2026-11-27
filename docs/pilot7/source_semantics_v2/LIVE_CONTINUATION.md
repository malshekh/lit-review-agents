# Authorized A06-only live continuation

Researcher authorization 2026-11-24 for run 20261123-214928: at most $0.550645
additional for seven strict checks and corrected-record independent A06 with at
most one structure-only format repair. All five existing holds ($0.124671), all
receipts, original dispatches and the failed functional verdict remain intact.
Cumulative smoke allowance $1; combined pilot cap $50; reviews $25/$48.

The new runner executes A06 strict first, then A06-only, then the other six strict
checks, then separately authorized scope to CP1. The archived A05 is never called.
The reviewed prepared payload hash remains
`1cb1af9df9d9767aec4b22fc23fb3b97c64d509f12ca78a08efcb8e220259056`.
No provider schema changes are introduced. A06 prompt v0.11 asks for two explicit
label decisions within the existing warnings array; no new schema properties.
The input remains below the inherited 64,000-byte bound; output stays 2,500 tokens.
Worst-case A06 including one repair stays $0.37; strict checks stay $0.180645.

A06 must assess all three findings with aligned source gates and supported
qualified dispositions, preserve sampled specimen/non-absence/375 mg combination
regimen limits, and explicitly decide both historical quarantined labels. Any
remaining MAJOR/CRITICAL scientific defect, missing decision or scientific failure
stops without using a format repair to change its assessment. If a format repair
is used, all scientific assessment fields must be identical to their parsed
original; an unparseable original that cannot establish preservation is stopped.
Raw replies, error receipts and billing reservations remain durable.

Builder scripts/build_pilot7_semantics_runtime.py verifies ancestry of 1048330,
the v26 manifest pin, all 149 reviewed source-run hashes, a clean source commit,
and fresh destination before exporting. It copies the same run and archives the
old runtime pin, never changes v26, and seals all source/config/authorization files.
The new runtime is v27; its resulting commit and manifest are recorded externally
in runs/v27_runtime_pin.json and the continuation closeout report.


Offline verification before sealing: full suite **1,147 passed** (204.13 seconds);
focused continuation/scientific/budget suite **85 passed**; exact-payload/label/
structure-only-repair tests **3 passed**. Updated prompt plus schema/framing is
48,503 bounded input bytes, under the unchanged 64,000 cap. Builder is invoked
with `python -B` and refuses bytecode-enabled execution to protect v26's vendor.
