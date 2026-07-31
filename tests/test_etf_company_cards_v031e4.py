from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from axiom_engine.etf_company_cards import build_etf_company_cards, write_etf_company_cards
from axiom_engine.etf_company_card_api import ETFCompanyCardService
from axiom_engine.valuation_http import ValuationWSGIApp


NOW = datetime(2026, 7, 29, tzinfo=timezone.utc)


def _write(root: Path, relative: str, payload) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(root: Path) -> None:
    _write(root, "data/universe/securities.json", [
        {"company_id":"company:MU","ticker":"MU","primary_listing":True},
        {"company_id":"company:MISSING","ticker":"MISSING","primary_listing":True},
    ])
    _write(root, "data/generated/coverage_policy/coverage_policy.json", {
        "schema_version":"coverage-policy-projection.v031f.1",
        "contract":{"unlisted_company_default_tier":"contextual"},
        "records":[{
            "company_id":"company:MU","ticker":"MU","publication_tier":"core",
            "publication":{"company_page":True,"valuation_card":True,"visibility":"public"}
        }],
        "indexes":{"ticker_to_company_id":{"MU":"company:MU"},"company_id_to_position":{"company:MU":0}}
    })
    _write(root, "data/generated/canonical_etf_exposure/manifest.json", {"schema_version":"canonical-etf-exposure.v031e.1","source_snapshot":{"provider_generated_at":"2026-07-28T00:00:00Z"}})
    _write(root, "data/generated/canonical_etf_exposure/coverage_audit.json", {"source_etf_ids":["US-QQQ","US-EMPTY","TW-0050"]})
    _write(root, "data/generated/canonical_etf_exposure/etf_exposures.json", [
        {"company_id":"company:MU","security_id":"security:NASDAQ-MU","holding_symbol":"MU","etf_id":"US-QQQ","etf_ticker":"QQQ","portfolio_weight":0.005,"portfolio_weight_percent":0.5,"as_of":None,"as_of_status":"unavailable_provider_did_not_supply","source_status":"top_holdings_only"},
        {"company_id":"company:TW","security_id":"security:TW-2330","holding_symbol":"2330.TW","etf_id":"TW-0050","portfolio_weight":0.5,"portfolio_weight_percent":50},
        {"company_id":"company:MISSING","security_id":"security:NASDAQ-MISSING","holding_symbol":"MISSING","etf_id":"US-QQQ","portfolio_weight":0.001,"portfolio_weight_percent":0.1},
    ])
    valuation = {"schema_version":"full-market-valuation-card.v031.0","company":{"company_id":"company:MU","display_name":"Micron Technology"},"primary_security":{"ticker":"MU","exchange":"NASDAQ","currency":"USD"},"market":{"status":"ready","current_price":"100","currency":"USD","as_of_date":"2026-07-27","reason_code":None},"valuation":{"status":"ready","fair_value":"125","calculated_model_count":5,"total_model_count":7,"reason_code":None,"aggregation_version":"equal-weight-calculated-models.v031v.5"}}
    _write(root, "data/generated/full_market_coverage/full_market_coverage.json", {"schema_version":"full-market-coverage.v031.0","generated_at":"2026-07-29T00:00:00Z","cards":[valuation]})


def _get(app, path: str):
    status = []
    body = b"".join(app({"REQUEST_METHOD":"GET","PATH_INFO":path}, lambda value, headers: status.append(value)))
    return status[0], json.loads(body)


def test_projection_keeps_holdings_when_valuation_is_unavailable_and_excludes_tw(tmp_path: Path):
    _fixture(tmp_path)
    report = build_etf_company_cards(tmp_path, now=NOW)
    assert len(report["cards"]) == 2
    mu = next(card for card in report["cards"] if card["security"]["ticker"] == "MU")
    missing = next(card for card in report["cards"] if card["security"]["ticker"] == "MISSING")
    assert mu["valuation"]["upside_percent"] == 25.0
    assert mu["valuation"]["calculated_model_count"] == 5
    assert missing["valuation"]["status"] == "not_covered"
    assert missing["valuation"]["reason_code"] == "COVERAGE_POLICY_VALUATION_WITHHELD"
    assert missing["coverage_policy"]["publication_tier"] == "contextual"
    assert report["summary"]["valuation_readiness_used_for_membership"] is False
    assert all(card["etf_id"].startswith("US-") for card in report["cards"])


def test_api_returns_cards_and_known_empty_etf(tmp_path: Path):
    _fixture(tmp_path)
    report = build_etf_company_cards(tmp_path, now=NOW)
    write_etf_company_cards(report, tmp_path / "data/generated/etf_company_cards")
    service = ETFCompanyCardService(root=tmp_path)
    qqq = service.get("QQQ")
    empty = service.get("EMPTY")
    assert qqq["summary"]["company_card_count"] == 2
    assert empty["status"] == "unavailable"
    assert empty["reason_code"] == "NO_RESOLVED_US_COMPANY_HOLDINGS"


def test_wsgi_exposes_etf_company_cards(tmp_path: Path):
    _fixture(tmp_path)
    write_etf_company_cards(build_etf_company_cards(tmp_path, now=NOW), tmp_path / "data/generated/etf_company_cards")
    app = ValuationWSGIApp(etf_company_card_service=ETFCompanyCardService(root=tmp_path))
    status, payload = _get(app, "/v1/etfs/QQQ/company-cards")
    assert status.startswith("200")
    assert payload["company_cards"][0]["etf_id"] == "US-QQQ"
