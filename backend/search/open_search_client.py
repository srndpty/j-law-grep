from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from django.conf import settings
from opensearchpy import OpenSearch


@dataclass
class SearchHit:
    file_id: str
    path: str
    line: int
    snippet: str
    url: str
    blocks: List[Dict[str, Any]]


class OpenSearchBackend:
    def __init__(self, client: Optional[OpenSearch] = None, index: Optional[str] = None) -> None:
        self.client = client or self._create_client()
        self.index = index or settings.OPENSEARCH_INDEX

    def _create_client(self) -> OpenSearch:
        return OpenSearch(settings.OPENSEARCH_HOST, timeout=30)

    def get_index_definition(self) -> Dict[str, Any]:
        return {
            "settings": {
                "index": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "max_ngram_diff": 20,
                },
                "analysis": {
                    "analyzer": {
                        "jp_ngram_analyzer": {
                            "tokenizer": "whitespace",
                            "filter": ["lowercase", "asciifolding", "jp_ngram_filter"],
                        },
                        "jp_edge_analyzer": {
                            "tokenizer": "whitespace",
                            "filter": ["lowercase", "jp_edge_filter"],
                        },
                    },
                    "filter": {
                        "jp_ngram_filter": {
                            "type": "ngram",
                            "min_gram": 2,
                            "max_gram": 15,
                        },
                        "jp_edge_filter": {
                            "type": "edge_ngram",
                            "min_gram": 1,
                            "max_gram": 15,
                        },
                    },
                },
            },
            "mappings": {
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
                    "paragraph_no": {"type": "integer"},
                    "item_no": {"type": "integer"},
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
                    "content_plain": {"type": "text", "analyzer": "jp_ngram_analyzer"},
                    "year_enforced": {"type": "keyword"},
                    "path": {"type": "keyword"},
                    "url": {"type": "keyword"},
                    "line": {"type": "integer"},
                    "blocks": {
                        "type": "nested",
                        "properties": {
                            "kind": {"type": "keyword"},
                            "html": {"type": "text", "analyzer": "jp_ngram_analyzer"}
                        }
                    },
                }
            },
        }

    def ensure_index(self) -> None:
        if self.client.indices.exists(index=self.index):
            return
        definition = self.get_index_definition()
        self.client.indices.create(index=self.index, body=definition)

    def search(self, body: Dict[str, Any], size: int, from_: int) -> Dict[str, Any]:
        return self.client.search(index=self.index, body=body, size=size, from_=from_)

    def _chunked(self, actions: Iterable[Dict[str, Any]], size: int) -> Iterable[List[Dict[str, Any]]]:
        batch: List[Dict[str, Any]] = []
        for action in actions:
            batch.append(action)
            if len(batch) >= size:
                yield batch
                batch = []
        if batch:
            yield batch

    def bulk(
        self,
        actions: List[Dict[str, Any]],
        chunk_size: int = 200,
        progress: bool = False,
        refresh_at_end: bool = True,
    ) -> None:
        if not actions:
            return

        total = len(actions)
        processed = 0
        for chunk in self._chunked(actions, size=chunk_size):
            body: List[Dict[str, Any]] = []
            for action in chunk:
                meta = {"index": {"_index": self.index, "_id": action["_id"]}}
                body.extend([meta, action["_source"]])
            # Keep requests small and defer refresh to the end for better throughput
            self.client.bulk(body=body, refresh=False)
            processed += len(chunk)
            if progress and processed % 5000 == 0:
                print(f"Indexed {processed}/{total} docs...", flush=True)
        if progress:
            print(f"Indexed {total}/{total} docs.", flush=True)
        if refresh_at_end:
            self.client.indices.refresh(index=self.index)


def highlight_config() -> Dict[str, Any]:
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
