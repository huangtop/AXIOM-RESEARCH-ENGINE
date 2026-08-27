from __future__ import annotations

from io import BytesIO
import json

from axiom_engine.valuation_http import ValuationWSGIApp


class StubFullMarketService:
    def __init__(self, payload):
        self.payload = payload

    def get(self, symbol):
        return {
            "valuation": {
                "unified_contract": {
                    **self.payload,
                    "symbol": symbol,
                }
            }
        }


class StubCoverageService:
    def require_public(self, symbol, *, capability=None):
        return {"symbol": symbol, "capability": capability}


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


def invoke_get(app, path, *, etag=None):
    result = []
    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": path}
    if etag:
        environ["HTTP_IF_NONE_MATCH"] = etag
    body = b"".join(app(environ, lambda status, headers: result.append((status, dict(headers)))))
    return result[0], body


def test_production_route_is_v1_valuations():
    app = ValuationWSGIApp(
        full_market_service=StubFullMarketService({"contract_version": "unified-valuation.v1"}),
        coverage_service=StubCoverageService(),
    )
    status, payload = invoke(app, "/v1/valuations", {"symbol": "NVDA"})
    assert status.startswith("200")
    assert payload["contract_version"] == "unified-valuation.v1"
    assert payload["symbol"] == "NVDA"


def test_retired_legacy_debug_route_is_removed():
    app = ValuationWSGIApp(
        full_market_service=StubFullMarketService({}),
        coverage_service=StubCoverageService(),
    )
    status, _ = invoke(
        app,
        "/v1/debug/valuations/legacy-parity",
        {"symbol": "NVDA"},
    )
    assert status.startswith("404")


def test_old_legacy_route_is_removed():
    app = ValuationWSGIApp(
        full_market_service=StubFullMarketService({}),
        coverage_service=StubCoverageService(),
    )
    status, _ = invoke(app, "/v1/valuations/legacy", {"symbol": "NVDA"})
    assert status.startswith("404")


def test_production_valuation_route_accepts_basic_market_company():
    app = ValuationWSGIApp(
        full_market_service=StubFullMarketService({"contract_version": "unified-valuation.v1"}),
        coverage_service=StubCoverageService(),
    )
    status, payload = invoke(app, "/v1/valuations", {"symbol": "F"})
    assert status.startswith("200")
    assert payload["contract_version"] == "unified-valuation.v1"
    assert payload["symbol"] == "F"


def test_publication_files_use_etag_and_immutable_cache(tmp_path):
    publication = tmp_path / "publication"
    companies = publication / "companies"
    companies.mkdir(parents=True)
    (publication / "manifest.json").write_text('{"release_id":"abc"}\n')
    (companies / "NVDA.abc.json").write_text('{"ticker":"NVDA"}\n')
    app = ValuationWSGIApp(publication_root=publication)

    (manifest_status, manifest_headers), _ = invoke_get(app, "/v1/publication/manifest.json")
    assert manifest_status.startswith("200")
    assert manifest_headers["Cache-Control"] == "public, max-age=60, must-revalidate"
    etag = manifest_headers["ETag"]
    (cached_status, _), cached_body = invoke_get(
        app, "/v1/publication/manifest.json", etag=etag
    )
    assert cached_status.startswith("304")
    assert cached_body == b""
    (weak_cached_status, _), weak_cached_body = invoke_get(
        app, "/v1/publication/manifest.json", etag=f"W/{etag}"
    )
    assert weak_cached_status.startswith("304")
    assert weak_cached_body == b""

    (shard_status, shard_headers), shard_body = invoke_get(
        app, "/v1/publication/companies/NVDA.abc.json"
    )
    assert shard_status.startswith("200")
    assert shard_headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert json.loads(shard_body)["ticker"] == "NVDA"
