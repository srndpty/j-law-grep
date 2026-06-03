from __future__ import annotations

from django.conf import settings
from opensearchpy import ConnectionError as OpenSearchConnectionError
from opensearchpy import ConnectionTimeout as OpenSearchConnectionTimeout
from opensearchpy import NotFoundError as OpenSearchNotFoundError
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import SearchRequestSerializer, SearchResponseSerializer
from .service import SearchParams, SearchService

OPENSEARCH_UNAVAILABLE_EXCEPTIONS = (
    OpenSearchConnectionError,
    OpenSearchConnectionTimeout,
    OpenSearchNotFoundError,
)


class SearchView(APIView):
    service_class = SearchService

    def post(self, request) -> Response:
        serializer = SearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        service = self.service_class()
        params = SearchParams(
            q=data["q"],
            mode=data.get("mode", "literal"),
            filters=data.get("filters", {}),
            size=data.get("size", 20),
            page=data.get("page", 1),
        )
        try:
            result = service.search(params)
        except ValueError as exc:
            raise ValidationError({"q": str(exc)}) from exc
        except OPENSEARCH_UNAVAILABLE_EXCEPTIONS:
            # OpenSearch unreachable or timed out: a transient backend problem,
            # not a client error. Surface 503 with the request id for debugging
            # instead of a generic 500.
            return Response(
                {
                    "detail": "検索バックエンドに接続できませんでした。時間をおいて再試行してください。",
                    "request_id": getattr(request, "request_id", None),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        response_serializer = SearchResponseSerializer(result)
        return Response(response_serializer.data)


class LawsView(APIView):
    service_class = SearchService

    def get(self, request) -> Response:
        service = self.service_class()
        try:
            laws = service.list_laws()
        except OPENSEARCH_UNAVAILABLE_EXCEPTIONS:
            return Response(
                {
                    "detail": "検索バックエンドに接続できませんでした。時間をおいて再試行してください。",
                    "request_id": getattr(request, "request_id", None),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"laws": laws})


class EnsureIndexView(APIView):
    service_class = SearchService

    def post(self, request) -> Response:
        if settings.REINDEX_TOKEN:
            token = request.headers.get("X-Ensure-Index-Token", "") or request.headers.get(
                "X-Reindex-Token", ""
            )
            if token != settings.REINDEX_TOKEN:
                raise PermissionDenied("Invalid ensure-index token.")
        elif not settings.DEBUG:
            raise PermissionDenied(
                "Ensure-index endpoint requires REINDEX_TOKEN when DEBUG is disabled."
            )
        service = self.service_class()
        service.ensure_index()
        return Response({"status": "ok"}, status=status.HTTP_202_ACCEPTED)
