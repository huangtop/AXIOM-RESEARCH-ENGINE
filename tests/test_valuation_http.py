import io
import json
from datetime import date
from decimal import Decimal

from axiom_engine.previous_close import DailyClose
from axiom_engine.valuation_api import LegacyValuationAPIService
from axiom_engine.valuation_http import ValuationWSGIApp


class CloseProvider:
    def previous_close(self, symbol, *, as_of=None):
        return DailyClose(
            symbol,
            date(2026, 7, 21),
            Decimal("205.47"),
            "USD",
            "America/New_York",
        )


def call(app, method, path, payload=None):
    raw = json.dumps(payload).encode() if payload is not None else b""
    env = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": io.BytesIO(raw),
    }
    observed = {}

    def start(status, headers):
        observed.update(status=status, headers=dict(headers))

    body = b"".join(app(env, start))
    return observed, json.loads(body)


def test_health():
    observed, body = call(ValuationWSGIApp(), "GET", "/health")
    assert observed["status"] == "200 OK"
    assert body == {"status": "ok"}


def test_debug_legacy_parity_endpoint():
    app = ValuationWSGIApp(
        legacy_service=LegacyValuationAPIService(CloseProvider())
    )
    observed, body = call(
        app,
        "POST",
        "/v1/debug/valuations/legacy-parity",
        {
            "symbol": "NVDA",
            "research_payload": {
                "market_consensus_eps_forward": 6,
                "market_consensus_eps_current": 4,
                "growth_estimate": 0.3,
            },
        },
    )

    assert observed["status"] == "200 OK"
    assert observed["headers"]["Cache-Control"] == "no-store"
    assert body["endpoint_mode"] == "debug_only"
    assert body["models"]["peg"]["fair_value"] == "162.00"


def test_debug_legacy_parity_bad_request():
    app = ValuationWSGIApp(
        legacy_service=LegacyValuationAPIService(CloseProvider())
    )
    observed, body = call(
        app,
        "POST",
        "/v1/debug/valuations/legacy-parity",
        {"symbol": "NVDA"},
    )

    assert observed["status"] == "400 Bad Request"
    assert body["error"] == "invalid_request"
