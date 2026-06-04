from __future__ import annotations

import django
from opensearchpy import ConnectionError as OpenSearchConnectionError
from opensearchpy import ConnectionTimeout as OpenSearchConnectionTimeout
from opensearchpy import NotFoundError as OpenSearchNotFoundError
from rest_framework import status
from rest_framework.test import APIRequestFactory

from search.service import SearchParams
from search.views import LawDocumentView, LawsView, SearchDebugView, SearchView

django.setup()


class SuccessfulSearchService:
    def search(self, params: SearchParams):
        return {
            "hits": [],
            "total": 0,
            "took_ms": 1,
            "query": {"raw": params.q, "mode": params.mode, "effective_mode": params.mode},
            "index": {"name": "laws"},
        }

    def debug_query(self, params: SearchParams):
        return {"query_dsl": {"query": {"match_all": {}}}, "effective_mode": params.mode}


class ConnectionErrorSearchService:
    def search(self, params: SearchParams):
        raise OpenSearchConnectionError("connection failed")


class TimeoutSearchService:
    def search(self, params: SearchParams):
        raise OpenSearchConnectionTimeout("timed out")


class NotFoundSearchService:
    def search(self, params: SearchParams):
        raise OpenSearchNotFoundError(404, "index_not_found_exception", {})


class SuccessfulLawsService:
    def list_laws(self):
        return ["刑法", "民法"]


class SuccessfulLawDocumentService:
    def law_document(self, law_id: str, article=None, context=None):
        return {
            "law_id": law_id,
            "law_name": "民法",
            "sections": [{"article_no": article or "1", "text": "本文"}],
        }


class MissingLawDocumentService:
    def law_document(self, law_id: str, article=None, context=None):
        return None


class ConnectionErrorLawsService:
    def list_laws(self):
        raise OpenSearchConnectionError("connection failed")


def post_search(service_class, payload=None):
    view = SearchView.as_view(service_class=service_class)
    request = APIRequestFactory().post(
        "/api/search",
        payload or {"q": "損害", "mode": "literal", "filters": {}, "size": 20, "page": 1},
        format="json",
    )
    request.request_id = "req-test"
    return view(request)


def get_laws(service_class):
    view = LawsView.as_view(service_class=service_class)
    request = APIRequestFactory().get("/api/laws")
    request.request_id = "req-test"
    return view(request)


def get_law_document(service_class, law_id="minpo"):
    view = LawDocumentView.as_view(service_class=service_class)
    request = APIRequestFactory().get(f"/api/laws/{law_id}")
    request.request_id = "req-test"
    return view(request, law_id=law_id)


def post_search_debug(service_class):
    view = SearchDebugView.as_view(service_class=service_class)
    request = APIRequestFactory().post(
        "/api/search-debug",
        {"q": "損害", "mode": "keyword", "filters": {}, "size": 20, "page": 1},
        format="json",
    )
    return view(request)


def test_search_view_returns_success_payload():
    response = post_search(SuccessfulSearchService)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["hits"] == []
    assert response.data["index"]["name"] == "laws"


def test_search_debug_view_returns_query_dsl_when_debug(monkeypatch):
    monkeypatch.setattr("search.views.settings.DEBUG", True)
    response = post_search_debug(SuccessfulSearchService)

    assert response.status_code == status.HTTP_200_OK
    assert "query_dsl" in response.data


def test_search_view_connection_error_returns_503_with_request_id():
    response = post_search(ConnectionErrorSearchService)

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.data["request_id"] == "req-test"


def test_search_view_timeout_returns_503_with_request_id():
    response = post_search(TimeoutSearchService)

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.data["request_id"] == "req-test"


def test_search_view_index_missing_returns_503_with_request_id():
    response = post_search(NotFoundSearchService)

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.data["request_id"] == "req-test"


def test_search_view_window_overflow_returns_400():
    response = post_search(SuccessfulSearchService, {"q": "損害", "size": 100, "page": 101})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "page" in response.data


def test_laws_view_returns_laws():
    response = get_laws(SuccessfulLawsService)

    assert response.status_code == status.HTTP_200_OK
    assert response.data == {"laws": ["刑法", "民法"]}


def test_laws_view_connection_error_returns_503_with_request_id():
    response = get_laws(ConnectionErrorLawsService)

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.data["request_id"] == "req-test"


def test_law_document_view_returns_document():
    response = get_law_document(SuccessfulLawDocumentService)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["law_id"] == "minpo"
    assert response.data["sections"][0]["text"] == "本文"


def test_law_document_view_accepts_article_filter():
    view = LawDocumentView.as_view(service_class=SuccessfulLawDocumentService)
    request = APIRequestFactory().get("/api/laws/minpo?article=709&context=1")
    request.request_id = "req-test"
    response = view(request, law_id="minpo")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["sections"][0]["article_no"] == "709"


def test_law_document_view_rejects_context_out_of_range():
    view = LawDocumentView.as_view(service_class=SuccessfulLawDocumentService)
    request = APIRequestFactory().get("/api/laws/minpo?article=709&context=-1")
    request.request_id = "req-test"
    response = view(request, law_id="minpo")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "context" in response.data


def test_law_document_view_returns_404_when_missing():
    response = get_law_document(MissingLawDocumentService)

    assert response.status_code == status.HTTP_404_NOT_FOUND
