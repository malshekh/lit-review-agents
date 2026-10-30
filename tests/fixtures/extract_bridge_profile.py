"""Extract the real proposition distribution used by the bridge fixtures. Read-only; no API calls.

    python -B tests/fixtures/extract_bridge_profile.py <path to runs/20261025-100039>

Writes tests/fixtures/bridge_profile.json.gz, marked evaluation-only. The run is never written: its file tree
is hashed before and after, and a difference is an error.

Sources (all from the reference run):
  propositions      the 63 complete propositions recoverable from the run's A07 output (A07-SYN_v2.raw0.txt),
                    whose tail was truncated at max_tokens; objects are parsed one by one, never repaired
  findings          validated_findings.json, with their source quotations (spans): A10 refuses to verify a claim
                    from a finding without its original passage, so the integrated simulation needs them
  corpus            selected_corpus.json citation metadata, tier and contrary-evidence flags
  conflicts         every CONFLICT in theme_records.json
  systems_missing   every distinct `systems_missing` string in theme_records.json (A07's SYSTEM_GAP items)
  inconsistencies   inconsistencies.json items, with their required visibility
  theme_records     theme_records.json (A06 per-theme results), to build an A07 registry for the integrated
                    simulation (tests/integrated_pipeline.py)
  spec_approved     spec_approved.json (the review specification approved at CP1)
"""
import gzip
import hashlib
import json
import sys
from pathlib import Path

OUT = Path(__file__).with_name("bridge_profile.json.gz")


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def recover_propositions(raw: str) -> list[dict]:
    start = raw.index("[", raw.index('"propositions"')) + 1
    dec, out, j = json.JSONDecoder(), [], start
    while True:
        while raw[j] in " \n\r\t,":
            j += 1
        if raw[j] != "{":
            break
        try:
            obj, j = dec.raw_decode(raw, j)
        except json.JSONDecodeError:
            break   # the truncated object: never repaired or guessed
        out.append(obj)
    return out


def main(run: Path) -> None:
    before = tree_hash(run)
    data = run / "data"
    load = lambda n: json.loads((data / n).read_text(encoding="utf-8"))
    props = recover_propositions((run / "outputs" / "A07-SYN_v2.raw0.txt").read_text(encoding="utf-8"))
    findings = load("validated_findings.json")
    corpus = [{k: r.get(k) for k in ("record_id", "title", "authors", "year", "venue", "tier", "themes",
                                     "is_preprint", "is_contrary_evidence", "doi", "pmid")}
              for r in load("selected_corpus.json")]
    themes = load("theme_records.json")
    conflicts = [{"theme": th, "index": i, "conflict": c} for th, rec in sorted(themes.items())
                 for i, c in enumerate(rec.get("conflicts") or [], 1)]
    missing = sorted({m for rec in themes.values() for m in (rec.get("evidence_reach") or {}).get("systems_missing", [])})
    profile = {"evaluation_only": True,
               "notice": "Evaluation-only fixture derived from reference run 20261025-100039. Not a scientific "
                         "synthesis, never a manuscript input.",
               "reference_run": run.name, "propositions": props, "findings": findings, "corpus": corpus,
               "conflicts": conflicts, "systems_missing": missing,
               "inconsistencies": load("inconsistencies.json"), "theme_records": themes,
               "spec_approved": load("spec_approved.json")}
    if tree_hash(run) != before:
        raise SystemExit("the reference run changed while it was read")
    with gzip.open(OUT, "wt", encoding="utf-8") as fh:
        json.dump(profile, fh, ensure_ascii=False, sort_keys=True)
    print(f"{len(props)} propositions, {len(findings)} findings, {len(corpus)} papers, {len(conflicts)} conflicts, "
          f"{len(missing)} system-gap strings -> {OUT} ({OUT.stat().st_size:,} bytes); run tree unchanged")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
