import json
from pathlib import Path
import pytest
from axiom_engine.valuation_engine import ValuationEngineError, build_valuation_engine, write_valuation_engine

METHODS = ["forward_pe", "trailing_pe", "price_to_sales", "ev_to_sales", "ev_to_ebitda", "fcf_yield", "dcf"]

def write(path: Path, payload): path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(payload), encoding="utf-8")

def source():
    derived = {
      "forward_pe": {"current_multiple": 6}, "trailing_pe": {"current_multiple": 8},
      "price_to_sales": {"revenue_per_share": 10, "current_multiple": 1.2},
      "ev_to_sales": {"current_multiple": 1.4}, "ev_to_ebitda": {"current_multiple": 7},
      "fcf_yield": {"current_yield": .1, "current_yield_percent": 10},
      "dcf": {"free_cash_flow_per_share": 1.2, "revenue_per_share": 10, "current_price": 12},
    }
    methods = {m: {"status":"prepared","confidence":"medium","formula_version":f"{m}.source.v1","reason":"ok","stale_inputs":[],"raw_inputs":{"x":{"value":1,"provider":"test","confidence":"medium","source_state":"primary"}},"derived_inputs":derived[m]} for m in METHODS}
    return {"schema_version":"valuation-method-inputs.v030.12.2","as_of_date":"2026-07-27","companies":[{"company_id":"company:1","primary_symbol":"AAA","methods":methods}]}

def build(tmp_path): write(tmp_path/"input.json", source()); return build_valuation_engine(tmp_path, input_path="input.json")

def test_calculates_all_seven(tmp_path):
    row=build(tmp_path)["companies"][0]; assert row["engine_state"]=="fully_calculated"; assert row["calculated_method_count"]==7

def test_forward_pe_payload(tmp_path):
    m=build(tmp_path)["companies"][0]["methods"]["forward_pe"]; assert m["status"]=="calculated"; assert m["metrics"]=={"current_multiple":6}

def test_price_to_sales_metrics(tmp_path): assert build(tmp_path)["companies"][0]["methods"]["price_to_sales"]["metrics"]["revenue_per_share"]==10

def test_dcf_metrics(tmp_path): assert build(tmp_path)["companies"][0]["methods"]["dcf"]["metrics"]["current_price"]==12

def test_confidence_and_source_formula_propagate(tmp_path):
    m=build(tmp_path)["companies"][0]["methods"]["forward_pe"]; assert m["confidence"]=="medium"; assert m["source_formula_version"]=="forward_pe.source.v1"

def test_engine_formula_version(tmp_path): assert build(tmp_path)["companies"][0]["methods"]["forward_pe"]["formula_version"]=="forward-pe-engine.v1"

def test_blocked_method_has_no_metrics(tmp_path):
    s=source(); s["companies"][0]["methods"]["forward_pe"]={"status":"blocked","formula_version":"forward-pe-inputs.v1","reason":"missing"}; write(tmp_path/"input.json",s)
    r=build_valuation_engine(tmp_path,input_path="input.json"); assert r["companies"][0]["methods"]["forward_pe"]["metrics"]=={}; assert r["summary"]["blocked_method_record_count"]==1

def test_incomplete_prepared_is_invalid(tmp_path):
    s=source(); s["companies"][0]["methods"]["forward_pe"]["derived_inputs"]={}; write(tmp_path/"input.json",s)
    r=build_valuation_engine(tmp_path,input_path="input.json"); assert r["summary"]["invalid_method_record_count"]==1

def test_rejects_bad_schema(tmp_path):
    write(tmp_path/"input.json",{"schema_version":"bad","companies":[]})
    with pytest.raises(ValuationEngineError): build_valuation_engine(tmp_path,input_path="input.json")

def test_write_outputs(tmp_path):
    r=build(tmp_path); out=tmp_path/"out.json"; diag=tmp_path/"diag.json"; write_valuation_engine(r,out,diag)
    assert json.loads(out.read_text())["version"]=="V030.13.0"; assert json.loads(diag.read_text())["schema_version"]=="valuation-engine-diagnostic.v030.13.0"
