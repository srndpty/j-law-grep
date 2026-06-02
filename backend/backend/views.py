from __future__ import annotations

from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET

from search.open_search_client import OpenSearchBackend

from .observability import request_metrics


@require_GET
def healthz(request) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@require_GET
def readyz(request) -> JsonResponse:
    backend = OpenSearchBackend()
    try:
        health = backend.cluster_health()
        concrete_indices = backend.indices_for_alias(backend.index) or [backend.index]
        payload = {
            "status": "ok",
            "opensearch": {
                "status": health.get("status"),
                "cluster_name": health.get("cluster_name"),
            },
            "index": {
                "name": backend.index,
                "concrete": concrete_indices,
            },
        }
        return JsonResponse(payload)
    except Exception as exc:
        return JsonResponse(
            {
                "status": "error",
                "error": str(exc),
            },
            status=503,
        )


@require_GET
def metrics(request) -> HttpResponse:
    snapshot = request_metrics.snapshot()
    body = "\n".join(
        [
            "# HELP jlaw_http_requests_total Total HTTP requests handled by Django.",
            "# TYPE jlaw_http_requests_total counter",
            f"jlaw_http_requests_total {snapshot.total}",
            "# HELP jlaw_http_5xx_total Total HTTP 5xx responses handled by Django.",
            "# TYPE jlaw_http_5xx_total counter",
            f"jlaw_http_5xx_total {snapshot.errors}",
            "# HELP jlaw_http_request_latency_ms_sum Sum of HTTP request latency in milliseconds.",
            "# TYPE jlaw_http_request_latency_ms_sum counter",
            f"jlaw_http_request_latency_ms_sum {snapshot.latency_ms_sum:.3f}",
            "",
        ]
    )
    return HttpResponse(body, content_type="text/plain; version=0.0.4; charset=utf-8")
