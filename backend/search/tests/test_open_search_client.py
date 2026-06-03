from types import SimpleNamespace

from search import open_search_client
from search.open_search_client import OpenSearchBackend


class DummyIndices:
    def __init__(self):
        self._exists = False
        self.created = None
        self.mapping = {}

    def exists(self, index):
        return self._exists

    def create(self, index, body):
        self.created = (index, body)
        self._exists = True

    def get_mapping(self, index):
        return self.mapping

    def get_alias(self, name):
        raise open_search_client.TransportError(404, "missing")

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


class DummyCountClient(DummyBulkClient):
    def __init__(self, response):
        super().__init__(response)
        self.indices._exists = True
        self.indices.mapping = {"laws": {"mappings": {"_meta": {"schema_version": 2}}}}

    def count(self, index):
        self.counted = index
        return {"count": 1}


class DummyLawNamesClient:
    def __init__(self):
        self.calls = []
        self.indices = DummyIndices()
        self.responses = [
            {
                "aggregations": {
                    "laws": {
                        "buckets": [
                            {"key": {"law": "民法"}},
                            {"key": {"law": "刑法"}},
                        ],
                        "after_key": {"law": "刑法"},
                    }
                }
            },
            {
                "aggregations": {
                    "laws": {
                        "buckets": [
                            {"key": {"law": "商法"}},
                        ],
                    }
                }
            },
        ]

    def search(self, index, body, request_timeout):
        self.calls.append((index, body, request_timeout))
        return self.responses.pop(0)


class DummyLawDocumentClient:
    def __init__(self):
        self.calls = []
        self.indices = DummyIndices()
        self.responses = [
            {
                "hits": {
                    "total": {"value": 3, "relation": "eq"},
                    "hits": [
                        {"_id": "1", "_source": {"article_no": "1"}, "sort": ["1", "", "", "a"]},
                        {"_id": "2", "_source": {"article_no": "2"}, "sort": ["2", "", "", "b"]},
                    ],
                }
            },
            {
                "hits": {
                    "total": {"value": 3, "relation": "eq"},
                    "hits": [
                        {"_id": "3", "_source": {"article_no": "3"}, "sort": ["3", "", "", "c"]},
                    ],
                }
            },
        ]

    def search(self, index, body, size, request_timeout):
        self.calls.append((index, body, size, request_timeout))
        return self.responses.pop(0)


def test_law_names_pages_composite_aggregation(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(OPENSEARCH_REQUEST_TIMEOUT_SECONDS=10),
    )
    client = DummyLawNamesClient()
    backend = OpenSearchBackend(client=client, index="laws")

    names = backend.law_names(page_size=2)

    assert names == ["民法", "刑法", "商法"]
    first_body = client.calls[0][1]
    second_body = client.calls[1][1]
    assert first_body["aggs"]["laws"]["composite"]["size"] == 2
    assert first_body["aggs"]["laws"]["composite"]["sources"] == [
        {"law": {"terms": {"field": "law_name", "order": "asc"}}}
    ]
    assert "after" not in first_body["aggs"]["laws"]["composite"]
    assert second_body["aggs"]["laws"]["composite"]["after"] == {"law": "刑法"}


def test_law_document_pages_with_search_after(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(OPENSEARCH_REQUEST_TIMEOUT_SECONDS=10),
    )
    client = DummyLawDocumentClient()
    backend = OpenSearchBackend(client=client, index="laws")

    response = backend.law_document("minpo", page_size=2)

    assert [hit["_id"] for hit in response["hits"]["hits"]] == ["1", "2", "3"]
    assert response["hits"]["total"] == {"value": 3, "relation": "eq"}
    first_body = client.calls[0][1]
    second_body = client.calls[1][1]
    assert first_body["query"] == {"term": {"law_id": "minpo"}}
    assert first_body["track_total_hits"] is True
    assert "search_after" not in first_body
    assert second_body["search_after"] == ["2", "", "", "b"]
    assert client.calls[0][2] == 2


def test_bulk_raises_on_partial_failure(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(
            OPENSEARCH_BULK_TIMEOUT_SECONDS=10, OPENSEARCH_BULK_MAX_BYTES=40 * 1024 * 1024
        ),
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
        SimpleNamespace(
            OPENSEARCH_BULK_TIMEOUT_SECONDS=10, OPENSEARCH_BULK_MAX_BYTES=40 * 1024 * 1024
        ),
    )
    client = DummyBulkClient({"errors": False, "items": []})
    backend = OpenSearchBackend(client=client, index="laws")
    actions = [{"_id": "1", "_source": {"content": "x"}}]

    assert backend.bulk(actions) == 1


def test_bulk_splits_by_max_chunk_bytes(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(OPENSEARCH_BULK_TIMEOUT_SECONDS=10, OPENSEARCH_BULK_MAX_BYTES=70),
    )
    client = DummyBulkClient({"errors": False, "items": []})
    calls = []

    def bulk(body, refresh, request_timeout):
        calls.append(body)
        return {"errors": False, "items": []}

    client.bulk = bulk  # type: ignore[method-assign]
    backend = OpenSearchBackend(client=client, index="laws")
    actions = [
        {"_id": "1", "_source": {"content": "x" * 20}},
        {"_id": "2", "_source": {"content": "y" * 20}},
    ]

    assert backend.bulk(actions, chunk_size=100) == 2
    assert len(calls) == 2


def test_position_fields_are_keywords(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(OPENSEARCH_SCHEMA_VERSION=2, OPENSEARCH_NUMBER_OF_SHARDS=4),
    )
    backend = OpenSearchBackend(
        client=DummyBulkClient({"errors": False, "items": []}), index="laws"
    )
    assert backend.get_index_definition()["settings"]["index"]["number_of_shards"] == 4
    properties = backend.get_index_definition()["mappings"]["properties"]
    assert properties["paragraph_no"]["type"] == "keyword"
    assert properties["item_no"]["type"] == "keyword"


def test_large_source_only_fields_are_not_indexed(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(OPENSEARCH_SCHEMA_VERSION=2, OPENSEARCH_NUMBER_OF_SHARDS=4),
    )
    backend = OpenSearchBackend(
        client=DummyBulkClient({"errors": False, "items": []}), index="laws"
    )
    properties = backend.get_index_definition()["mappings"]["properties"]
    assert properties["content_plain"]["index"] is False
    assert properties["blocks"]["enabled"] is False


def test_ensure_index_rejects_schema_version_mismatch(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(OPENSEARCH_SCHEMA_VERSION=2, OPENSEARCH_NUMBER_OF_SHARDS=4),
    )
    client = DummyBulkClient({"errors": False, "items": []})
    client.indices._exists = True
    client.indices.mapping = {"laws": {"mappings": {"_meta": {"schema_version": 1}}}}
    backend = OpenSearchBackend(client=client, index="laws")

    try:
        backend.ensure_index()
    except RuntimeError as exc:
        assert "schema version mismatch" in str(exc)
    else:
        raise AssertionError("Expected schema mismatch to fail")


def test_ensure_index_validates_alias_mapping_response(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(OPENSEARCH_SCHEMA_VERSION=2, OPENSEARCH_NUMBER_OF_SHARDS=4),
    )
    client = DummyBulkClient({"errors": False, "items": []})
    client.indices._exists = True
    client.indices.mapping = {
        "laws-v20260603000000": {"mappings": {"_meta": {"schema_version": 2}}}
    }
    backend = OpenSearchBackend(client=client, index="laws")

    backend.ensure_index()


def test_validate_ready_checks_index_schema_and_count(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(OPENSEARCH_SCHEMA_VERSION=2, OPENSEARCH_NUMBER_OF_SHARDS=4),
    )
    client = DummyCountClient({"errors": False, "items": []})
    backend = OpenSearchBackend(client=client, index="laws")

    payload = backend.validate_ready()

    assert payload["concrete"] == ["laws"]
    assert payload["schema_version"] == 2
    assert client.counted == "laws"
