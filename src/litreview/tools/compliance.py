"""Journal compliance checks (Scientific Reviews), read from config/journal_scirev.yaml."""
from __future__ import annotations

import re

from .. import config
from .tags import CITE_RE, DISPLAY_RE, strip_tags

_WORD_RE = re.compile(r"[A-Za-z0-9\u00C0-\u024F\u0370-\u03FF]+(?:[-'][A-Za-z0-9]+)*")


def word_count(text: str) -> int:
    text = strip_tags(text)
    text = CITE_RE.sub("", text)
    text = DISPLAY_RE.sub("", text)
    text = re.sub(r"^#+\s.*$", "", text, flags=re.M)  # headings are not counted as body text
    return len(_WORD_RE.findall(text))


def check(manuscript: dict) -> dict:
    """manuscript: {title, abstract, keywords, sections:[{text_markdown}], figure_legends:[...],
    display_items:[...], references:[...]}"""
    lim = config.load("journal_scirev")["limits"]
    body = "\n\n".join(s.get("text_markdown", "") for s in manuscript.get("sections", []))
    main_words = word_count(body)
    n_refs = len(set(manuscript.get("references", [])))
    issues: list[dict] = []

    def add(rule: str, ok: bool, detail: str) -> None:
        issues.append({"rule": rule, "pass": ok, "detail": detail})

    title_words = word_count(manuscript.get("title", ""))
    add("title_max_words", title_words <= lim["title_max_words"], f"{title_words}/{lim['title_max_words']} words")
    add("title_single_sentence", manuscript.get("title", "").count(". ") == 0, "one sentence")

    abstract = manuscript.get("abstract", "")
    aw = word_count(abstract)
    add("abstract_max_words", aw <= lim["abstract_max_words"], f"{aw}/{lim['abstract_max_words']} words")
    add("abstract_no_references", not CITE_RE.search(abstract) and not re.search(r"\[\d+", abstract),
        "no citations in abstract")
    add("abstract_unstructured", not re.search(r"^\s*(#|\*\*?\w+:)", abstract, flags=re.M), "no headings")

    kw = manuscript.get("keywords", [])
    add("keywords_max", len(kw) <= lim["keywords_max"], f"{len(kw)}/{lim['keywords_max']}")

    add("main_text_max_words", main_words <= lim["main_text_max_words"],
        f"{main_words}/{lim['main_text_max_words']} words")

    n_disp = len(manuscript.get("display_items", []))
    disp_lim = (lim["display_items_max_if_short"] if main_words <= lim["short_text_threshold_words"]
                else lim["display_items_max"])
    add("display_items_max", n_disp <= disp_lim, f"{n_disp}/{disp_lim}")

    for leg in manuscript.get("figure_legends", []):
        lw = word_count(leg.get("legend", ""))
        add(f"legend_{leg.get('display_id')}", lw <= lim["figure_legend_max_words"],
            f"{lw}/{lim['figure_legend_max_words']} words")

    target = lim["references_per_1000_words"] * main_words / 1000
    add("references_ratio", n_refs >= 0.6 * target, f"{n_refs} refs; target about {target:.0f} (advisory)")

    add("no_footnotes", not re.search(r"\[\^[^\]]+\]", body), "no Markdown footnotes")
    add("no_gap_markers", "[[GAP:" not in body, "no unresolved plan gaps")

    return {"main_text_words": main_words, "references": n_refs,
            "all_pass": all(i["pass"] for i in issues if i["rule"] != "references_ratio"),
            "checks": issues}
