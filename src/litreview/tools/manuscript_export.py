"""Render the final manuscript to Markdown and Word (.docx) from one document model.

The orchestrator builds the model (citations already numbered, tags stripped) and both renderers
read it, so the two files always carry the same text. Order follows the journal's back-matter
order (config/journal_scirev.yaml): References ... Figure legends, Tables.

Document model:
  {"title": str, "abstract": str, "keywords": [str],
   "sections": [{"heading": str, "level": 1|2|3, "text": markdown}],
   "references": [markdown], "back_matter": [(heading, text)],
   "figures": [{"display_id": "F1", "legend": str, "image": Path|None, "brief": str|None}],
   "tables":  [{"display_id": "T1", "caption": str, "columns": [str], "rows": [[str]], "notes": [str]}]}
"""
from __future__ import annotations

import re
from pathlib import Path

INLINE_RE = re.compile(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)")
LIST_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")


def _num(display_id: str) -> str:
    return display_id[1:]


# ------------------------------------------------------------------ Markdown
def _md_cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(doc: dict, image_dir: str = "display_items") -> str:
    parts = [f"# {doc['title']}", "## Abstract", doc["abstract"],
             "**Keywords:** " + "; ".join(doc.get("keywords", []))]
    for s in doc["sections"]:
        parts.append(f"{'#' * (s.get('level', 1) + 1)} {s['heading']}\n\n{s['text']}")
    parts += ["## References", "\n".join(doc["references"])]
    for heading, text in doc.get("back_matter", []):
        parts += [f"## {heading}", text]
    legends = []
    for f in doc.get("figures", []):
        entry = f"**Figure {_num(f['display_id'])}.** {f['legend']}"
        if f.get("image"):
            entry = f"![Figure {_num(f['display_id'])}]({image_dir}/{Path(f['image']).name})\n\n" + entry
        elif f.get("brief"):
            entry += f"\n\n*[Figure to be drawn: see {image_dir}/{f['brief']}]*"
        legends.append(entry)
    parts += ["## Figure legends", "\n\n".join(legends)]
    if doc.get("tables"):
        tables = []
        for t in doc["tables"]:
            block = [f"**Table {_num(t['display_id'])}.** {t['caption']}", ""]
            if t["rows"]:
                block += ["| " + " | ".join(_md_cell(c) for c in t["columns"]) + " |",
                          "|" + "---|" * len(t["columns"])]
                block += ["| " + " | ".join(_md_cell(c) for c in row) + " |" for row in t["rows"]]
            block += [f"*{n}*" for n in t.get("notes", [])]
            tables.append("\n".join(block))
        parts += ["## Tables", "\n\n".join(tables)]
    return "\n\n".join(parts)


# ------------------------------------------------------------------ Word
def _runs(paragraph, text: str, size=None, bold=False):
    """Add text with **bold** and *italic* Markdown converted to Word runs."""
    for piece in INLINE_RE.split(text or ""):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**") and len(piece) > 4:
            run, run_bold, italic = piece[2:-2], True, False
        elif piece.startswith("*") and piece.endswith("*") and len(piece) > 2:
            run, run_bold, italic = piece[1:-1], bold, True
        else:
            run, run_bold, italic = piece, bold, False
        r = paragraph.add_run(run)
        r.bold, r.italic = run_bold or None, italic or None
        if size:
            r.font.size = size


def _markdown_blocks(document, text: str, base_level: int) -> None:
    """Paragraphs, sub-headings (#) and bullet/numbered lists from a section's Markdown."""
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        head = re.match(r"^(#+)\s+(.*)$", lines[0])
        if head and len(lines) == 1:
            document.add_heading(head.group(2).strip(), level=min(base_level + len(head.group(1)) - 1, 4))
            continue
        if all(LIST_RE.match(ln) for ln in lines):
            style = "List Number" if re.match(r"^\s*\d+\.", lines[0]) else "List Bullet"
            for ln in lines:
                _runs(document.add_paragraph(style=style), LIST_RE.sub("", ln, count=1))
            continue
        _runs(document.add_paragraph(), " ".join(ln.strip() for ln in lines))


def render_docx(doc: dict, path: Path) -> Path:
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.text import WD_BREAK
    from docx.shared import Inches, Pt

    d = Document()
    normal = d.styles["Normal"]
    normal.font.name, normal.font.size = "Arial", Pt(11)
    normal.paragraph_format.line_spacing = 1.5
    for name in ("Title", "Heading 1", "Heading 2", "Heading 3", "Heading 4"):
        d.styles[name].font.name = "Arial"

    d.add_heading(doc["title"], level=0)
    d.add_heading("Abstract", level=1)
    _runs(d.add_paragraph(), doc["abstract"])
    kw = d.add_paragraph()
    _runs(kw, "**Keywords:** " + "; ".join(doc.get("keywords", [])))

    for s in doc["sections"]:
        level = min(int(s.get("level") or 1), 3)
        d.add_heading(s["heading"], level=level)
        _markdown_blocks(d, s["text"], level + 1)

    d.add_heading("References", level=1)
    for ref in doc["references"]:
        p = d.add_paragraph()
        p.paragraph_format.line_spacing = 1.0
        _runs(p, ref, size=Pt(10))

    for heading, text in doc.get("back_matter", []):
        d.add_heading(heading, level=1)
        _markdown_blocks(d, text, 2)

    d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    d.add_heading("Figure legends", level=1)
    for f in doc.get("figures", []):
        if f.get("image") and Path(f["image"]).exists():
            d.add_picture(str(f["image"]), width=Inches(6.3))
        legend = d.add_paragraph()
        _runs(legend, f"**Figure {_num(f['display_id'])}.** {f['legend']}")
        if not f.get("image") and f.get("brief"):
            _runs(d.add_paragraph(), f"*[Figure to be drawn: see display_items/{f['brief']}]*")

    for t in doc.get("tables", []):
        if len(t["columns"]) > 5 and d.sections[-1].orientation != WD_ORIENT.LANDSCAPE:
            sec = d.add_section()   # wide tables get landscape pages; a new section starts a new page
            sec.orientation = WD_ORIENT.LANDSCAPE
            sec.page_width, sec.page_height = sec.page_height, sec.page_width
        else:
            d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        _runs(d.add_paragraph(), f"**Table {_num(t['display_id'])}.** {t['caption']}")
        if t["rows"]:
            table = d.add_table(rows=1, cols=len(t["columns"]))
            table.style = "Table Grid"
            for cell, name in zip(table.rows[0].cells, t["columns"]):
                _runs(cell.paragraphs[0], name, size=Pt(8), bold=True)
            for row in t["rows"]:
                for cell, value in zip(table.add_row().cells, row):
                    cell.paragraphs[0].paragraph_format.line_spacing = 1.0
                    _runs(cell.paragraphs[0], value, size=Pt(8))
        for note in t.get("notes", []):
            _runs(d.add_paragraph(), f"*{note}*", size=Pt(9))

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    d.save(path)
    return path
