"""Extract the R0030 Gate 1 fixture from reference run 20261025-100039. Read-only; no API calls.

    python -B tests/fixtures/extract_r0030.py <path to runs/20261025-100039>

Writes tests/fixtures/r0030_gate1.json: findings F18, F20 and F21 of R0030's extraction, and only the full-text
sections their quotes come from. The script refuses to write unless span repair and Gate 1 give the same
result per finding on the subset as on the complete source (removing text can never make an ambiguous repair
look unique without this check failing), and unless the run's file tree is unchanged.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from litreview.tools import span_check  # noqa: E402

OUT = Path(__file__).with_name("r0030_gate1.json")
IDS = ("F18", "F20", "F21")


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def outcome(ext, sections):
    repaired = span_check.repair_findings(ext, sections)
    gates = {g["finding_id"]: g for g in span_check.check_findings(repaired, sections)}
    return {f["finding_id"]: (span_check.passed(gates[f["finding_id"]]), f["span"], f.get("span_corrections"))
            for f in repaired["findings"] if f["finding_id"] in IDS}


def main(run: Path) -> None:
    before = tree_hash(run)
    data = run / "data"
    ext = json.loads((data / "extractions" / "R0030.json").read_text(encoding="utf-8"))
    sections = json.loads((data / "fulltext" / "R0030.json").read_text(encoding="utf-8"))
    keep = {k: v for k, v in ext.items() if k != "findings"}
    keep["findings"] = [f for f in ext["findings"] if f["finding_id"] in IDS]
    full = outcome(keep, sections)
    used = {f.get("section") for f in keep["findings"]} | {
        name for name, text in sections.items() for f in keep["findings"]
        if any(part.strip() and part.strip()[:60] in text for part in f["span"].split("..."))}
    subset = {k: v for k, v in sections.items() if k in used}
    if outcome(keep, subset) != full:
        raise SystemExit("the section subset changes a Gate 1 or repair outcome; not written")
    if tree_hash(run) != before:
        raise SystemExit("the reference run changed while it was read")
    OUT.write_text(json.dumps({"evaluation_only": True, "reference_run": run.name, "record_id": "R0030",
                               "extraction": keep, "fulltext_sections": subset,
                               "expected": {k: v[0] for k, v in full.items()}},
                              ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(keep['findings'])} findings, sections {sorted(subset)} of {len(sections)}; outcomes {dict((k, v[0]) for k, v in full.items())}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
