from __future__ import annotations
import ast, json
from pathlib import Path
import pytest
from axiom_engine.estimate_data import EstimateDataImportError, import_estimate_data, validate_estimate_data

def payload(company_id="company:US-NVDA"):
    return {"schema_version":"1.0.0","provider_id":"provider:test","provider_name":"Test","as_of_date":"2026-07-23","provenance":[{"provenance_id":"provenance:test:1","provider_id":"provider:test","source_type":"manual_fixture","source_name":"fixture","source_record_id":"1","retrieved_at":"2026-07-23T00:00:00Z"}],"estimates":[{"estimate_id":"estimate:test:revenue:2027","company_id":company_id,"metric":"revenue","value":"100","unit":"currency","currency":"USD","period_end":"2027-12-31","fiscal_year":2027,"fiscal_period":"FY","estimate_kind":"consensus_mean","analyst_count":3,"provenance_ids":["provenance:test:1"]}],"forward_assumptions":[{"assumption_id":"forward_assumption:test:growth:3y","company_id":company_id,"metric":"revenue_growth_rate","value":"0.2","unit":"ratio","effective_date":"2026-07-23","horizon_years":3,"assumption_type":"research_assumption","status":"proposed","provenance_ids":["provenance:test:1"]}]}

def write(path,p): path.write_text(json.dumps(p),encoding="utf-8")
def registry(path,cid="company:US-NVDA"): path.mkdir(); write(path/"companies.json",[{"company_id":cid}])

def test_dry_run_default(tmp_path):
    s=tmp_path/"s.json"; write(s,payload()); r=tmp_path/"r"; registry(r); o=tmp_path/"out"
    report=import_estimate_data(s,output_dir=o,company_registry_dir=r)
    assert report.dry_run and not o.exists()

def test_write_canonical_bundle(tmp_path):
    s=tmp_path/"s.json"; write(s,payload()); r=tmp_path/"r"; registry(r); o=tmp_path/"out"
    report=import_estimate_data(s,output_dir=o,company_registry_dir=r,dry_run=False)
    assert report.estimates_found==1 and report.assumptions_found==1
    assert sorted(x.name for x in o.iterdir())==["estimates.json","forward_assumptions.json","manifest.json","provenance.json"]
    assert validate_estimate_data(o)["estimate_count"]==1

def test_missing_company_rejected(tmp_path):
    s=tmp_path/"s.json"; write(s,payload("company:US-MISSING")); r=tmp_path/"r"; registry(r)
    with pytest.raises(EstimateDataImportError,match="missing from registry"): import_estimate_data(s,company_registry_dir=r)

def test_valuation_fields_rejected(tmp_path):
    p=payload(); p["fair_value"]=123; s=tmp_path/"s.json"; write(s,p)
    with pytest.raises(EstimateDataImportError,match="forbidden"): import_estimate_data(s,company_registry_dir=None)

def test_currency_requires_code(tmp_path):
    p=payload(); del p["estimates"][0]["currency"]; s=tmp_path/"s.json"; write(s,p)
    with pytest.raises(EstimateDataImportError,match="currency"): import_estimate_data(s,company_registry_dir=None)

def test_empty_source_rejected(tmp_path):
    p=payload(); p["estimates"]=[]; p["forward_assumptions"]=[]; s=tmp_path/"s.json"; write(s,p)
    with pytest.raises(EstimateDataImportError,match="at least one"): import_estimate_data(s,company_registry_dir=None)

def test_no_legacy_or_valuation_imports():
    root=Path(__file__).parents[1]/"src"/"axiom_engine"/"estimate_data"; forbidden={"yfinance","research_report","legacy_valuation","valuation_engine"}; imports=set()
    for p in root.glob("*.py"):
        tree=ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n,ast.Import): imports.update(x.name for x in n.names)
            elif isinstance(n,ast.ImportFrom) and n.module: imports.add(n.module)
    assert not any(any(part in name for part in forbidden) for name in imports)

def test_provider_agnostic_model():
    from axiom_engine.estimate_data.models import EstimateDataSource
    fields=set(EstimateDataSource.model_fields)
    assert {"provider_id","estimates","forward_assumptions"} <= fields
    assert not ({"fmp","polygon","yfinance","sec"} & fields)
