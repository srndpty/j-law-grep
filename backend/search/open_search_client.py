from __future__ import annotations

import json
from collections.abc import Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from django.conf import settings
from opensearchpy import OpenSearch, TransportError

# Optional corpora aliases reported by /readyz, keyed by the payload key.
OPTIONAL_ALIAS_SETTINGS = {
    "diet": "OPENSEARCH_DIET_INDEX",
    "shuisho": "OPENSEARCH_SHUISHO_INDEX",
}


@dataclass
class SearchHit:
    file_id: str
    source_type: str
    law_id: str
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
    house: str | None = None
    meeting_name: str | None = None
    date: str | None = None
    speaker: str | None = None
    speaker_group: str | None = None
    speaker_position: str | None = None
    speaker_role: str | None = None
    session: str | None = None
    shuisho_kind: str | None = None
    shuisho_number: str | None = None
    submitter: str | None = None


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
                    "source_type": {"type": "keyword"},
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
                    "caption": {"type": "text", "analyzer": "jp_ngram_analyzer"},
                    "heading": {"type": "text", "analyzer": "jp_ngram_analyzer"},
                    "content": {
                        "type": "text",
                        "analyzer": "jp_ngram_analyzer",
                        "term_vector": "with_positions_offsets",
                        "fields": {
                            "keywordish": {"type": "text", "analyzer": "whitespace"},
                        },
                    },
                    "content_long": {
                        "type": "keyword",
                        "ignore_above": 8192,
                    },
                    "content_plain": {"type": "text", "index": False},
                    "year_enforced": {"type": "keyword"},
                    "issue_id": {"type": "keyword"},
                    "house": {"type": "keyword"},
                    # meeting_name / speaker / speaker_yomi are matched with
                    # keyword term + `prefix` queries (see SearchService), which
                    # already give forward-match without an edge-ngram subfield.
                    "meeting_name": {"type": "keyword"},
                    "session": {"type": "keyword"},
                    "issue": {"type": "keyword"},
                    "date": {"type": "date", "format": "strict_date_optional_time||yyyy-MM-dd"},
                    "speaker": {"type": "keyword"},
                    "speaker_yomi": {"type": "keyword"},
                    "speaker_group": {"type": "keyword"},
                    "speaker_position": {
                        "type": "text",
                        "analyzer": "jp_ngram_analyzer",
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                    },
                    "speaker_role": {"type": "keyword"},
                    "speech_id": {"type": "keyword"},
                    "speech_order": {"type": "keyword"},
                    # 質問主意書: 質問本文 / 答弁本文の別と提出番号。件名は law_name
                    # を流用する。submitter は質問・答弁の両レコードに提出者を持つ
                    # (speaker はレコードごとの発話者なので答弁では答弁者になる)。
                    "shuisho_kind": {"type": "keyword"},
                    "shuisho_number": {"type": "keyword"},
                    "submitter": {"type": "keyword"},
                    "pdf_url": {"type": "keyword"},
                    "path": {"type": "keyword"},
                    "url": {"type": "keyword"},
                    "line": {"type": "integer"},
                    "blocks": {"type": "object", "enabled": False},
                },
            },
        }

    def ensure_index(self) -> None:
        if self.client.indices.exists(index=self.index):
            self.validate_schema(self.index)
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

    def index_stats(self, index: str | None = None) -> dict[str, Any]:
        target = index or self.index
        return {
            "health": self.client.cluster.health(index=target),
            "stats": self.client.indices.stats(index=target, metric=["docs", "store"]),
            "mapping": self.client.indices.get_mapping(index=target),
        }

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

    def schema_versions(self, index_or_alias: str) -> dict[str, int | None]:
        response = self.client.indices.get_mapping(index=index_or_alias)
        versions: dict[str, int | None] = {}
        for concrete_index, payload in response.items():
            metadata = payload.get("mappings", {}).get("_meta", {})
            version = metadata.get("schema_version")
            versions[concrete_index] = int(version) if version is not None else None
        return versions

    def get_schema_version(self, index: str) -> int | None:
        versions = self.schema_versions(index)
        if len(versions) == 1:
            return next(iter(versions.values()))
        return versions.get(index)

    def validate_schema(self, index_or_alias: str) -> None:
        versions = self.schema_versions(index_or_alias)
        expected = settings.OPENSEARCH_SCHEMA_VERSION
        mismatches = {index: actual for index, actual in versions.items() if actual != expected}
        if mismatches:
            raise RuntimeError(
                f"Index schema version mismatch: expected {expected}, got {mismatches}. "
                "Run versioned reindex."
            )

    def concrete_indices(self, index_or_alias: str | None = None) -> list[str]:
        target = index_or_alias or self.index
        alias_indices = self.indices_for_alias(target)
        if alias_indices:
            return alias_indices
        if not self.client.indices.exists(index=target):
            raise RuntimeError(f"OpenSearch index does not exist: {target}")
        return [target]

    def validate_ready(self) -> dict[str, Any]:
        # The law alias must exist and match the backend schema version. This is
        # what catches the "ran new code against an un-reindexed v6 index" case,
        # where the source_type filter would otherwise silently return 0 hits.
        concrete_indices = self.concrete_indices(self.index)
        for index in concrete_indices:
            self.validate_schema(index)
            self.count(index=index)
        payload: dict[str, Any] = {
            "name": self.index,
            "concrete": concrete_indices,
            "schema_version": settings.OPENSEARCH_SCHEMA_VERSION,
        }
        for key, setting_name in OPTIONAL_ALIAS_SETTINGS.items():
            optional = self._optional_alias_ready_payload(setting_name)
            if optional is not None:
                payload[key] = optional
        return payload

    def _optional_alias_ready_payload(self, setting_name: str) -> dict[str, Any] | None:
        # The diet / shuisho aliases are optional: a law-only deployment never
        # creates them, so their absence is not a readiness failure (those
        # searches tolerate the missing index). When one does exist, hold it to
        # the same schema gate.
        alias = getattr(settings, setting_name, None)
        if not alias:
            return None
        concrete = self.indices_for_alias(alias)
        if not concrete:
            if not self.client.indices.exists(index=alias):
                return None
            concrete = [alias]
        for index in concrete:
            self.validate_schema(index)
            self.count(index=index)
        return {"name": alias, "concrete": concrete}

    def cluster_health(self) -> dict[str, Any]:
        return self.client.cluster.health()

    def switch_alias(self, alias: str, target_index: str) -> None:
        if not self.client.indices.exists(index=target_index):
            raise RuntimeError(
                f"Cannot switch alias {alias}: target index does not exist: {target_index}"
            )
        # Refuse to promote an index whose mapping schema does not match the
        # backend expectation, so a stale or half-built index never becomes live.
        self.validate_schema(target_index)
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

    def all_indices(self, pattern: str) -> list[str]:
        try:
            response = self.client.indices.get(index=pattern)
        except TransportError as exc:
            if exc.status_code == 404:
                return []
            raise
        return sorted(response.keys())

    def law_names(self, page_size: int = 1000) -> list[str]:
        names: list[str] = []
        after: dict[str, Any] | None = None
        while True:
            composite: dict[str, Any] = {
                "size": page_size,
                "sources": [
                    {
                        "law": {
                            "terms": {
                                "field": "law_name",
                                "order": "asc",
                            }
                        }
                    }
                ],
            }
            if after:
                composite["after"] = after
            body = {
                "size": 0,
                "aggs": {"laws": {"composite": composite}},
            }
            response = self.client.search(
                index=self.index,
                body=body,
                request_timeout=settings.OPENSEARCH_REQUEST_TIMEOUT_SECONDS,
            )
            aggregation = response.get("aggregations", {}).get("laws", {})
            buckets = aggregation.get("buckets", [])
            names.extend(
                bucket["key"]["law"] for bucket in buckets if bucket.get("key", {}).get("law")
            )
            after = aggregation.get("after_key")
            if not after:
                break
        return names

    def search(
        self,
        body: dict[str, Any],
        size: int,
        from_: int,
        ignore_unavailable: bool = False,
    ) -> dict[str, Any]:
        params = {"ignore_unavailable": "true"} if ignore_unavailable else None
        return self.client.search(
            index=self.index,
            body=body,
            size=size,
            from_=from_,
            params=params,
            request_timeout=settings.OPENSEARCH_REQUEST_TIMEOUT_SECONDS,
        )

    def law_document(
        self, law_id: str, article: str | None = None, page_size: int = 1000
    ) -> dict[str, Any]:
        hits: list[dict[str, Any]] = []
        total: dict[str, Any] | int = {"value": 0, "relation": "eq"}
        search_after: list[Any] | None = None
        sort = [
            {"article_no": {"order": "asc", "missing": "_first"}},
            {"paragraph_no": {"order": "asc", "missing": "_first"}},
            {"item_no": {"order": "asc", "missing": "_first"}},
            {"url": {"order": "asc", "missing": "_last"}},
        ]

        while True:
            body: dict[str, Any] = {
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"law_id": law_id}},
                            *([{"term": {"article_no": article}}] if article else []),
                        ]
                    }
                },
                "_source": [
                    "law_id",
                    "law_name",
                    "article_no",
                    "paragraph_no",
                    "item_no",
                    "caption",
                    "heading",
                    "content_plain",
                    "content",
                    "blocks",
                    "url",
                    "path",
                ],
                "sort": sort,
                "track_total_hits": True,
            }
            if search_after:
                body["search_after"] = search_after

            response = self.client.search(
                index=self.index,
                body=body,
                size=page_size,
                request_timeout=settings.OPENSEARCH_REQUEST_TIMEOUT_SECONDS,
            )
            page_hits = response.get("hits", {}).get("hits", [])
            total = response.get("hits", {}).get("total", total)
            hits.extend(page_hits)
            if len(page_hits) < page_size:
                break
            next_search_after = page_hits[-1].get("sort")
            if not next_search_after:
                break
            search_after = next_search_after

        return {"hits": {"hits": hits, "total": total}}

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
        workers: int = 1,
    ) -> int:
        if workers < 1:
            raise ValueError("bulk workers must be at least 1")

        max_bytes = max_chunk_bytes or settings.OPENSEARCH_BULK_MAX_BYTES
        chunks = self._chunked(actions, size=chunk_size, max_bytes=max_bytes)
        if workers == 1:
            processed = sum(self._index_bulk_chunk(chunk) for chunk in chunks)
        else:
            processed = self._parallel_bulk(chunks, workers=workers)
        if refresh_at_end:
            self.client.indices.refresh(index=self.index)
        return processed

    def _index_bulk_chunk(self, chunk: list[dict[str, Any]]) -> int:
        body: list[dict[str, Any]] = []
        for action in chunk:
            meta = {"index": {"_index": self.index, "_id": action["_id"]}}
            body.extend([meta, action["_source"]])
        # Keep requests small and defer refresh to the end for better throughput.
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
        return len(chunk)

    def _parallel_bulk(self, chunks: Iterable[list[dict[str, Any]]], workers: int) -> int:
        processed = 0
        pending: set[Future[int]] = set()
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="opensearch-bulk") as pool:
            try:
                for chunk in chunks:
                    pending.add(pool.submit(self._index_bulk_chunk, chunk))
                    # Bound queued payloads to one chunk per worker. Generating the next
                    # chunk overlaps with requests that are still running, without retaining
                    # the whole corpus in memory.
                    if len(pending) >= workers:
                        done, pending = wait(pending, return_when=FIRST_COMPLETED)
                        processed += sum(future.result() for future in done)
                processed += sum(future.result() for future in pending)
            except Exception:
                for future in pending:
                    future.cancel()
                raise
        return processed


def highlight_config() -> dict[str, Any]:
    return {
        "fields": {
            "caption": {
                "type": "unified",
                "number_of_fragments": 1,
                "fragment_size": 120,
                "no_match_size": 0,
                "pre_tags": ["<mark>"],
                "post_tags": ["</mark>"],
            },
            "heading": {
                "type": "unified",
                "number_of_fragments": 1,
                "fragment_size": 120,
                "no_match_size": 0,
                "pre_tags": ["<mark>"],
                "post_tags": ["</mark>"],
            },
            "content": {
                "type": "unified",
                "number_of_fragments": 3,
                "fragment_size": 120,
                "no_match_size": 120,
                "pre_tags": ["<mark>"],
                "post_tags": ["</mark>"],
            },
        }
    }
