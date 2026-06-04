import xml.etree.ElementTree as ET
from pathlib import Path

from indexer.egov_importer import (
    collect_structural_warnings,
    normalize_article_no,
    parse_law,
    parse_law_tree,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "egov"


def _law(name: str) -> dict:
    return parse_law(FIXTURES / name)


def _article_map(law: dict) -> dict[str, dict]:
    return {article["article_no"]: article for article in law["articles"]}


def test_normalize_article_no_handles_branch_and_fullwidth():
    assert normalize_article_no("709") == "709"
    assert normalize_article_no("2_2") == "2の2"
    assert normalize_article_no("１０") == "10"
    assert normalize_article_no(None) == ""


def test_branch_article_number_comes_from_num_attribute():
    law = _law("branch_article.xml")
    articles = _article_map(law)
    assert "1" in articles
    assert "2の2" in articles  # 第2条の2, previously lost as empty article_no
    assert law["law_name"] == "テスト法"
    assert law["law_id"] == "平成元年法律第一号"


def test_nested_sentence_text_is_not_dropped():
    law = _law("branch_article.xml")
    article = _article_map(law)["1"]
    body = article["paragraphs"][0]["items"][0]["text"]
    # Ruby base text must survive itertext extraction.
    assert "試験" in body
    assert "のために定める" in body


def test_items_are_preserved():
    law = _law("branch_article.xml")
    items = _article_map(law)["1"]["paragraphs"][0]["items"]
    texts = [item["text"] for item in items]
    assert any("第一号の内容" in text for text in texts)
    assert any("イ号の内容" in text for text in texts)


def test_converted_appendix_nodes_do_not_emit_structural_warnings():
    root = ET.parse(FIXTURES / "appendix.xml").getroot()
    law = parse_law_tree(root, "appendix")
    codes = {w.code for w in collect_structural_warnings(root, law["law_id"])}
    assert codes == set()
    # The main provision article is still converted.
    assert "1" in _article_map(law)


def test_appendix_table_and_suppl_paragraphs_are_searchable_pseudo_articles():
    law = _law("appendix.xml")
    articles = _article_map(law)
    assert "附則-1" in articles
    assert "別表1" in articles
    assert articles["附則-1"]["heading"] == "附則"
    assert articles["別表1"]["paragraphs"][0]["items"][0]["text"]


def test_clean_fixture_has_no_structural_warnings():
    root = ET.parse(FIXTURES / "branch_article.xml").getroot()
    law = parse_law_tree(root, "branch_article")
    assert collect_structural_warnings(root, law["law_id"]) == []
