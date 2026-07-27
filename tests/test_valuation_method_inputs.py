import json
from pathlib import Path

import pytest

from axiom_engine.valuation_method_inputs import ValuationMethodInputsError, build_valuation_method_inputs, write_valuation_method_inputs


def write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def sources():
    company = {
        "company_id": "company:1", "cik": "1", "primary_symbol": "AAA", "display_name": "AAA", "input_state": "ready",
        "financial_freshness_state": "current",
        "market": {"previous_close": {"value": 12, "provider": "yahoo_finance", "confidence": "high", "freshness_state": "fresh", "source_state": "completed_session_close"}},
        "financial_metrics": {
            "forward_eps": {"value": 2, "provider": "yahoo_finance", "confidence": "medium"},
            "trailing_eps": {"value": 1.5, "provider": "yahoo_finance", "confidence": "medium"},
            "revenue": {"value": 1000, "provider": "sec_companyfacts", "confidence": "high"},
            "diluted_shares_outstanding": {"value": 100, "provider": "sec_companyfacts", "confidence": "high"},
            "enterprise_value": {"value": 1400, "provider": "yahoo_finance", "confidence": "medium"},
            "ebitda": {"value": 200, "provider": "yahoo_finance", "confidence": "medium"},
            "market_cap": {"value": 1200, "provider": "yahoo_finance", "confidence": "medium"},
            "free_cash_flow": {"value": 120, "provider": "yahoo_finance", "confidence": "medium"}
        }
    }
    methods = {name: {"status": "eligible", "confidence": "medium", "reason": "all_required_inputs_available", "missing_inputs": [], "invalid_inputs": [], "stale_inputs": []} for name in ["forward_pe", "trailing_pe", "price_to_sales", "ev_to_sales", "ev_to_ebitda", "fcf_yield", "dcf"]}
    eligibility = {"schema_version": "valuation-method-eligibility.v030.12.1", "companies": [{"company_id": "company:1", "methods": methods}]}
    snapshot = {"schema_version": "valuation-input-snapshot.v030.12.0", "as_of_date": "2026-07-27", "companies": [company]}
    return snapshot, eligibility


def build(tmp_path):
    snapshot, eligibility = sources()
    write(tmp_path / "input.json", snapshot)
    write(tmp_path / "eligibility.json", eligibility)
    return build_valuation_method_inputs(tmp_path, input_path="input.json", eligibility_path="eligibility.json")


def test_prepares_all_seven_methods(tmp_path):
    row = build(tmp_path)["companies"][0]
    assert row["method_input_state"] == "fully_prepared"
    assert row["prepared_method_count"] == 7


def test_forward_pe_current_multiple(tmp_path):
    method = build(tmp_path)["companies"][0]["methods"]["forward_pe"]
    assert method["derived_inputs"]["current_multiple"] == 6.0


def test_price_to_sales_derives_per_share_and_multiple(tmp_path):
    method = build(tmp_path)["companies"][0]["methods"]["price_to_sales"]
    assert method["derived_inputs"] == {"revenue_per_share": 10.0, "current_multiple": 1.2}


def test_ev_and_fcf_derivations(tmp_path):
    methods = build(tmp_path)["companies"][0]["methods"]
    assert methods["ev_to_sales"]["derived_inputs"]["current_multiple"] == 1.4
    assert methods["ev_to_ebitda"]["derived_inputs"]["current_multiple"] == 7.0
    assert methods["fcf_yield"]["derived_inputs"]["current_yield_percent"] == 10.0


def test_dcf_builds_per_share_bases(tmp_path):
    derived = build(tmp_path)["companies"][0]["methods"]["dcf"]["derived_inputs"]
    assert derived["free_cash_flow_per_share"] == 1.2
    assert derived["revenue_per_share"] == 10.0
    assert derived["current_price"] == 12


def test_blocked_method_is_not_calculated(tmp_path):
    snapshot, eligibility = sources()
    eligibility["companies"][0]["methods"]["forward_pe"] = {"status": "blocked", "reason": "missing_required_inputs", "missing_inputs": ["forward_eps"], "invalid_inputs": [], "stale_inputs": []}
    write(tmp_path / "input.json", snapshot); write(tmp_path / "eligibility.json", eligibility)
    report = build_valuation_method_inputs(tmp_path, input_path="input.json", eligibility_path="eligibility.json")
    assert report["companies"][0]["methods"]["forward_pe"]["status"] == "blocked"
    assert report["summary"]["blocked_method_record_count"] == 1


def test_rejects_company_set_mismatch(tmp_path):
    snapshot, eligibility = sources(); eligibility["companies"][0]["company_id"] = "company:2"
    write(tmp_path / "input.json", snapshot); write(tmp_path / "eligibility.json", eligibility)
    with pytest.raises(ValuationMethodInputsError):
        build_valuation_method_inputs(tmp_path, input_path="input.json", eligibility_path="eligibility.json")


def test_write_snapshot_and_diagnostic(tmp_path):
    report = build(tmp_path)
    output = tmp_path / "out/report.json"; diagnostic = tmp_path / "out/diag.json"
    write_valuation_method_inputs(report, output, diagnostic)
    assert json.loads(output.read_text())["version"] == "V030.12.2"
    assert json.loads(diagnostic.read_text())["schema_version"] == "valuation-method-inputs-diagnostic.v030.12.2"
