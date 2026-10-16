from litreview.tools import compliance


def test_word_count_ignores_tags_and_citations():
    assert compliance.word_count("Drug A reduced B [@R0001]. ⟦P1⟧") == 4


def test_check_flags_long_title_and_too_many_keywords():
    m = {"title": " ".join(["word"] * 25), "abstract": "Short abstract.", "keywords": list("abcdefg"),
         "sections": [{"text_markdown": "Body text. ⟦P1⟧"}], "references": [], "display_items": []}
    res = {c["rule"]: c["pass"] for c in compliance.check(m)["checks"]}
    assert res["title_max_words"] is False
    assert res["keywords_max"] is False
    assert res["abstract_max_words"] is True


def test_citation_in_abstract_fails():
    m = {"title": "A title.", "abstract": "Text [@R1].", "keywords": [], "sections": [], "references": []}
    res = {c["rule"]: c["pass"] for c in compliance.check(m)["checks"]}
    assert res["abstract_no_references"] is False
