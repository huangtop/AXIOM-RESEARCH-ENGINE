from __future__ import annotations

import json
from pathlib import Path

from axiom_engine.etf_exposure_api import ETFExposureService
from axiom_engine.valuation_http import ValuationWSGIApp


ROOT = Path(__file__).resolve().parents[1]


def _write(root: Path, relative: str, payload) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _fixture(tmp_path: Path) -> ETFExposureService:
    exposures = [
        {"company_id":"company:1","etf_id":"US-LOW","etf_ticker":"LOW","etf_name":"Low","etf_name_en":"Low","portfolio_weight":0.05,"portfolio_weight_percent":5.0,"as_of":None,"as_of_status":"unavailable_provider_did_not_supply","source_status":"top_holdings_only"},
        {"company_id":"company:1","etf_id":"US-HIGH","etf_ticker":"HIGH","etf_name":"High","etf_name_en":"High","portfolio_weight":0.20,"portfolio_weight_percent":20.0,"as_of":"2026-07-28","as_of_status":"available","source_status":"top_holdings_only"},
    ]
    _write(tmp_path, "data/generated/canonical_etf_exposure/manifest.json", {"schema_version":"canonical-etf-exposure.v031e.1","source_snapshot":{"snapshot_id":"s1","provider_generated_at":"2026-07-28T00:00:00+00:00"},"summary":{"source_status":"top_holdings_only"}})
    _write(tmp_path, "data/generated/canonical_etf_exposure/etf_exposures.json", exposures)
    _write(tmp_path, "data/generated/canonical_etf_exposure/indexes.json", {"company_id_to_exposure_positions":{"company:1":[0,1]}})
    _write(tmp_path, "data/universe/companies.json", [{"company_id":"company:1","display_name":"Test Corp"},{"company_id":"company:2","display_name":"Empty Corp"}])
    _write(tmp_path, "data/universe/securities.json", [{"security_id":"security:1","company_id":"company:1","ticker":"TEST"},{"security_id":"security:2","company_id":"company:2","ticker":"EMPTY"}])
    _write(tmp_path, "data/generated/security_identity/security_identity_normalization.json", {"schema_version":"security-identity-normalization.v031v.2","securities":[{"security_id":"security:1","instrument_type":"common_or_ordinary_equity"},{"security_id":"security:2","instrument_type":"common_or_ordinary_equity"}]})
    return ETFExposureService(root=tmp_path)


def _get(app: ValuationWSGIApp, path: str):
    observed = {}
    def start_response(status, headers): observed["status"] = status
    body = b"".join(app({"REQUEST_METHOD":"GET","PATH_INFO":path}, start_response))
    return observed["status"], json.loads(body)


def test_company_exposures_are_sorted_and_weight_semantics_are_explicit(tmp_path: Path):
    payload = _fixture(tmp_path).get("test")
    assert [row["etf_ticker"] for row in payload["exposures"]] == ["HIGH", "LOW"]
    assert payload["summary"] == {"holding_etf_count":2,"maximum_portfolio_weight":0.2,"maximum_portfolio_weight_percent":20.0,"as_of_available_count":1,"as_of_unavailable_count":1}
    assert payload["source"]["source_status"] == "top_holdings_only"
    assert "not ETF ownership" in payload["source"]["interpretation"]


def test_known_company_without_exposure_returns_200_empty_not_404(tmp_path: Path):
    status, payload = _get(ValuationWSGIApp(etf_exposure_service=_fixture(tmp_path)), "/v1/companies/EMPTY/etf-exposure")
    assert status == "200 OK"
    assert payload["status"] == "unavailable"
    assert payload["reason_code"] == "NO_TOP_HOLDINGS_EXPOSURE_OBSERVED"
    assert payload["exposures"] == []


def test_http_route_returns_exposure_and_unknown_company_404(tmp_path: Path):
    app = ValuationWSGIApp(etf_exposure_service=_fixture(tmp_path))
    status, payload = _get(app, "/v1/companies/TEST/etf-exposure")
    missing_status, missing = _get(app, "/v1/companies/MISSING/etf-exposure")
    assert status == "200 OK"
    assert payload["exposures"][0]["etf_ticker"] == "HIGH"
    assert missing_status == "404 Not Found"
    assert missing["error"] == "company_not_found"


def test_real_nvda_api_projection_contains_smh_weight():
    payload = ETFExposureService(root=ROOT).get("NVDA")
    smh = next(row for row in payload["exposures"] if row["etf_id"] == "US-SMH")
    assert smh["portfolio_weight"] == 0.177539
    assert smh["portfolio_weight_percent"] == 17.7539
    assert payload["summary"]["holding_etf_count"] > 1
