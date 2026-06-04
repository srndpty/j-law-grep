from typing import Any

import pytest

from search.service import (
    MAX_LONG_LITERAL_WILDCARD_LENGTH,
    MAX_RESULT_WINDOW,
    SearchParams,
    SearchService,
)


class DummyBackend:
    def __init__(self) -> None:
        self.last_body: dict[str, Any] = {}
        self.index = "laws"

    def ensure_index(self) -> None:
        pass

    def search(self, body, size, from_):
        self.last_body = body
        return {"hits": {"hits": [], "total": {"value": 0}}, "took": 1}

    def law_document(self, law_id, article=None):
        if article:
            assert article == "10"
        return {
            "hits": {
                "hits": [
                    {
                        "_id": "minpo-10",
                        "_source": {
                            "law_id": law_id,
                            "law_name": "民法",
                            "article_no": "10",
                            "paragraph_no": None,
                            "item_no": None,
                            "content_plain": "第十条の本文",
                            "blocks": [],
                            "url": "/l/minpo/a/10",
                            "path": "民法/10",
                        },
                    },
                    {
                        "_id": "minpo-2",
                        "_source": {
                            "law_id": law_id,
                            "law_name": "民法",
                            "article_no": "2",
                            "paragraph_no": None,
                            "item_no": None,
                            "content_plain": "第二条の本文",
                            "blocks": [],
                            "url": "/l/minpo/a/2",
                            "path": "民法/2",
                        },
                    },
                ]
            }
        }


def test_build_literal_query_uses_match_phrase(monkeypatch):
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="損害賠償", mode="literal", filters={}, size=20, page=1)
    service.search(params)
    content = backend.last_body["query"]["bool"]["must"][0]["match_phrase"]["content"]
    assert content["query"] == "損害賠償"


def test_build_keyword_query_uses_multi_match():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="不法行為 損害", mode="keyword", filters={}, size=20, page=1)
    service.search(params)
    multi_match = backend.last_body["query"]["bool"]["must"][0]["multi_match"]
    assert multi_match["query"] == "不法行為 損害"
    assert multi_match["operator"] == "and"
    assert "content.keywordish" in multi_match["fields"]


def test_blank_build_query_uses_match_none():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    body = service.build_query(SearchParams(q="", mode="keyword", filters={}, size=20, page=1))
    assert body["query"] == {"match_none": {}}


def test_build_long_literal_query_uses_long_content_field():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(
        q="これは十五文字を超える長い完全一致検索です",
        mode="literal",
        filters={},
        size=20,
        page=1,
    )
    service.search(params)
    literal_clause = backend.last_body["query"]["bool"]["must"][0]["bool"]

    assert literal_clause["minimum_should_match"] == 1
    assert literal_clause["should"][0]["match_phrase"]["content"]["query"] == params.q
    assert literal_clause["should"][1]["wildcard"]["content_long"]["value"] == f"*{params.q}*"


def test_long_literal_wildcard_escapes_user_wildcards():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(
        q="長い検索語*を?含むテキストです", mode="literal", filters={}, size=20, page=1
    )

    service.search(params)

    wildcard = backend.last_body["query"]["bool"]["must"][0]["bool"]["should"][1]["wildcard"]
    assert wildcard["content_long"]["value"] == "*長い検索語\\*を\\?含むテキストです*"


def test_very_long_literal_skips_content_long_wildcard():
    # A leading/trailing wildcard on content_long is a full substring scan; past
    # MAX_LONG_LITERAL_WILDCARD_LENGTH we drop it and rely on the content phrase
    # query only, to keep tail latency bounded on a full corpus.
    backend = DummyBackend()
    service = SearchService(backend=backend)
    term = "あ" * (MAX_LONG_LITERAL_WILDCARD_LENGTH + 1)
    params = SearchParams(q=term, mode="literal", filters={}, size=20, page=1)

    service.search(params)

    must = backend.last_body["query"]["bool"]["must"][0]
    assert must["match_phrase"]["content"]["query"] == term
    should = backend.last_body["query"]["bool"].get("should", [])
    assert all("content_long" not in clause.get("wildcard", {}) for clause in should)


def test_branch_number_citation_falls_into_article_filter():
    # 枝番 citation (e.g. 民事訴訟法3条の2) must normalize to article_no "3の2"
    # and land in the term filter so the citation actually constrains results.
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="民事訴訟法3条の2", mode="auto", filters={}, size=20, page=1)

    service.search(params)

    query = backend.last_body["query"]["bool"]
    assert service._law_name_filter("民事訴訟法") in query["filter"]
    assert {"term": {"article_no": "3の2"}} in query["filter"]


def test_build_literal_citation_only_query_uses_citation_filters():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="民法 709条", mode="literal", filters={}, size=20, page=1)
    service.search(params)
    query = backend.last_body["query"]["bool"]
    assert query["must"] == [{"match_all": {}}]
    assert service._law_name_filter("民法") in query["filter"]
    assert {"term": {"article_no": "709"}} in query["filter"]


def test_auto_citation_with_residual_terms_keeps_content_phrase():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="民法 709条 損害", mode="auto", filters={}, size=20, page=1)
    service.search(params)
    query = backend.last_body["query"]["bool"]
    content = query["must"][0]["match_phrase"]["content"]

    assert content["query"] == "損害"
    assert service._law_name_filter("民法") in query["filter"]
    assert {"term": {"article_no": "709"}} in query["filter"]


def test_auto_citation_with_prefix_residual_terms_keeps_content_phrase():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="損害 民法 709条", mode="auto", filters={}, size=20, page=1)
    service.search(params)
    query = backend.last_body["query"]["bool"]
    content = query["must"][0]["match_phrase"]["content"]

    assert content["query"] == "損害"
    assert service._law_name_filter("民法") in query["filter"]
    assert {"term": {"article_no": "709"}} in query["filter"]


def test_citation_prefix_should_is_boost_only():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="民法 709条", mode="auto", filters={}, size=20, page=1)
    service.search(params)
    query = backend.last_body["query"]["bool"]

    assert "should" in query
    assert "minimum_should_match" not in query


def test_ranking_boosts_are_should_only():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="民法 709条 損害", mode="auto", filters={}, size=20, page=1)
    service.search(params)
    query = backend.last_body["query"]["bool"]

    assert {"term": {"citation_key": {"value": "民法 709条", "boost": 12.0}}} in query["should"]
    assert any("heading" in clause.get("match_phrase", {}) for clause in query["should"])
    assert "minimum_should_match" not in query


def test_citation_mode_rejects_non_citation_query():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="損害賠償", mode="citation", filters={}, size=20, page=1)

    try:
        service.build_query(params)
    except ValueError as exc:
        assert "article number" in str(exc)
    else:
        raise AssertionError("Expected citation mode without article number to fail")


def test_search_response_includes_query_and_index_metadata():
    backend = DummyBackend()
    backend.index = "jlaw-current"
    service = SearchService(backend=backend)
    params = SearchParams(q="民法 709条", mode="auto", filters={}, size=20, page=1)
    result = service.search(params)
    assert result["query"]["effective_mode"] == "citation"
    assert result["query"]["parsed"]["law_name"] == "民法"
    assert result["index"]["name"] == "jlaw-current"


def test_search_response_includes_debug_ranking_signals_when_debug(monkeypatch):
    monkeypatch.setattr("search.service.settings.DEBUG", True)
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="民法 709条 損害", mode="auto", filters={}, size=20, page=1)

    result = service.search(params)

    assert result["debug"]["ranking_signals"]["citation_exact"] is True
    assert result["debug"]["ranking_signals"]["law_name"] is True


def test_law_document_returns_sections_in_natural_article_order():
    service = SearchService(backend=DummyBackend())

    document = service.law_document("minpo")

    assert document is not None
    assert document["law_name"] == "民法"
    assert [section["article_no"] for section in document["sections"]] == ["2", "10"]


def test_law_document_passes_article_filter_to_backend():
    service = SearchService(backend=DummyBackend())

    document = service.law_document("minpo", article="10")

    assert document is not None


def test_law_document_context_filters_after_fetching_sections():
    service = SearchService(backend=DummyBackend())

    document = service.law_document("minpo", article="10", context=0)

    assert document is not None
    assert [section["article_no"] for section in document["sections"]] == ["10"]


def test_build_boolean_query_uses_required_optional_and_excluded_terms():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(
        q='"不法行為" 損害 | 賠償 -故意', mode="boolean", filters={}, size=20, page=1
    )
    service.search(params)
    query = backend.last_body["query"]["bool"]

    must_terms = [
        clause["match_phrase"]["content"]["query"]
        for clause in query["must"]
        if "match_phrase" in clause
    ]
    must_not_terms = [clause["match_phrase"]["content"]["query"] for clause in query["must_not"]]
    optional_terms = [
        clause["match_phrase"]["content"]["query"] for clause in query["must"][1]["bool"]["should"]
    ]
    assert must_terms == ["不法行為"]
    assert optional_terms == ["損害", "賠償"]
    assert must_not_terms == ["故意"]
    assert query["must"][1]["bool"]["minimum_should_match"] == 1
    assert "minimum_should_match" not in query


def test_boolean_or_requirements_are_not_satisfied_by_boosts():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="損害 | 賠償", mode="boolean", filters={"law": "民法"}, size=20, page=1)
    service.search(params)
    query = backend.last_body["query"]["bool"]

    assert query["must"] == [
        {
            "bool": {
                "should": [
                    service._content_phrase_clause("損害"),
                    service._content_phrase_clause("賠償"),
                ],
                "minimum_should_match": 1,
            }
        }
    ]
    assert query["should"] == service._law_name_boosts("民法")
    assert "minimum_should_match" not in query


def test_law_filter_matches_name_or_alias():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="損害", mode="literal", filters={"law": "民法典"}, size=20, page=1)
    service.search(params)
    query = backend.last_body["query"]["bool"]

    alias_filter = service._law_name_filter("民法典")
    assert alias_filter in query["filter"]
    should = alias_filter["bool"]["should"]
    assert {"term": {"law_name": "民法典"}} in should
    assert {"term": {"law_aliases": "民法典"}} in should


def test_convert_hit_includes_article_metadata():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    hit = {
        "_id": "doc1",
        "_source": {
            "law_id": "minpo",
            "law_name": "民法",
            "article_no": "709",
            "paragraph_no": None,
            "item_no": None,
            "path": "",
            "line": 3,
            "content": "不法行為による損害の賠償",
            "url": "/l/minpo/a/709",
            "blocks": [],
        },
        "highlight": {"content": []},
    }
    result = service._convert_hit(hit, query="損害")
    assert result["law_name"] == "民法"
    assert result["law_id"] == "minpo"
    assert result["article_no"] == "709"
    assert result["path"] == "民法/709"
    assert result["snippet"] == "不法行為による損害の賠償"
    assert result["snippet_text"] == "不法行為による損害の賠償"
    assert result["highlights"] == [{"start": 7, "end": 9}]


def test_convert_hit_turns_opensearch_mark_tags_into_ranges():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    hit = {
        "_id": "doc-marked",
        "_source": {
            "law_name": "民法",
            "article_no": "709",
            "paragraph_no": None,
            "item_no": None,
            "path": "民法/709",
            "line": 0,
            "content": "fallback",
            "url": "/l/minpo/a/709",
            "blocks": [],
        },
        "highlight": {"content": ["不法行為による<mark>損害</mark>の賠償"]},
    }
    result = service._convert_hit(hit, query="損害")
    assert result["snippet"] == "不法行為による損害の賠償"
    assert result["highlights"] == [{"start": 7, "end": 9}]


def test_convert_hit_derives_article_from_url_when_missing():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    hit = {
        "_id": "doc2",
        "_source": {
            "law_name": "重要経済安保情報の保護及び活用に関する法律",
            "article_no": "",
            "paragraph_no": None,
            "item_no": None,
            "path": "",
            "line": 0,
            "content": "dummy",
            "url": "/l/123/a/23/4",
            "blocks": [],
        },
        "highlight": {"content": []},
    }
    result = service._convert_hit(hit, query="")
    assert result["article_no"] == "23"
    assert result["paragraph_no"] == "4"


def test_validate_pagination_allows_window_boundary():
    # from + size exactly at the window must pass.
    SearchService.validate_pagination(page=MAX_RESULT_WINDOW // 20, size=20)


def test_validate_pagination_rejects_deep_paging():
    with pytest.raises(ValueError, match=f"beyond {MAX_RESULT_WINDOW}"):
        SearchService.validate_pagination(page=999999, size=20)


def test_validate_pagination_rejects_window_overflow_by_one():
    with pytest.raises(ValueError):
        SearchService.validate_pagination(page=(MAX_RESULT_WINDOW // 20) + 1, size=20)


def test_regex_query_rejects_expensive_patterns():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q=".*損害.*賠償", mode="regex", filters={}, size=20, page=1)
    try:
        service.build_query(params)
    except ValueError as exc:
        assert "too broad" in str(exc)
    else:
        raise AssertionError("Expected expensive regex to be rejected")
