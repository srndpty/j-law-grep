from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from django.conf import settings
from opensearchpy import OpenSearch, TransportError


@dataclass
class SearchHit:
    file_id: str
    law_name: str
    article_no: str
    paragraph_no: str | None
    item_no: str | None
    path: str
    line: int
    snippet: str
    snippet_text: str
    highlights: list[dict[str, int]]
    url: str
    blocks: list[dict[str, Any]]


@lru_cache(maxsize=8)
def get_opensearch_client(host: str, timeout: int) -> OpenSearch:
    return OpenSearch(host, timeout=timeout)


class OpenSearchBackend:
    def __init__(self, client: OpenSearch | None = None, index: str | None = None) -> None:
        self.client = client or self._create_client()
        self.index = index or settings.OPENSEARCH_INDEX

    def _create_client(self) -> OpenSearch:
        return get_opensearch_client(
            settings.OPENSEARCH_HOST,
            settings.OPENSEARCH_TIMEOUT_SECONDS,
        )

    def get_index_definition(self) -> dict[str, Any]:
        return {
            "settings": {
                "index": {
                    "number_of_shards": settings.OPENSEARCH_NUMBER_OF_SHARDS,
                    "number_of_replicas": 0,
                    "max_ngram_diff": 20,
                    "refresh_interval": "-1",
                },
                "analysis": {
                    "tokenizer": {
                        # Use an ngram tokenizer so character positions advance; this keeps phrase
                        # queries from collapsing into a single position (which caused noisy matches
                        # like 「当面の」 matching any token that contained 「面の」).
                        "jp_ngram_tokenizer": {
                            "type": "ngram",
                            "min_gram": 2,
                            "max_gram": 15,
                            "token_chars": ["letter", "digit"],
                        },
                    },
                    "analyzer": {
                        "jp_ngram_analyzer": {
                            "tokenizer": "jp_ngram_tokenizer",
                            "filter": ["lowercase", "asciifolding"],
                        },
                        "jp_edge_analyzer": {
                            "tokenizer": "whitespace",
                            "filter": ["lowercase", "jp_edge_filter"],
                        },
                    },
                    "filter": {
                        "jp_edge_filter": {
                            "type": "edge_ngram",
                            "min_gram": 1,
                            "max_gram": 15,
                        },
                    },
                },
            },
            "mappings": {
                "_meta": {
                    "schema_version": settings.OPENSEARCH_SCHEMA_VERSION,
                },
                "properties": {
                    "law_id": {"type": "keyword"},
                    "law_name": {
                        "type": "keyword",
                        "fields": {
                            "prefix": {"type": "text", "analyzer": "jp_edge_analyzer"},
                        },
                    },
                    "law_aliases": {
                        "type": "keyword",
                        "fields": {
                            "prefix": {"type": "text", "analyzer": "jp_edge_analyzer"},
                        },
                    },
                    "article_no": {"type": "keyword"},
                    "paragraph_no": {"type": "keyword"},
                    "item_no": {"type": "keyword"},
                    "citation_key": {
                        "type": "keyword",
                        "fields": {
                            "prefix": {"type": "text", "analyzer": "jp_edge_analyzer"},
                        },
                    },
                    "heading": {"type": "text", "analyzer": "jp_ngram_analyzer"},
                    "content": {
                        "type": "text",
                        "analyzer": "jp_ngram_analyzer",
                        "term_vector": "with_positions_offsets",
                    },
                    "content_plain": {"type": "text", "index": False},
                    "year_enforced": {"type": "keyword"},
                    "path": {"type": "keyword"},
                    "url": {"type": "keyword"},
                    "line": {"type": "integer"},
                    "blocks": {"type": "object", "enabled": False},
                },
            },
        }

    def ensure_index(self) -> None:
        if self.client.indices.exists(index=self.index):
            return
        definition = self.get_index_definition()
        self.client.indices.create(index=self.index, body=definition)

    def create_index(self, index: str) -> None:
        if self.client.indices.exists(index=index):
            raise RuntimeError(f"OpenSearch index already exists: {index}")
        self.client.indices.create(index=index, body=self.get_index_definition())

    def delete_index(self, index: str) -> None:
        if self.client.indices.exists(index=index):
            self.client.indices.delete(index=index)

    def prepare_for_search(self, index: str | None = None, forcemerge: bool = False) -> None:
        target = index or self.index
        self.client.indices.put_settings(
            index=target,
            body={"index": {"refresh_interval": "1s"}},
        )
        self.client.indices.refresh(index=target)
        if forcemerge:
            self.client.indices.forcemerge(index=target, max_num_segments=1)

    def count(self, index: str | None = None) -> int:
        response = self.client.count(index=index or self.index)
        return int(response.get("count", 0))

    def cluster_health(self) -> dict[str, Any]:
        return self.client.cluster.health()

    def switch_alias(self, alias: str, target_index: str) -> None:
        actions: list[dict[str, Any]] = []
        for old_index in self.indices_for_alias(alias):
            actions.append({"remove": {"index": old_index, "alias": alias}})
        actions.append({"add": {"index": target_index, "alias": alias}})
        self.client.indices.update_aliases(body={"actions": actions})

    def indices_for_alias(self, alias: str) -> list[str]:
        try:
            response = self.client.indices.get_alias(name=alias)
        except TransportError as exc:
            if exc.status_code == 404:
                return []
            raise
        return sorted(response.keys())

    def search(self, body: dict[str, Any], size: int, from_: int) -> dict[str, Any]:
        return self.client.search(
            index=self.index,
            body=body,
            size=size,
            from_=from_,
            request_timeout=settings.OPENSEARCH_REQUEST_TIMEOUT_SECONDS,
        )

    @staticmethod
    def _estimated_bulk_action_bytes(action: dict[str, Any]) -> int:
        meta = {"index": {"_id": action["_id"]}}
        return (
            len(json.dumps(meta, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            + len(
                json.dumps(action["_source"], ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            + 2
        )

    def _chunked(
        self,
        actions: Iterable[dict[str, Any]],
        size: int,
        max_bytes: int | None = None,
    ) -> Iterable[list[dict[str, Any]]]:
        batch: list[dict[str, Any]] = []
        batch_bytes = 0
        for action in actions:
            action_bytes = self._estimated_bulk_action_bytes(action) if max_bytes else 0
            if batch and max_bytes and batch_bytes + action_bytes > max_bytes:
                yield batch
                batch = []
                batch_bytes = 0
            batch.append(action)
            batch_bytes += action_bytes
            if len(batch) >= size:
                yield batch
                batch = []
                batch_bytes = 0
        if batch:
            yield batch

    def bulk(
        self,
        actions: Iterable[dict[str, Any]],
        chunk_size: int = 200,
        max_chunk_bytes: int | None = None,
        progress: bool = False,
        refresh_at_end: bool = True,
    ) -> int:
        processed = 0
        max_bytes = max_chunk_bytes or settings.OPENSEARCH_BULK_MAX_BYTES
        for chunk in self._chunked(actions, size=chunk_size, max_bytes=max_bytes):
            body: list[dict[str, Any]] = []
            for action in chunk:
                meta = {"index": {"_index": self.index, "_id": action["_id"]}}
                body.extend([meta, action["_source"]])
            # Keep requests small and defer refresh to the end for better throughput
            response = self.client.bulk(
                body=body,
                refresh=False,
                request_timeout=settings.OPENSEARCH_BULK_TIMEOUT_SECONDS,
            )
            if response.get("errors"):
                failures = [
                    item.get("index", item)
                    for item in response.get("items", [])
                    if item.get("index", {}).get("error")
                ]
                preview = failures[:3]
                raise RuntimeError(f"OpenSearch bulk indexing failed: {preview}")
            processed += len(chunk)
        if refresh_at_end:
            self.client.indices.refresh(index=self.index)
        return processed


def highlight_config() -> dict[str, Any]:
    return {
        "fields": {
            "content": {
                "type": "unified",
                "number_of_fragments": 3,
                "fragment_size": 120,
                "no_match_size": 120,
                "pre_tags": ["<mark>"],
                "post_tags": ["</mark>"],
            }
        }
    }
