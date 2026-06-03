from typing import Any

from search.service import SearchParams, SearchService


class DummyBackend:
    def __init__(self) -> None:
        self.last_body: dict[str, Any] = {}
        self.index = "laws"

    def ensure_index(self) -> None:
        pass

    def search(self, body, size, from_):
        self.last_body = body
        return {"hits": {"hits": [], "total": {"value": 0}}, "took": 1}


def test_build_literal_query_uses_match_phrase(monkeypatch):
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="損害賠償", mode="literal", filters={}, size=20, page=1)
    service.search(params)
    content = backend.last_body["query"]["bool"]["must"][0]["match_phrase"]["content"]
    assert content["query"] == "損害賠償"


def test_build_literal_citation_only_query_uses_citation_filters():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="民法 709条", mode="literal", filters={}, size=20, page=1)
    service.search(params)
    query = backend.last_body["query"]["bool"]
    assert query["must"] == [{"match_all": {}}]
    assert {"term": {"law_name": "民法"}} in query["filter"]
    assert {"term": {"article_no": "709"}} in query["filter"]


def test_auto_citation_with_residual_terms_keeps_content_phrase():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="民法 709条 損害", mode="auto", filters={}, size=20, page=1)
    service.search(params)
    query = backend.last_body["query"]["bool"]
    content = query["must"][0]["match_phrase"]["content"]

    assert content["query"] == "損害"
    assert {"term": {"law_name": "民法"}} in query["filter"]
    assert {"term": {"article_no": "709"}} in query["filter"]


def test_auto_citation_with_prefix_residual_terms_keeps_content_phrase():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="損害 民法 709条", mode="auto", filters={}, size=20, page=1)
    service.search(params)
    query = backend.last_body["query"]["bool"]
    content = query["must"][0]["match_phrase"]["content"]

    assert content["query"] == "損害"
    assert {"term": {"law_name": "民法"}} in query["filter"]
    assert {"term": {"article_no": "709"}} in query["filter"]


def test_citation_prefix_should_is_boost_only():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="民法 709条", mode="auto", filters={}, size=20, page=1)
    service.search(params)
    query = backend.last_body["query"]["bool"]

    assert "should" in query
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
    assert query["should"] == [{"match_phrase_prefix": {"law_name.prefix": "民法"}}]
    assert "minimum_should_match" not in query


def test_convert_hit_includes_article_metadata():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    hit = {
        "_id": "doc1",
        "_source": {
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
