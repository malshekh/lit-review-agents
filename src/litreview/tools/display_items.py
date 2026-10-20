"""Display items (A08-OL §5): evidence tables and figures built by code from validated findings.

A08-OL specifies each item (type, source propositions, columns or panels) and never supplies
values. This module fills tables only from validated findings and the selected corpus, and draws
only the figure whose content those fully determine: the evidence map. Schematics, data-summary
plots and adapted figures need a person; they get a brief listing what the figure must show and
distinguish, plus the underlying data, never an invented drawing.

Output per item (data/display_items/<id>.json, plus .csv and, for figures, .png or _brief.md):
  status  BUILT       table filled / figure drawn
          BRIEF_ONLY  figure must be drawn by a person from the brief
          EMPTY       none of the source propositions resolved to a validated finding
"""
from __future__ import annotations

import csv
import json
import re
import textwrap
from pathlib import Path

TABLE_TYPES = {"TABLE_EVIDENCE_SUMMARY", "TABLE_COMPARISON"}
NOT_REPORTED = "NR"
TABLE_ROWS_PER_PAGE = 25   # rough fit for one typeset page (journal table_max_pages: 1)
TABLE_COLS_PER_PAGE = 7


# ------------------------------------------------------------------ evidence rows
def _ctx(f: dict, *keys: str) -> str:
    c = f.get("context") or {}
    for k in keys:
        v = c.get(k)
        if v and v != "NOT_REPORTED":
            return str(v)
    return NOT_REPORTED


def _entity(f: dict, eid: str | None) -> str:
    e = (f.get("entities") or {}).get(eid or "", {})
    return e.get("approved_symbol") or e.get("mention") or (eid or NOT_REPORTED)


def _relation(f: dict) -> str:
    pred = (f.get("predicate") or "").replace("_", " ").lower()
    return f"{_entity(f, f.get('subject'))} {pred} {_entity(f, f.get('object'))}".strip()


def _quantities(f: dict) -> str:
    out = []
    for q in f.get("quantities") or []:
        s = " ".join(x for x in (q.get("measured_property"), q.get("raw_value"), q.get("raw_unit")) if x)
        extra = [x for x in (q.get("variance_or_ci"),
                             f"P = {q['p_value']}" if q.get("p_value") else None,
                             f"n = {q['n']}" if q.get("n") else None) if x]
        out.append(s + (f" ({'; '.join(extra)})" if extra else ""))
    return "; ".join(out) or NOT_REPORTED


def _study(rec: dict, rid: str) -> str:
    authors = rec.get("authors") or []
    first = (authors[0].split()[-1] if authors and authors[0].split() else "") if authors else ""
    label = f"{first}{' et al.' if len(authors) > 1 else ''}" if first else rid
    year = f" ({rec['year']})" if rec.get("year") else ""
    return f"{label}{year} [@{rid}]"


# (keywords in the column name, value for the row). First match wins, so specific rules come first.
COLUMN_RULES: list[tuple[tuple[str, ...], callable]] = [
    (("proposition",), lambda r: f"{r['proposition_id']}: {r['assertion']}"),
    (("study design", "study type"), lambda r: _ctx(r["f"], "evidence_system", "model_type")),
    (("study", "reference", "citation", "source", "paper", "author"), lambda r: _study(r["record"], r["record_id"])),
    (("species", "organism"), lambda r: _ctx(r["f"], "species", "species_from_cell_line_lookup")),
    (("cell line", "cell type", "cells"), lambda r: _ctx(r["f"], "cell_line_or_type")),
    (("population", "cohort", "participant", "patient"), lambda r: _ctx(r["f"], "population", "n_participants")),
    (("dose", "concentration"), lambda r: _ctx(r["f"], "dose_or_concentration")),
    (("duration", "timepoint", "time point"), lambda r: _ctx(r["f"], "duration", "timepoint")),
    (("comparator", "control"), lambda r: _ctx(r["f"], "comparator")),
    (("assay", "method", "readout", "measurement"), lambda r: _ctx(r["f"], "assay", "readout")),
    (("system", "model", "setting", "design"), lambda r: _ctx(r["f"], "evidence_system", "model_type")),
    (("construct",), lambda r: _ctx(r["f"], "construct", "genetic_modification")),
    (("intervention", "exposure", "agent", "drug", "compound", "subject"),
     lambda r: _entity(r["f"], r["f"].get("subject"))),
    (("outcome", "endpoint", "target", "object"), lambda r: _entity(r["f"], r["f"].get("object"))),
    (("value", "quantit", "magnitude", "effect size", "statistic"), lambda r: _quantities(r["f"])),
    (("direction", "polarity"), lambda r: (r["f"].get("polarity") or NOT_REPORTED).replace("_", " ").lower()),
    (("support", "conflict", "role", "agree"), lambda r: r["role"]),
    (("limitation", "constraint", "caveat", "qualif", "scope"),
     lambda r: "; ".join(r["f"].get("constraints") or []) or r["f"].get("plain_language_limit") or "None recorded"),
    (("evidence", "strength", "certainty", "disposition", "validation", "grade", "ceiling"),
     lambda r: (r["f"].get("disposition") or NOT_REPORTED).replace("_", " ").lower()),
    (("span", "quote", "verbatim"), lambda r: r["f"].get("span") or NOT_REPORTED),
    (("finding", "result", "observation", "effect", "relationship", "claim", "association"),
     lambda r: _relation(r["f"])),
]


def column_rule(name: str):
    n = name.lower()
    for keys, fn in COLUMN_RULES:
        if any(k in n for k in keys):
            return fn
    return None


def evidence_rows(item: dict, synthesis: dict, findings: list[dict], corpus: list[dict]) -> tuple[list[dict], list[str]]:
    """One row per finding behind the item's source propositions: supporting first, then conflicting.
    Source IDs that are finding IDs (R0001:F3) are used directly."""
    by_fid = {f["finding_id"]: f for f in findings}
    props = {p["proposition_id"]: p for p in synthesis.get("propositions", [])}
    recs = {r["record_id"]: r for r in corpus}
    rows, seen, missing = [], set(), []
    for sid in item.get("source_proposition_ids") or []:
        if sid in by_fid:
            pairs, assertion = [(sid, "supporting")], ""
        elif sid in props:
            p = props[sid]
            assertion = p.get("assertion", "")
            pairs = [(x, "supporting") for x in p.get("supporting_finding_ids") or []] + \
                    [(x, "conflicting") for x in p.get("conflicting_finding_ids") or []]
        else:
            missing.append(sid)
            continue
        for fid, role in pairs:
            f = by_fid.get(fid)
            if not f:
                missing.append(fid)
                continue
            if (fid, role) in seen:
                continue
            seen.add((fid, role))
            rows.append({"proposition_id": sid, "assertion": assertion, "finding_id": fid, "role": role,
                         "record_id": f["record_id"], "record": recs.get(f["record_id"], {}), "f": f})
    return rows, missing


# ------------------------------------------------------------------ tables
def build_table(item: dict, synthesis: dict, findings: list[dict], corpus: list[dict]) -> dict:
    rows, missing = evidence_rows(item, synthesis, findings, corpus)
    columns = list(item.get("columns_or_panels") or []) or ["Study", "System", "Finding", "Evidence"]
    rules = {c: column_rule(c) for c in columns}
    unmapped = [c for c, fn in rules.items() if fn is None]
    cells = [[fn(r) if fn else "" for c, fn in rules.items()] for r in rows]
    warnings = []
    if unmapped:
        warnings.append(f"Columns with no source field, left blank for the authors: {', '.join(unmapped)}")
    if missing:
        warnings.append(f"Source IDs not found among validated findings or propositions: {', '.join(sorted(set(missing)))}")
    if len(rows) > TABLE_ROWS_PER_PAGE or len(columns) > TABLE_COLS_PER_PAGE:
        warnings.append(f"{len(rows)} rows x {len(columns)} columns may exceed one typeset page; "
                        "split it or move part to Supplementary Information")
    return {"display_id": item["display_id"], "kind": "TABLE", "type": item.get("type"),
            "status": "BUILT" if rows else "EMPTY", "columns": columns, "rows": cells,
            "row_finding_ids": [r["finding_id"] for r in rows], "unmapped_columns": unmapped,
            "warnings": warnings}


# ------------------------------------------------------------------ figures
def evidence_map_data(rows: list[dict]) -> tuple[list[str], list[str], dict]:
    """Rows = propositions, columns = evidence systems; cell = (supporting, conflicting) finding counts."""
    props, systems, counts = [], [], {}
    for r in rows:
        system = _ctx(r["f"], "evidence_system", "species")
        system = "Not reported" if system == NOT_REPORTED else system.replace("_", " ").capitalize()
        if r["proposition_id"] not in props:
            props.append(r["proposition_id"])
        if system not in systems:
            systems.append(system)
        cell = counts.setdefault((r["proposition_id"], system), [0, 0])
        cell[0 if r["role"] == "supporting" else 1] += 1
    return props, sorted(systems, key=lambda s: (s == "Not reported", s)), counts


def draw_evidence_map(props: list[str], labels: dict[str, str], systems: list[str], counts: dict,
                      path: Path) -> bool:
    """Static journal figure: one sequential blue hue for the number of findings, a red outline where
    any finding conflicts, and the counts written in each cell so meaning never rests on colour."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import LinearSegmentedColormap
        from matplotlib.patches import Rectangle
    except ImportError:
        return False
    ink, muted, surface, blue, red = "#0b0b0b", "#52514e", "#ffffff", "#2a78d6", "#e34948"
    cmap = LinearSegmentedColormap.from_list("seq_blue", ["#eef4fc", blue])
    peak = max((s + c for s, c in counts.values()), default=1) or 1
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
                         "font.size": 7})
    width_in = 7.08   # 180 mm, double column
    fig, ax = plt.subplots(figsize=(width_in, 0.8 + 0.42 * len(props)), dpi=300, facecolor=surface,
                           layout="constrained")
    for i, p in enumerate(props):
        for j, s in enumerate(systems):
            sup, con = counts.get((p, s), (0, 0))
            n = sup + con
            fill = cmap(n / peak) if n else surface
            edge = red if con else "#d9d8d4"
            ax.add_patch(Rectangle((j + 0.04, i + 0.06), 0.92, 0.88, facecolor=fill, edgecolor=edge,
                                   linewidth=1.6 if con else 0.6))
            if n:
                dark_fill = n / peak > 0.8   # white text only where the fill is dark enough to carry it
                txt = f"{sup} supporting" + (f"\n{con} conflicting" if con else "")
                ax.text(j + 0.5, i + 0.5, txt, ha="center", va="center", fontsize=6,
                        color=surface if dark_fill else ink)
    ax.set_xlim(0, len(systems))
    ax.set_ylim(len(props), 0)
    ax.set_xticks([j + 0.5 for j in range(len(systems))])
    ax.set_xticklabels([textwrap.fill(s, 14) for s in systems], color=ink)
    ax.xaxis.tick_top()
    ax.set_yticks([i + 0.5 for i in range(len(props))])
    ax.set_yticklabels([textwrap.fill(textwrap.shorten(f"{p}  {labels.get(p, '')}", 80, placeholder="…"), 42)
                        for p in props], color=ink)
    ax.tick_params(length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    fig.supxlabel("Cell shade: number of validated findings. Red outline: at least one conflicting finding.",
                  fontsize=6, color=muted, x=0.01, ha="left")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300, facecolor=surface)
    plt.close(fig)
    return True


def figure_brief(item: dict, synthesis: dict, rows: list[dict]) -> str:
    props = {p["proposition_id"]: p for p in synthesis.get("propositions", [])}
    lines = [f"# {item['display_id']} — figure brief ({item.get('type')})", "",
             "Drawn by a person, not by the pipeline. Use only what is listed here.", "",
             f"**Purpose.** {item.get('purpose') or ''}", ""]
    if item.get("must_distinguish"):
        lines += [f"**Must distinguish (supported / inferred / unresolved).** {item['must_distinguish']}", ""]
    if item.get("columns_or_panels"):
        lines += ["**Panels.**", *[f"- {p}" for p in item["columns_or_panels"]], ""]
    lines += ["**Source propositions and their evidence ceiling.**"]
    for pid in item.get("source_proposition_ids") or []:
        p = props.get(pid, {})
        ceiling = (p.get("ceiling") or {}).get("disposition") or "see synthesis package"
        lines.append(f"- {pid}: {p.get('assertion', '(not a proposition ID)')} — ceiling: {ceiling}")
    lines += ["", f"**Underlying findings:** {len(rows)} (see the CSV next to this brief).", ""]
    if item.get("legend_points"):
        lines += ["**Legend points.**", *[f"- {x}" for x in item["legend_points"]], ""]
    if item.get("origin") == "ADAPTED_FROM":
        lines += [f"**Adapted from {item.get('adapted_from_record_id')}: copyright permission required "
                  "before submission.**", ""]
    lines += ["**Style.** Sans-serif labels, no 3D effects, untruncated axes, panels labelled a, b, c."]
    return "\n".join(lines)


def build_figure(item: dict, synthesis: dict, findings: list[dict], corpus: list[dict], out_dir: Path) -> dict:
    did = item["display_id"]
    rows, missing = evidence_rows(item, synthesis, findings, corpus)
    res = {"display_id": did, "kind": "FIGURE", "type": item.get("type"), "status": "BRIEF_ONLY",
           "image": None, "brief": f"{did}_brief.md", "row_finding_ids": [r["finding_id"] for r in rows],
           "warnings": [f"Source IDs not found: {', '.join(sorted(set(missing)))}"] if missing else []}
    if item.get("origin") == "ADAPTED_FROM":
        res["warnings"].append(f"Adapted from {item.get('adapted_from_record_id')}: needs copyright permission")
    if item.get("type") == "FIGURE_EVIDENCE_MAP" and rows and item.get("origin") != "ADAPTED_FROM":
        props, systems, counts = evidence_map_data(rows)
        labels = {r["proposition_id"]: r["assertion"] for r in rows}
        if draw_evidence_map(props, labels, systems, counts, out_dir / f"{did}.png"):
            res.update(status="BUILT", image=f"{did}.png")
        else:
            res["warnings"].append("matplotlib not installed: evidence map not drawn")
    elif not rows:
        res["status"] = "EMPTY"
    (out_dir / res["brief"]).write_text(figure_brief(item, synthesis, rows), encoding="utf-8")
    return res


# ------------------------------------------------------------------ entry point
def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as fh:   # BOM so Excel reads UTF-8
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def build_all(plan: dict, synthesis: dict, findings: list[dict], corpus: list[dict], out_dir: Path) -> list[dict]:
    """Build every display item in the manuscript plan; returns one summary per item."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    built = []
    for item in plan.get("display_items", []):
        did = item.get("display_id") or ""
        if not re.fullmatch(r"[FT]\d+", did):
            built.append({"display_id": did, "status": "EMPTY", "warnings": ["display_id must look like F1 or T1"]})
            continue
        if did.startswith("T") or item.get("type") in TABLE_TYPES:
            res = build_table(item, synthesis, findings, corpus)
            _write_csv(out_dir / f"{did}.csv", res["columns"], res["rows"])
        else:
            res = build_figure(item, synthesis, findings, corpus, out_dir)
            rows, _ = evidence_rows(item, synthesis, findings, corpus)
            _write_csv(out_dir / f"{did}.csv", ["proposition_id", "finding_id", "role", "record_id", "system",
                                                "finding", "quantities", "disposition"],
                       [[r["proposition_id"], r["finding_id"], r["role"], r["record_id"],
                         _ctx(r["f"], "evidence_system", "species"), _relation(r["f"]), _quantities(r["f"]),
                         r["f"].get("disposition") or ""] for r in rows])
        res["placement_section_id"] = item.get("placement_section_id")
        (out_dir / f"{did}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        built.append(res)
    return built
