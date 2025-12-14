from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import SearchRequestSerializer, SearchResponseSerializer
from .service import SearchParams, SearchService


class SearchView(APIView):
    service_class = SearchService

    def post(self, request) -> Response:  # type: ignore[override]
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
        result = service.search(params)
        response_serializer = SearchResponseSerializer(result)
        return Response(response_serializer.data)


class ReindexView(APIView):
    service_class = SearchService

    def post(self, request) -> Response:  # type: ignore[override]
        service = self.service_class()
        service.ensure_index()
        return Response({"status": "ok"}, status=status.HTTP_202_ACCEPTED)
