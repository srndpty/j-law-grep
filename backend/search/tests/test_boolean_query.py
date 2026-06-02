from search.boolean_query import parse_boolean_query


def test_parse_boolean_query():
    parsed = parse_boolean_query('"不法行為" 損害 | 賠償 -故意')
    assert parsed.required == ["不法行為"]
    assert parsed.optional_groups == [["損害", "賠償"]]
    assert parsed.excluded == ["故意"]
