import json
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

    def search(self, body, size, from_, ignore_unavailable=False):
        self.last_body = body
        self.last_ignore_unavailable = ignore_unavailable
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
                            "caption": "（見出し）",
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
                    {
                        "_id": "minpo-suppl-1",
                        "_source": {
                            "law_id": law_id,
                            "law_name": "民法",
                            "article_no": "附則1-1",
                            "paragraph_no": None,
                            "item_no": None,
                            "content_plain": "附則第一条の本文",
                            "blocks": [],
                            "url": "/l/minpo/a/%E9%99%84%E5%89%871-1",
                            "path": "民法/附則1-1",
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


def test_keyword_citation_only_query_uses_citation_filters():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="民法 709条", mode="keyword", filters={}, size=20, page=1)

    result = service.search(params)

    query = backend.last_body["query"]["bool"]
    assert query["must"] == [{"match_all": {}}]
    assert service._law_name_filter("民法") in query["filter"]
    assert {"term": {"article_no": "709"}} in query["filter"]
    assert result["query"]["effective_mode"] == "citation"


def test_blank_build_query_uses_match_none():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    body = service.build_query(SearchParams(q="", mode="keyword", filters={}, size=20, page=1))
    assert body["query"] == {"match_none": {}}


def test_blank_search_returns_empty_hits_with_metadata():
    backend = DummyBackend()
    backend.index = "jlaw-current"
    service = SearchService(backend=backend)

    result = service.search(SearchParams(q="  ", mode="keyword", filters={}, size=20, page=1))

    assert result["hits"] == []
    assert result["total"] == 0
    assert result["query"]["raw"] == "  "
    assert result["query"]["effective_mode"] == "keyword"
    assert result["index"]["name"] == "jlaw-current"


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
    assert any("caption" in clause.get("match_phrase", {}) for clause in query["should"])
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
    assert [section["article_no"] for section in document["sections"]] == ["2", "10", "附則1-1"]


def test_law_document_passes_article_filter_to_backend():
    service = SearchService(backend=DummyBackend())

    document = service.law_document("minpo", article="10")

    assert document is not None


def test_law_document_context_filters_after_fetching_sections():
    service = SearchService(backend=DummyBackend())

    document = service.law_document("minpo", article="10", context=0)

    assert document is not None
    assert [section["article_no"] for section in document["sections"]] == ["10"]


def test_law_document_context_missing_article_returns_none():
    service = SearchService(backend=DummyBackend())

    document = service.law_document("minpo", article="999", context=0)

    assert document is None


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


def test_diet_filters_apply_metadata_filters():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(
        q="予算",
        mode="literal",
        filters={
            "house": "衆議院",
            "meeting": "予算委員会",
            "speaker": "山田太郎",
            "date_from": "2025-06-09",
            "date_to": "2026-06-09",
        },
        size=20,
        page=1,
        source="diet",
    )

    filters = service.build_query(params)["query"]["bool"]["filter"]
    assert {"term": {"source_type": "diet"}} in filters
    assert {"term": {"house": "衆議院"}} in filters
    assert service._keyword_or_prefix_filter("meeting_name", "予算委員会") in filters
    assert service._speaker_filter("山田太郎") in filters
    assert {"range": {"date": {"gte": "2025-06-09", "lte": "2026-06-09"}}} in filters


def test_speaker_filter_uses_keyword_prefix_not_ngram_prefix():
    service = SearchService(backend=DummyBackend())

    speaker_filter = service._speaker_filter("青柳仁士")

    assert speaker_filter == {
        "bool": {
            "should": [
                {
                    "bool": {
                        "should": [
                            {"term": {"speaker": "青柳仁士"}},
                            {"prefix": {"speaker": "青柳仁士"}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                {
                    "bool": {
                        "should": [
                            {"term": {"speaker_yomi": "青柳仁士"}},
                            {"prefix": {"speaker_yomi": "青柳仁士"}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
            ],
            "minimum_should_match": 1,
        }
    }


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


def test_convert_hit_includes_diet_metadata():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    hit = {
        "_id": "diet1",
        "_source": {
            "source_type": "diet",
            "law_id": "121205254X01220231213",
            "law_name": "衆議院 本会議 第212回 第12号",
            "article_no": "1",
            "paragraph_no": None,
            "item_no": None,
            "path": "国会会議録/衆議院/本会議/第212回/第12号/発言1",
            "line": 0,
            "content": "これより会議を開きます。",
            "url": "https://kokkai.ndl.go.jp/txt/121205254X01220231213/1",
            "blocks": [],
            "house": "衆議院",
            "meeting_name": "本会議",
            "date": "2023-12-13",
            "speaker": "額賀福志郎",
            "speaker_group": "自由民主党",
            "speaker_position": "議長",
            "speaker_role": "",
        },
        "highlight": {"content": []},
    }

    result = service._convert_hit(hit, query="会議")

    assert result["source_type"] == "diet"
    assert result["house"] == "衆議院"
    assert result["meeting_name"] == "本会議"
    assert result["date"] == "2023-12-13"
    assert result["speaker"] == "額賀福志郎"
    assert result["speaker_group"] == "自由民主党"
    assert result["speaker_position"] == "議長"


def test_convert_law_section_includes_caption():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    result = service._convert_law_section(
        {
            "_id": "doc-caption",
            "_source": {
                "law_id": "test",
                "law_name": "テスト法",
                "article_no": "1",
                "paragraph_no": 1,
                "item_no": None,
                "caption": "（目的）",
                "heading": "第一条",
                "content_plain": "本文。",
                "blocks": [],
                "url": "/l/test/a/1/1",
                "path": "テスト法/1",
            },
        }
    )

    assert result["caption"] == "（目的）"


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


def test_convert_hit_uses_caption_highlight_when_content_is_not_highlighted():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    hit = {
        "_id": "doc-caption-hit",
        "_source": {
            "law_name": "民法",
            "article_no": "1",
            "paragraph_no": None,
            "item_no": None,
            "path": "民法/1",
            "line": 0,
            "caption": "（基本原則）",
            "content": "本文",
            "url": "/l/minpo/a/1",
            "blocks": [],
        },
        "highlight": {"caption": ["（<mark>基本</mark>原則）"]},
    }

    result = service._convert_hit(hit, query="基本")

    assert result["snippet"] == "（基本原則）"
    assert result["highlights"] == [{"start": 1, "end": 3}]


def test_convert_hit_prefers_marked_caption_over_content_no_match_fallback():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    hit = {
        "_id": "doc-caption-over-content",
        "_source": {
            "law_name": "民法",
            "article_no": "1",
            "paragraph_no": None,
            "item_no": None,
            "path": "民法/1",
            "line": 0,
            "caption": "（基本原則）",
            "content": "本文の先頭だけがfallbackとして返る。",
            "url": "/l/minpo/a/1",
            "blocks": [],
        },
        "highlight": {
            "content": ["本文の先頭だけがfallbackとして返る。"],
            "caption": ["（<mark>基本</mark>原則）"],
        },
    }

    result = service._convert_hit(hit, query="基本")

    assert result["snippet"] == "（基本原則）"
    assert result["highlights"] == [{"start": 1, "end": 3}]


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


def test_law_source_adds_source_type_filter():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="損害", mode="literal", filters={}, size=20, page=1, source="law")

    filters = service.build_query(params)["query"]["bool"]["filter"]

    assert {"term": {"source_type": "law"}} in filters


def test_diet_source_adds_source_type_filter():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="予算", mode="literal", filters={}, size=20, page=1, source="diet")

    filters = service.build_query(params)["query"]["bool"]["filter"]

    assert {"term": {"source_type": "diet"}} in filters


def test_all_source_does_not_add_source_type_filter():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="損害", mode="literal", filters={}, size=20, page=1, source="all")

    filters = service.build_query(params)["query"]["bool"]["filter"]

    # No top-level source_type term: the source split lives inside a should.
    assert {"term": {"source_type": "law"}} not in filters
    assert {"term": {"source_type": "diet"}} not in filters


def test_all_source_with_diet_filter_keeps_law_results():
    # Spec lock: in cross-search, a diet-only filter (speaker) must not drop law
    # docs. Law docs pass through the law branch (which carries no diet filter),
    # while diet docs are constrained by the speaker filter.
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(
        q="予算", mode="literal", filters={"speaker": "山田太郎"}, size=20, page=1, source="all"
    )

    filters = service.build_query(params)["query"]["bool"]["filter"]
    should = filters[0]["bool"]["should"]
    assert filters[0]["bool"]["minimum_should_match"] == 1

    law_branch = next(b for b in should if {"term": {"source_type": "law"}} in b["bool"]["filter"])
    diet_branch = next(
        b for b in should if {"term": {"source_type": "diet"}} in b["bool"]["filter"]
    )
    # Law branch is unconstrained by the speaker filter; diet branch carries it.
    assert service._speaker_filter("山田太郎") not in law_branch["bool"]["filter"]
    assert service._speaker_filter("山田太郎") in diet_branch["bool"]["filter"]


def test_all_source_with_law_filter_keeps_diet_results():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(
        q="予算", mode="literal", filters={"law": "民法"}, size=20, page=1, source="all"
    )

    should = service.build_query(params)["query"]["bool"]["filter"][0]["bool"]["should"]
    law_branch = next(b for b in should if {"term": {"source_type": "law"}} in b["bool"]["filter"])
    diet_branch = next(
        b for b in should if {"term": {"source_type": "diet"}} in b["bool"]["filter"]
    )
    assert service._law_name_filter("民法") in law_branch["bool"]["filter"]
    # Diet branch is not constrained by the law-name filter.
    assert service._law_name_filter("民法") not in diet_branch["bool"]["filter"]


def test_diet_source_treats_citation_only_as_content_search():
    # 国会タブで「709条」は法令引用ではなく本文検索として扱う。match_all +
    # article_no=709 で発言709 を返すのではなく、本文に「709条」を含む発言を探す。
    service = SearchService(backend=DummyBackend())
    params = SearchParams(q="709条", mode="auto", filters={}, size=20, page=1, source="diet")

    query = service.build_query(params)["query"]["bool"]

    assert query["must"] != [{"match_all": {}}]
    assert query["must"][0]["match_phrase"]["content"]["query"] == "709条"
    assert {"term": {"article_no": "709"}} not in query["filter"]
    assert query["filter"] == [{"term": {"source_type": "diet"}}]
    assert SearchService.classify_query("709条", "auto", "diet")["effective_mode"] == "literal"


def test_diet_source_searches_full_query_not_citation_residual():
    # 「民法 709条 損害」も法令フィルタ (law_name=民法) を掛けず、全文を本文検索する。
    service = SearchService(backend=DummyBackend())
    params = SearchParams(
        q="民法 709条 損害", mode="auto", filters={}, size=20, page=1, source="diet"
    )

    query = service.build_query(params)["query"]["bool"]

    assert query["must"][0]["match_phrase"]["content"]["query"] == "民法 709条 損害"
    assert service._law_name_filter("民法") not in query["filter"]
    assert query["filter"] == [{"term": {"source_type": "diet"}}]


def test_all_source_citation_only_does_not_match_all_diet():
    # Spec lock: 横断 + citation-only (民法709条) must not dump every diet speech.
    # `must` is match_all, so the diet branch (source_type=diet only) would
    # otherwise match all speeches. Cross-search collapses to law-only here.
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="民法 709条", mode="auto", filters={}, size=20, page=1, source="all")

    query = service.build_query(params)["query"]["bool"]
    filters = query["filter"]

    assert query["must"] == [{"match_all": {}}]
    # Law-only collapse: a plain source_type=law term, citation filters applied,
    # and crucially no diet branch anywhere in the filter tree.
    assert {"term": {"source_type": "law"}} in filters
    assert service._law_name_filter("民法") in filters
    assert {"term": {"article_no": "709"}} in filters
    assert 'source_type": "diet' not in json.dumps(filters)


def test_all_source_citation_with_residual_keeps_diet_branch():
    # With a free-text residual term the diet branch is meaningful again
    # (the residual is enforced via top-level `must`), so keep cross-search.
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(
        q="民法 709条 損害", mode="auto", filters={}, size=20, page=1, source="all"
    )

    query = service.build_query(params)["query"]["bool"]
    should = query["filter"][0]["bool"]["should"]

    assert query["must"][0]["match_phrase"]["content"]["query"] == "損害"
    assert any({"term": {"source_type": "diet"}} in b["bool"]["filter"] for b in should)


def test_search_index_payload_includes_split_indices_for_all():
    created: dict[str, DummyBackend] = {}

    def factory(index: str) -> DummyBackend:
        backend = DummyBackend()
        backend.index = index
        created[index] = backend
        return backend

    service = SearchService(backend_factory=factory)
    params = SearchParams(q="損害", mode="literal", filters={}, size=20, page=1, source="all")

    result = service.search(params)

    assert result["index"]["name"] == "jlaw-current,jdiet-current"
    assert result["index"]["indices"] == ["jlaw-current", "jdiet-current"]


def test_search_routes_to_diet_backend_without_real_opensearch():
    # diet/all routing must go through the injected backend_factory, so the
    # diet path is unit-testable without constructing a real OpenSearchBackend.
    created: dict[str, DummyBackend] = {}

    def factory(index: str) -> DummyBackend:
        backend = DummyBackend()
        backend.index = index
        created[index] = backend
        return backend

    service = SearchService(backend_factory=factory)
    params = SearchParams(q="予算", mode="literal", filters={}, size=20, page=1, source="diet")

    result = service.search(params)

    assert result["index"]["name"] == "jdiet-current"
    assert created["jdiet-current"].last_ignore_unavailable is True


def test_all_search_spans_injected_law_index_and_diet():
    created: dict[str, DummyBackend] = {}

    def factory(index: str) -> DummyBackend:
        backend = DummyBackend()
        backend.index = index
        created[index] = backend
        return backend

    service = SearchService(backend_factory=factory)
    params = SearchParams(q="損害", mode="literal", filters={}, size=20, page=1, source="all")

    result = service.search(params)

    assert result["index"]["name"] == "jlaw-current,jdiet-current"
    assert created["jlaw-current,jdiet-current"].last_ignore_unavailable is True


def test_law_search_does_not_set_ignore_unavailable():
    backend = DummyBackend()
    service = SearchService(backend=backend)
    params = SearchParams(q="損害", mode="literal", filters={}, size=20, page=1, source="law")

    service.search(params)

    assert backend.last_ignore_unavailable is False


def test_validate_filters_rejects_invalid_date():
    with pytest.raises(ValueError, match="date_from must be a valid"):
        SearchService.validate_filters("diet", {"date_from": "2025/06/09"})


def test_validate_filters_rejects_inverted_date_range():
    with pytest.raises(ValueError, match="date_from must not be after date_to"):
        SearchService.validate_filters("diet", {"date_from": "2026-06-09", "date_to": "2025-06-09"})


def test_validate_filters_rejects_unknown_key_for_source():
    with pytest.raises(ValueError, match="Unsupported filter"):
        SearchService.validate_filters("diet", {"year": "2025"})


def test_validate_filters_accepts_known_law_and_diet_keys():
    SearchService.validate_filters("law", {"law": "民法", "year": "2025"})
    SearchService.validate_filters(
        "diet", {"house": "衆議院", "date_from": "2025-06-09", "date_to": "2026-06-09"}
    )
    # `all` accepts the union of law and diet keys.
    SearchService.validate_filters("all", {"law": "民法", "speaker": "山田"})
