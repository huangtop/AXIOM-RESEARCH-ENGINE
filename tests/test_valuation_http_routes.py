from __future__ import annotations

from io import BytesIO
import json

from axiom_engine.valuation_http import ValuationWSGIApp


class StubService:
    def __init__(self, payload): self.payload = payload
    def calculate(self, request): return {**self.payload, "request": request}


def invoke(app, path, payload):
    body = json.dumps(payload).encode()
    status = []
    environ = {
        "REQUEST_METHOD": "POST", "PATH_INFO": path,
        "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": BytesIO(body),
    }
    response = b"".join(app(environ, lambda value, headers: status.append(value)))
    return status[0], json.loads(response)


def test_production_route_is_v1_valuations():
    app = ValuationWSGIApp(StubService({"endpoint_mode": "production"}), StubService({"endpoint_mode": "debug_only"}))
    status, payload = invoke(app, "/v1/valuations", {"symbol": "NVDA"})
    assert status.startswith("200")
    assert payload["endpoint_mode"] == "production"


def test_legacy_route_is_debug_namespaced():
    app = ValuationWSGIApp(StubService({"endpoint_mode": "production"}), StubService({"endpoint_mode": "debug_only"}))
    status, payload = invoke(app, "/v1/debug/valuations/legacy-parity", {"symbol": "NVDA"})
    assert status.startswith("200")
    assert payload["endpoint_mode"] == "debug_only"


def test_old_legacy_route_is_removed():
    app = ValuationWSGIApp(StubService({}), StubService({}))
    status, _ = invoke(app, "/v1/valuations/legacy", {"symbol": "NVDA"})
    assert status.startswith("404")
