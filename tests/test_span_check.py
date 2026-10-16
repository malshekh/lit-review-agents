from litreview.tools import span_check


def test_exact_span_found_despite_whitespace_and_quotes():
    src = "Treatment with   compound X reduced \u201cIL-6\u201d levels by 42% (n = 12)."
    assert span_check.span_found('compound X reduced "IL-6" levels by 42%', src)


def test_fabricated_span_not_found():
    assert not span_check.span_found("compound X abolished IL-6", "compound X reduced IL-6")


def test_numbers_must_appear_in_span():
    span = "IC50 of 3.2 µM in HeLa cells"
    assert span_check.numbers_match(span, [{"raw_value": "3.2"}])
    assert not span_check.numbers_match(span, [{"raw_value": "2.3"}])


def test_check_findings_reports_location():
    ext = {"findings": [{"finding_id": "F1", "span": "reduced tumour volume",
                         "span_location": {"section": "Results"}, "quantities": []}]}
    out = span_check.check_findings(ext, {"Results": "Drug A reduced tumour volume.", "Methods": "x"})
    assert out[0]["span_found"] and out[0]["location_matches"]
