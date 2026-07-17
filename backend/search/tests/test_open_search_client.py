import threading
import time
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
    assert first_body["query"] == {"bool": {"filter": [{"term": {"law_id": "minpo"}}]}}
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


def test_bulk_runs_requests_concurrently(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(OPENSEARCH_BULK_TIMEOUT_SECONDS=10, OPENSEARCH_BULK_MAX_BYTES=1024),
    )

    class ConcurrentBulkClient(DummyBulkClient):
        def __init__(self):
            super().__init__({"errors": False, "items": []})
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def bulk(self, body, refresh, request_timeout):
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            time.sleep(0.02)
            with self.lock:
                self.active -= 1
            return {"errors": False, "items": []}

    client = ConcurrentBulkClient()
    backend = OpenSearchBackend(client=client, index="laws")
    actions = [{"_id": str(index), "_source": {"content": str(index)}} for index in range(8)]

    assert backend.bulk(actions, chunk_size=1, workers=4) == 8
    assert client.max_active > 1


def test_bulk_rejects_non_positive_workers(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(OPENSEARCH_BULK_TIMEOUT_SECONDS=10, OPENSEARCH_BULK_MAX_BYTES=1024),
    )
    backend = OpenSearchBackend(client=DummyBulkClient({"errors": False}), index="laws")

    try:
        backend.bulk([], workers=0)
    except ValueError as exc:
        assert "at least 1" in str(exc)
    else:
        raise AssertionError("Expected invalid worker count to raise")


def test_position_fields_are_keywords(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(OPENSEARCH_SCHEMA_VERSION=4, OPENSEARCH_NUMBER_OF_SHARDS=4),
    )
    backend = OpenSearchBackend(
        client=DummyBulkClient({"errors": False, "items": []}), index="laws"
    )
    definition = backend.get_index_definition()
    assert definition["settings"]["index"]["number_of_shards"] == 4
    assert definition["settings"]["index"]["max_ngram_diff"] == 20
    assert definition["mappings"]["_meta"]["schema_version"] == 4
    properties = definition["mappings"]["properties"]
    assert properties["paragraph_no"]["type"] == "keyword"
    assert properties["item_no"]["type"] == "keyword"
    assert properties["caption"] == {"type": "text", "analyzer": "jp_ngram_analyzer"}
    assert properties["content_long"] == {"type": "keyword", "ignore_above": 8192}


def test_highlight_config_includes_caption_and_heading():
    fields = open_search_client.highlight_config()["fields"]

    assert "caption" in fields
    assert "heading" in fields
    assert "content" in fields


def test_large_source_only_fields_are_not_indexed(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(OPENSEARCH_SCHEMA_VERSION=4, OPENSEARCH_NUMBER_OF_SHARDS=4),
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
    assert "diet" not in payload


class DietAwareIndices(DummyIndices):
    def __init__(self, existing, mappings):
        super().__init__()
        self._existing = set(existing)
        self._mappings = mappings

    def exists(self, index):
        return index in self._existing

    def get_mapping(self, index):
        return {index: self._mappings[index]}

    def get_alias(self, name):
        raise open_search_client.TransportError(404, "missing")


class DietAwareClient:
    def __init__(self, existing, mappings):
        self.indices = DietAwareIndices(existing, mappings)
        self.counted = []

    def count(self, index):
        self.counted.append(index)
        return {"count": 1}


def test_validate_ready_skips_diet_index_when_absent(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(
            OPENSEARCH_SCHEMA_VERSION=7,
            OPENSEARCH_NUMBER_OF_SHARDS=4,
            OPENSEARCH_DIET_INDEX="jdiet-current",
        ),
    )
    meta = {"mappings": {"_meta": {"schema_version": 7}}}
    client = DietAwareClient(existing={"jlaw-current"}, mappings={"jlaw-current": meta})
    backend = OpenSearchBackend(client=client, index="jlaw-current")

    payload = backend.validate_ready()

    assert "diet" not in payload
    assert client.counted == ["jlaw-current"]


def test_validate_ready_validates_diet_index_when_present(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(
            OPENSEARCH_SCHEMA_VERSION=7,
            OPENSEARCH_NUMBER_OF_SHARDS=4,
            OPENSEARCH_DIET_INDEX="jdiet-current",
        ),
    )
    meta = {"mappings": {"_meta": {"schema_version": 7}}}
    client = DietAwareClient(
        existing={"jlaw-current", "jdiet-current"},
        mappings={"jlaw-current": meta, "jdiet-current": meta},
    )
    backend = OpenSearchBackend(client=client, index="jlaw-current")

    payload = backend.validate_ready()

    assert payload["diet"]["name"] == "jdiet-current"
    assert payload["diet"]["concrete"] == ["jdiet-current"]
    assert "jdiet-current" in client.counted


def test_validate_ready_raises_on_diet_schema_mismatch(monkeypatch):
    monkeypatch.setattr(
        open_search_client,
        "settings",
        SimpleNamespace(
            OPENSEARCH_SCHEMA_VERSION=7,
            OPENSEARCH_NUMBER_OF_SHARDS=4,
            OPENSEARCH_DIET_INDEX="jdiet-current",
        ),
    )
    client = DietAwareClient(
        existing={"jlaw-current", "jdiet-current"},
        mappings={
            "jlaw-current": {"mappings": {"_meta": {"schema_version": 7}}},
            "jdiet-current": {"mappings": {"_meta": {"schema_version": 6}}},
        },
    )
    backend = OpenSearchBackend(client=client, index="jlaw-current")

    try:
        backend.validate_ready()
    except RuntimeError as exc:
        assert "schema version mismatch" in str(exc)
    else:
        raise AssertionError("Expected diet schema mismatch to fail readyz")
