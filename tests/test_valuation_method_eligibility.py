import json
from pathlib import Path

import pytest

from axiom_engine.valuation_eligibility import ValuationEligibilityError, build_valuation_method_eligibility, write_valuation_method_eligibility


def write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def company(symbol="AAA", market_freshness="fresh", financial_freshness="current"):
    metrics = {
        "forward_eps": {"value": 2, "provider": "yahoo_finance", "confidence": "medium"},
        "trailing_eps": {"value": 1.5, "provider": "yahoo_finance", "confidence": "medium"},
        "revenue": {"value": 1000, "provider": "sec_companyfacts", "confidence": "high"},
        "diluted_shares_outstanding": {"value": 100, "provider": "sec_companyfacts", "confidence": "high"},
        "enterprise_value": {"value": 1400, "provider": "yahoo_finance", "confidence": "medium"},
        "ebitda": {"value": 200, "provider": "yahoo_finance", "confidence": "medium"},
        "market_cap": {"value": 1200, "provider": "yahoo_finance", "confidence": "medium"},
        "free_cash_flow": {"value": 120, "provider": "yahoo_finance", "confidence": "medium"},
    }
    return {
        "company_id": "company:1", "primary_symbol": symbol, "input_state": "ready",
        "financial_freshness_state": financial_freshness,
        "market": {"previous_close": {"value": 12, "provider": "yahoo_finance", "confidence": "high", "freshness_state": market_freshness}},
        "financial_metrics": metrics,
    }


def build(tmp_path, companies=None):
    write(tmp_path / "input.json", {"schema_version": "valuation-input-snapshot.v030.12.0", "as_of_date": "2026-07-27", "companies": companies or [company()]})
    return build_valuation_method_eligibility(tmp_path, input_path="input.json")


def test_all_seven_methods_eligible(tmp_path):
    report = build(tmp_path)
    row = report["companies"][0]
    assert row["eligibility_state"] == "fully_eligible"
    assert row["eligible_method_count"] == 7


def test_forward_pe_requires_price_and_positive_forward_eps(tmp_path):
    row = company()
    row["financial_metrics"]["forward_eps"]["value"] = -1
    result = build(tmp_path, [row])["companies"][0]["methods"]["forward_pe"]
    assert result["status"] == "blocked"
    assert result["invalid_inputs"] == ["forward_eps"]


def test_price_to_sales_requires_diluted_shares(tmp_path):
    row = company()
    del row["financial_metrics"]["diluted_shares_outstanding"]
    result = build(tmp_path, [row])["companies"][0]["methods"]["price_to_sales"]
    assert result["missing_inputs"] == ["diluted_shares_outstanding"]


def test_fcf_yield_allows_negative_free_cash_flow(tmp_path):
    row = company()
    row["financial_metrics"]["free_cash_flow"]["value"] = -20
    result = build(tmp_path, [row])["companies"][0]["methods"]["fcf_yield"]
    assert result["status"] == "eligible"


def test_dcf_requires_positive_free_cash_flow(tmp_path):
    row = company()
    row["financial_metrics"]["free_cash_flow"]["value"] = -20
    result = build(tmp_path, [row])["companies"][0]["methods"]["dcf"]
    assert result["status"] == "blocked"
    assert "free_cash_flow" in result["invalid_inputs"]


def test_stale_inputs_lower_confidence_without_blocking(tmp_path):
    report = build(tmp_path, [company(market_freshness="stale", financial_freshness="stale")])
    result = report["companies"][0]["methods"]["forward_pe"]
    assert result["status"] == "eligible"
    assert result["confidence"] == "low"
    assert set(result["stale_inputs"]) == {"forward_eps", "previous_close"}


def test_rejects_wrong_schema(tmp_path):
    write(tmp_path / "input.json", {"schema_version": "wrong", "companies": []})
    with pytest.raises(ValuationEligibilityError):
        build_valuation_method_eligibility(tmp_path, input_path="input.json")


def test_write_snapshot_and_diagnostic(tmp_path):
    report = build(tmp_path)
    output = tmp_path / "out/report.json"
    diagnostic = tmp_path / "out/diag.json"
    write_valuation_method_eligibility(report, output, diagnostic)
    assert json.loads(output.read_text())["version"] == "V030.12.1"
    assert json.loads(diagnostic.read_text())["schema_version"] == "valuation-method-eligibility-diagnostic.v030.12.1"
