from __future__ import annotations
import json
from pathlib import Path
import pytest
from axiom_engine.production_estimate import ProductionEstimateError, build_production_estimates, validate_production_estimates
FIXTURE=Path(__file__).parents[1]/"examples"/"production_estimate_fixture"
def _registry(tmp_path:Path)->Path:
    root=tmp_path/"registry"; root.mkdir()
    (root/"companies.json").write_text(json.dumps([{"company_id":"company:US-CIK0000320193"}]),encoding="utf-8")
    (root/"securities.json").write_text(json.dumps([{"security_id":"security:NASDAQ-AAPL","company_id":"company:US-CIK0000320193"}]),encoding="utf-8")
    return root
def test_build_valid_dry_run(tmp_path:Path)->None:
    result=build_production_estimates(source_dir=FIXTURE/"valid",registry_dir=_registry(tmp_path))
    assert result["valid"] is True and result["estimate_count"]==3 and result["metric_count"]==3 and result["dry_run"] is True
def test_build_write_and_validate(tmp_path:Path)->None:
    registry=_registry(tmp_path); out=tmp_path/"estimates"
    result=build_production_estimates(source_dir=FIXTURE/"valid",registry_dir=registry,output_dir=out,write=True,strict=True)
    assert result["valid"] is True
    payload=json.loads((out/"consensus_estimates.json").read_text())
    revenue=next(r for r in payload if r["metric"]=="revenue")
    assert revenue["estimate_id"].startswith("estimate:") and revenue["mean"]=="410000000000"
    validation=validate_production_estimates(output_dir=out,registry_dir=registry)
    assert validation["valid"] is True and validation["estimate_count"]==3
def test_invalid_strict_raises(tmp_path:Path)->None:
    with pytest.raises(ProductionEstimateError): build_production_estimates(source_dir=FIXTURE/"invalid",registry_dir=_registry(tmp_path),strict=True)
def test_invalid_non_strict_reports_errors(tmp_path:Path)->None:
    result=build_production_estimates(source_dir=FIXTURE/"invalid",registry_dir=_registry(tmp_path))
    assert result["valid"] is False and result["errors"]>=5
def test_validate_missing_output(tmp_path:Path)->None:
    result=validate_production_estimates(output_dir=tmp_path/"missing",registry_dir=_registry(tmp_path))
    assert result["valid"] is False and any("missing file" in e for e in result["errors"])
