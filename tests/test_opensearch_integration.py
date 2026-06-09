from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from django.test import override_settings

from indexer.pipeline import iter_records, to_index_actions
from search.open_search_client import OpenSearchBackend
from search.service import SearchParams, SearchService


@pytest.mark.integration
def test_sample_corpus_reindex_alias_and_search_against_opensearch():
    alias = f"jlaw-it-{uuid4().hex[:12]}"
    concrete = f"{alias}-v1"
    backend = OpenSearchBackend(index=concrete)
    try:
        backend.create_index(concrete)
        indexed = backend.bulk(to_index_actions(iter_records(Path("indexer/sample_corpus"))))
        backend.prepare_for_search(concrete)
        assert indexed == backend.count(concrete)
        backend.validate_schema(concrete)
        backend.switch_alias(alias, concrete)

        service = SearchService(backend=OpenSearchBackend(index=alias))
        result = service.search(
            SearchParams(q="民法709条", mode="auto", filters={}, size=10, page=1)
        )
        assert result["total"] >= 1
        assert result["hits"][0]["law_name"] == "民法"
        assert result["hits"][0]["article_no"] == "709"
    finally:
        cleanup = OpenSearchBackend(index=concrete)
        cleanup.delete_index(concrete)


@pytest.mark.integration
def test_diet_search_missing_index_returns_empty_not_500():
    # diet-only search targets an alias that has never been created. With
    # ignore_unavailable, OpenSearch must return an empty result set rather than
    # an index_not_found error (which would surface as a 5xx in the API).
    missing_alias = f"jdiet-missing-{uuid4().hex[:12]}"
    with override_settings(OPENSEARCH_DIET_INDEX=missing_alias):
        service = SearchService()
        result = service.search(
            SearchParams(q="予算", mode="literal", filters={}, size=10, page=1, source="diet")
        )

    assert result["total"] == 0
    assert result["hits"] == []
