from search.service import SearchParams, SearchService


class DummyBackend:
    def __init__(self) -> None:
        self.last_body = None

    def ensure_index(self) -> None:
        pass

    def search(self, body, size, from_):
        self.last_body = body
        return {"hits": {"hits": [], "total": {"value": 0}}, "took": 1}


def test_build_literal_query_uses_match_phrase(monkeypatch):
    backend = DummyBackend()
    service = SearchService(backend=backend)  # type: ignore[arg-type]
    params = SearchParams(q="民法 709条", mode="literal", filters={}, size=20, page=1)
    service.search(params)
    content = backend.last_body["query"]["bool"]["must"][0]["match_phrase"]["content"]
    assert content["query"] == "民法 709条"


def test_convert_hit_includes_article_metadata():
    backend = DummyBackend()
    service = SearchService(backend=backend)  # type: ignore[arg-type]
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


def test_convert_hit_derives_article_from_url_when_missing():
    backend = DummyBackend()
    service = SearchService(backend=backend)  # type: ignore[arg-type]
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
    assert result["paragraph_no"] == 4
