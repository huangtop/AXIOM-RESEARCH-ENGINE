from pathlib import Path
import json
import pytest
from axiom_engine.production_build import build_production, validate_production, ProductionBuildError
FIX=Path(__file__).parents[1]/"examples/full_production_fixture"
def test_full_build_write(tmp_path):
    m=build_production(registry_source_dir=FIX/"registry",financial_source_dir=FIX/"financial",market_source_dir=FIX/"market",estimate_source_dir=FIX/"estimate",output_dir=tmp_path,write=True,strict=True)
    assert m["valid"] and m["counts"]=={"companies":1,"securities":1,"financial_facts":3,"market_snapshots":2,"estimates":3}
    assert (tmp_path/"production_build_manifest.json").exists()
def test_validate_full_build(tmp_path):
    build_production(registry_source_dir=FIX/"registry",financial_source_dir=FIX/"financial",market_source_dir=FIX/"market",estimate_source_dir=FIX/"estimate",output_dir=tmp_path,write=True,strict=True)
    assert validate_production(output_dir=tmp_path)["valid"]
def test_dry_run_writes_nothing(tmp_path):
    m=build_production(registry_source_dir=FIX/"registry",financial_source_dir=FIX/"financial",market_source_dir=FIX/"market",estimate_source_dir=FIX/"estimate",output_dir=tmp_path,write=False)
    assert m["dry_run"] and list(tmp_path.iterdir()) == []
def test_missing_source_fails(tmp_path):
    with pytest.raises(ProductionBuildError):
        build_production(registry_source_dir=tmp_path/"missing",financial_source_dir=FIX/"financial",market_source_dir=FIX/"market",estimate_source_dir=FIX/"estimate",output_dir=tmp_path/"out",write=True)
def test_validate_missing_build(tmp_path):
    r=validate_production(output_dir=tmp_path)
    assert not r["valid"] and r["errors"]
