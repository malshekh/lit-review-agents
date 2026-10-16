from litreview.tools import tags


def test_bindings_and_strip():
    text = "Drug A reduced B in mice [@R0001]. ⟦P1⟧ This section turns to humans. ⟦ORG⟧"
    b = tags.bindings(text)
    assert b[0][1] == ["P1"] and b[1][1] == ["ORG"]
    assert "⟦" not in tags.strip_tags(text)


def test_cited_records_multiple():
    assert tags.cited_records("x [@R1; @R2] y [@R3]") == ["R1", "R2", "R3"]
