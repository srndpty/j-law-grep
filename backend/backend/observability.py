from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger("jlaw.requests")


@dataclass
class RequestSnapshot:
    total: int
    errors: int
    latency_ms_sum: float


class RequestMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.total = 0
        self.errors = 0
        self.latency_ms_sum = 0.0

    def record(self, status_code: int, latency_ms: float) -> None:
        with self._lock:
            self.total += 1
            if status_code >= 500:
                self.errors += 1
            self.latency_ms_sum += latency_ms

    def snapshot(self) -> RequestSnapshot:
        with self._lock:
            return RequestSnapshot(
                total=self.total,
                errors=self.errors,
                latency_ms_sum=self.latency_ms_sum,
            )


request_metrics = RequestMetrics()


class RequestIdMiddleware:
    def __init__(self, get_response: Callable) -> None:
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.request_id = request_id
        started = time.perf_counter()
        try:
            response = self.get_response(request)
        except Exception:
            latency_ms = (time.perf_counter() - started) * 1000
            request_metrics.record(500, latency_ms)
            logger.exception(
                self._log_payload(request, request_id, 500, latency_ms),
            )
            raise
        latency_ms = (time.perf_counter() - started) * 1000
        response["X-Request-ID"] = request_id
        request_metrics.record(response.status_code, latency_ms)
        logger.info(self._log_payload(request, request_id, response.status_code, latency_ms))
        return response

    @staticmethod
    def _log_payload(request, request_id: str, status_code: int, latency_ms: float) -> str:
        return json.dumps(
            {
                "request_id": request_id,
                "method": request.method,
                "path": request.path,
                "status": status_code,
                "latency_ms": round(latency_ms, 2),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
