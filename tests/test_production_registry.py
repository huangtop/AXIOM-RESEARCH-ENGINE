from pathlib import Path
import json
import pytest
from axiom_engine.production_registry import ProductionRegistryError, build_production_registry, validate_production_registry
FIXTURE=Path(__file__).resolve().parents[1]/"examples"/"production_registry_fixture"

def test_build_valid_registry(tmp_path):
    r=build_production_registry(source_dir=FIXTURE/"valid", output_dir=tmp_path, write=True)
    assert r["valid"] is True and r["company_count"]==2 and r["security_count"]==3
    companies=json.loads((tmp_path/"companies.json").read_text())
    assert companies[0]["company_id"].startswith("company:")

def test_dual_listing_has_one_primary(tmp_path):
    build_production_registry(source_dir=FIXTURE/"valid", output_dir=tmp_path, write=True)
    securities=json.loads((tmp_path/"securities.json").read_text())
    acme=[x for x in securities if x["company_id"]=="company:US-CIK0000000001"]
    assert len(acme)==2 and sum(x["primary_listing"] for x in acme)==1

def test_diagnostics_detect_bad_source(tmp_path):
    r=build_production_registry(source_dir=FIXTURE/"invalid", output_dir=tmp_path, write=True)
    assert r["valid"] is False
    codes={x["code"] for x in json.loads((tmp_path/"registry_diagnostics.json").read_text())}
    assert {"ticker_collision","missing_exchange","invalid_provenance"} <= codes

def test_strict_rejects_errors(tmp_path):
    with pytest.raises(ProductionRegistryError):
        build_production_registry(source_dir=FIXTURE/"invalid", output_dir=tmp_path, write=True, strict=True)

def test_validator(tmp_path):
    build_production_registry(source_dir=FIXTURE/"valid", output_dir=tmp_path, write=True)
    assert validate_production_registry(output_dir=tmp_path)["valid"] is True
