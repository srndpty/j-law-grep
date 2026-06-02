from types import SimpleNamespace

from search import open_search_client
from search.open_search_client import OpenSearchBackend


class DummyIndices:
    def refresh(self, index):
        self.refreshed = index


class DummyBulkClient:
    def __init__(self, response):
        self.response = response
        self.indices = DummyIndices()

    def bulk(self, body, refresh, request_timeout):
        self.body = body
        self.refresh = refresh
        self.request_timeout = request_timeout
        return self.response


def test_bulk_raises_on_partial_failure(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(OPENSEARCH_BULK_TIMEOUT_SECONDS=10),
    )
    client = DummyBulkClient(
        {
            "errors": True,
            "items": [
                {
                    "index": {
                        "_id": "1",
                        "error": {"type": "mapper_parsing_exception"},
                    }
                }
            ],
        }
    )
    backend = OpenSearchBackend(client=client, index="laws")
    actions = [{"_id": "1", "_source": {"content": "x"}}]

    try:
        backend.bulk(actions)
    except RuntimeError as exc:
        assert "bulk indexing failed" in str(exc)
    else:
        raise AssertionError("Expected bulk failure to raise")


def test_bulk_returns_processed_count(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(OPENSEARCH_BULK_TIMEOUT_SECONDS=10),
    )
    client = DummyBulkClient({"errors": False, "items": []})
    backend = OpenSearchBackend(client=client, index="laws")
    actions = [{"_id": "1", "_source": {"content": "x"}}]

    assert backend.bulk(actions) == 1


def test_position_fields_are_keywords(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(OPENSEARCH_SCHEMA_VERSION=2),
    )
    backend = OpenSearchBackend(client=DummyBulkClient({"errors": False, "items": []}), index="laws")
    properties = backend.get_index_definition()["mappings"]["properties"]
    assert properties["paragraph_no"]["type"] == "keyword"
    assert properties["item_no"]["type"] == "keyword"


def test_large_source_only_fields_are_not_indexed(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(OPENSEARCH_SCHEMA_VERSION=2),
    )
    backend = OpenSearchBackend(client=DummyBulkClient({"errors": False, "items": []}), index="laws")
    properties = backend.get_index_definition()["mappings"]["properties"]
    assert properties["content_plain"]["index"] is False
    assert properties["blocks"]["enabled"] is False
