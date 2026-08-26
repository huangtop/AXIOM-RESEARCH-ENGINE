import io
import json

from axiom_engine.valuation_http import ValuationWSGIApp


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

class UnifiedFullMarketStub:
    def get(self, symbol):
        return {
            "valuation": {
                "unified_contract": {
                    "contract_version": "unified-valuation.v1",
                    "symbol": symbol,
                    "headline": {
                        "base_fair_value": "123.45",
                    },
                }
            }
        }


class CoverageStub:
    def require_public(self, symbol, capability=None):
        return None


def test_unified_valuation_endpoint_uses_full_market_contract():
    app = ValuationWSGIApp(
        full_market_service=UnifiedFullMarketStub(),
        coverage_service=CoverageStub(),
    )
    observed, body = call(
        app,
        "POST",
        "/v1/valuations",
        {"symbol": "NVDA"},
    )
    assert observed["status"] == "200 OK"
    assert body["contract_version"] == "unified-valuation.v1"
    assert body["symbol"] == "NVDA"
    assert body["headline"]["base_fair_value"] == "123.45"


def test_legacy_debug_endpoint_is_retired():
    app = ValuationWSGIApp(
        full_market_service=UnifiedFullMarketStub(),
        coverage_service=CoverageStub(),
    )
    observed, body = call(
        app,
        "POST",
        "/v1/debug/valuations/legacy-parity",
        {"symbol": "NVDA"},
    )
    assert observed["status"] == "404 Not Found"
    assert body["error"] == "not_found"

