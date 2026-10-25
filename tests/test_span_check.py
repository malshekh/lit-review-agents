from litreview.tools import span_check


def test_exact_span_found_despite_whitespace_and_quotes():
    src = "Treatment with   compound X reduced \u201cIL-6\u201d levels by 42% (n = 12)."
    assert span_check.span_found('compound X reduced "IL-6" levels by 42%', src)


def test_figure_and_table_references_ignore_internal_spacing():
    # real case (run 20261025-100039, R0030 F18): span and paper differ only in spacing
    src = "the survival curve of DSF, G, D + G, and Veh did not show the differences ( Figure 8 H). The"
    assert span_check.span_found("did not show the differences ( Figure 8 H ).", src)
    assert span_check.span_found("did not show the differences (Figure 8H).", src)
    assert span_check.span_found("as shown (Fig. 3B-D)", "as shown ( Fig. 3 B - D )")
    assert span_check.span_found("listed in [Table 1]", "listed in [ Table  1 ]")
    assert span_check.span_found("(Supplementary Figure S2B)", "( Supplementary Figure S2 B )")


def test_spacing_rules_do_not_hide_different_references():
    assert not span_check.span_found("(Figure 8H)", "(Figure 8I)")
    assert not span_check.span_found("(Figure 8H)", "(Figure 6H)")
    assert not span_check.span_found("reduced growth (Figure 8A)", "increased growth (Figure 8A)")


def test_fabricated_span_not_found():
    assert not span_check.span_found("compound X abolished IL-6", "compound X reduced IL-6")


def test_numbers_must_appear_in_span():
    span = "IC50 of 3.2 µM in HeLa cells"
    assert span_check.numbers_match(span, [{"raw_value": "3.2"}])
    assert not span_check.numbers_match(span, [{"raw_value": "2.3"}])


def test_ranges_are_not_read_as_negative_numbers():
    # real case (R0061 F1): range recorded without spaces, printed with spaces in the paper
    assert span_check.numbers_in("12.1–56.3") == {"12.1", "56.3"}
    assert span_check.numbers_match("IC 50 values ranged 12.1 – 56.3 nM", [{"raw_value": "12.1–56.3"}])
    assert span_check.numbers_in("a change of -2.5 (95% CI -4.1 to -0.9)") == {"-2.5", "95", "-4.1", "-0.9"}


def test_check_findings_reports_location():
    ext = {"findings": [{"finding_id": "F1", "span": "reduced tumour volume",
                         "span_location": {"section": "Results"}, "quantities": []}]}
    out = span_check.check_findings(ext, {"Results": "Drug A reduced tumour volume.", "Methods": "x"})
    assert out[0]["span_found"] and out[0]["location_matches"]
