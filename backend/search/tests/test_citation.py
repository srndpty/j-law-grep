from search.citation import citation_key, parse_citation, parse_citation_query


def test_parse_basic_citation():
    result = parse_citation("民法 709条")
    assert result.law_name == "民法"
    assert result.article_no == "709"
    assert result.paragraph_no is None
    assert result.item_no is None


def test_parse_with_paragraph_item():
    result = parse_citation("民法第95条1項2号")
    assert result.law_name == "民法"
    assert result.article_no == "95"
    assert result.paragraph_no == 1
    assert result.item_no == 2


def test_citation_key():
    key = citation_key(parse_citation("民法 95条 1項 1号"))
    assert key == "民法 95条 1項 1号"


def test_parse_citation_query_keeps_prefix_residual_terms():
    result = parse_citation_query("損害 民法 709条")
    assert result.citation.law_name == "民法"
    assert result.citation.article_no == "709"
    assert result.residual_query == "損害"


def test_parse_citation_query_does_not_break_spaced_law_name():
    result = parse_citation_query("国家 賠償 法 1条")
    assert result.citation.law_name == "国家賠償法"
    assert result.citation.article_no == "1"
    assert result.residual_query == ""
