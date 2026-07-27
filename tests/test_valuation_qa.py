import copy
import json
from pathlib import Path

import pytest

from axiom_engine.valuation_qa import ValuationQAError, run_valuation_qa, write_valuation_qa

METHODS = ["forward_pe", "trailing_pe", "price_to_sales", "ev_to_sales", "ev_to_ebitda", "fcf_yield", "dcf"]
FORMULAS = {
    "forward_pe": "forward-pe-inputs.v1", "trailing_pe": "trailing-pe-inputs.v1",
    "price_to_sales": "price-to-sales-inputs.v1", "ev_to_sales": "ev-to-sales-inputs.v1",
    "ev_to_ebitda": "ev-to-ebitda-inputs.v1", "fcf_yield": "fcf-yield-inputs.v1", "dcf": "dcf-base-inputs.v1",
}

def write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(payload), encoding="utf-8")

def raw(value, provider="yahoo_finance", name="x"):
    result = {"value": value, "provider": provider, "confidence": "medium", "source_state": "fallback"}
    if provider == "yahoo_finance": result["source_field"] = name
    else: result["source_fact_ids"] = ["fact:1"]
    return result

def sources():
    raws = {
      "forward_pe": {"previous_close": raw(12, name="previous_close"), "forward_eps": raw(2, name="forward_eps")},
      "trailing_pe": {"previous_close": raw(12, name="previous_close"), "trailing_eps": raw(1.5, name="trailing_eps")},
      "price_to_sales": {"previous_close": raw(12, name="previous_close"), "revenue": raw(1000, "sec_companyfacts"), "diluted_shares_outstanding": raw(100, "sec_companyfacts")},
      "ev_to_sales": {"enterprise_value": raw(1400, name="enterprise_value"), "revenue": raw(1000, "sec_companyfacts")},
      "ev_to_ebitda": {"enterprise_value": raw(1400, name="enterprise_value"), "ebitda": raw(200, name="ebitda")},
      "fcf_yield": {"market_cap": raw(1200, name="market_cap"), "free_cash_flow": raw(120, name="free_cash_flow")},
      "dcf": {"previous_close": raw(12, name="previous_close"), "free_cash_flow": raw(120, name="free_cash_flow"), "revenue": raw(1000, "sec_companyfacts"), "diluted_shares_outstanding": raw(100, "sec_companyfacts")},
    }
    derived = {
      "forward_pe": {"current_multiple": 6}, "trailing_pe": {"current_multiple": 8},
      "price_to_sales": {"revenue_per_share": 10, "current_multiple": 1.2},
      "ev_to_sales": {"current_multiple": 1.4}, "ev_to_ebitda": {"current_multiple": 7},
      "fcf_yield": {"current_yield": .1, "current_yield_percent": 10},
      "dcf": {"free_cash_flow_per_share": 1.2, "revenue_per_share": 10, "current_price": 12},
    }
    e_methods = {m: {"status": "eligible", "confidence": "medium"} for m in METHODS}
    i_methods = {m: {"status": "prepared", "confidence": "medium", "formula_version": FORMULAS[m], "raw_inputs": raws[m], "derived_inputs": derived[m]} for m in METHODS}
    eligibility = {"schema_version": "valuation-method-eligibility.v030.12.1", "companies": [{"company_id": "company:1", "methods": e_methods}]}
    inputs = {"schema_version": "valuation-method-inputs.v030.12.2", "summary": {"prepared_method_record_count": 7, "blocked_method_record_count": 0, "invalid_method_record_count": 0}, "companies": [{"company_id": "company:1", "methods": i_methods}]}
    return eligibility, inputs

def run(tmp_path, mutate=None):
    e, i = sources()
    if mutate: mutate(e, i)
    write(tmp_path/"e.json", e); write(tmp_path/"i.json", i)
    return run_valuation_qa(tmp_path, eligibility_path="e.json", method_inputs_path="i.json")

def test_clean_report_passes_all_gates(tmp_path):
    report = run(tmp_path); assert report["summary"]["status"] == "pass"; assert set(report["gates"].values()) == {"pass"}

def test_detects_status_mismatch(tmp_path):
    report = run(tmp_path, lambda e, i: i["companies"][0]["methods"]["forward_pe"].update(status="blocked")); assert report["gates"]["eligibility_consistency"] == "fail"

def test_detects_formula_version_error(tmp_path):
    report = run(tmp_path, lambda e, i: i["companies"][0]["methods"]["forward_pe"].update(formula_version="bad")); assert report["gates"]["formula_integrity"] == "fail"

def test_detects_calculation_error(tmp_path):
    report = run(tmp_path, lambda e, i: i["companies"][0]["methods"]["ev_to_sales"]["derived_inputs"].update(current_multiple=9)); assert report["gates"]["derived_calculation"] == "fail"

def test_detects_provenance_error(tmp_path):
    def mutate(e, i): del i["companies"][0]["methods"]["ev_to_sales"]["raw_inputs"]["revenue"]["source_fact_ids"]
    assert run(tmp_path, mutate)["gates"]["provider_provenance"] == "fail"

def test_detects_confidence_error(tmp_path):
    report = run(tmp_path, lambda e, i: i["companies"][0]["methods"]["forward_pe"].update(confidence="high")); assert report["gates"]["confidence_propagation"] == "fail"

def test_blocked_method_must_not_be_calculated(tmp_path):
    def mutate(e, i):
        e["companies"][0]["methods"]["forward_pe"]["status"] = "blocked"
        i["companies"][0]["methods"]["forward_pe"].update(status="blocked", raw_inputs={}, derived_inputs={"current_multiple": 6})
    assert run(tmp_path, mutate)["gates"]["blocked_method_safety"] == "fail"

def test_rejects_company_set_mismatch(tmp_path):
    e, i = sources(); i["companies"][0]["company_id"] = "company:2"; write(tmp_path/"e.json", e); write(tmp_path/"i.json", i)
    with pytest.raises(ValuationQAError): run_valuation_qa(tmp_path, eligibility_path="e.json", method_inputs_path="i.json")

def test_writes_report(tmp_path):
    report = run(tmp_path); path = tmp_path/"out/report.json"; write_valuation_qa(report, path); assert json.loads(path.read_text())["version"] == "V030.12.3"
