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
    assert backend.last_body["query"]["bool"]["must"][0]["match_phrase"]["content"] == "民法 709条"
