from search.boolean_query import parse_boolean_query


def test_parse_boolean_query():
    parsed = parse_boolean_query('"不法行為" 損害 | 賠償 -故意')
    assert parsed.required == ["不法行為"]
    assert parsed.optional_groups == [["損害", "賠償"]]
    assert parsed.excluded == ["故意"]


def test_parse_boolean_query_accepts_or_keyword():
    parsed = parse_boolean_query("損害 OR 賠償")
    assert parsed.optional_groups == [["損害", "賠償"]]


def test_parse_boolean_query_accepts_multiple_or_terms():
    parsed = parse_boolean_query("損害 | 賠償 | 慰謝料")
    assert parsed.optional_groups == [["損害", "賠償", "慰謝料"]]


def test_parse_boolean_query_rejects_invalid_syntax():
    try:
        parse_boolean_query("損害 |")
    except ValueError as exc:
        assert "OR must be followed" in str(exc)
    else:
        raise AssertionError("Expected trailing OR to fail")
