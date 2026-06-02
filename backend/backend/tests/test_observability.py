import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

OBSERVABILITY_PATH = Path(__file__).resolve().parents[1] / "observability.py"
spec = importlib.util.spec_from_file_location("observability_under_test", OBSERVABILITY_PATH)
observability = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["observability_under_test"] = observability
spec.loader.exec_module(observability)

RequestIdMiddleware = observability.RequestIdMiddleware
RequestMetrics = observability.RequestMetrics


class DummyResponse(dict):
    status_code = 200


def test_request_metrics_records_totals():
    metrics = RequestMetrics()
    metrics.record(200, 12.5)
    metrics.record(503, 7.5)

    snapshot = metrics.snapshot()
    assert snapshot.total == 2
    assert snapshot.errors == 1
    assert snapshot.latency_ms_sum == 20.0


def test_request_id_middleware_sets_response_header():
    def get_response(request):
        return DummyResponse()

    request = SimpleNamespace(
        headers={"X-Request-ID": "req-1"},
        method="GET",
        path="/healthz",
    )
    middleware = RequestIdMiddleware(get_response)

    response = middleware(request)

    assert response["X-Request-ID"] == "req-1"
    assert request.request_id == "req-1"
