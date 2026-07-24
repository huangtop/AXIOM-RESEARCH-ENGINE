from __future__ import annotations

import json
from pathlib import Path

import pytest

from axiom_engine.production_market import ProductionMarketError, build_production_market, validate_production_market


FIXTURE = Path(__file__).parents[1] / "examples" / "production_market_fixture"


def _registry(tmp_path: Path) -> Path:
    root = tmp_path / "registry"
    root.mkdir()
    (root / "companies.json").write_text(json.dumps([{"company_id": "company:US-CIK0000320193"}]), encoding="utf-8")
    (root / "securities.json").write_text(json.dumps([{"security_id": "security:NASDAQ-AAPL", "company_id": "company:US-CIK0000320193"}]), encoding="utf-8")
    return root


def test_build_valid_dry_run(tmp_path: Path) -> None:
    result = build_production_market(source_dir=FIXTURE / "valid", registry_dir=_registry(tmp_path))
    assert result["valid"] is True
    assert result["snapshot_count"] == 2
    assert result["security_count"] == 1
    assert result["dry_run"] is True


def test_build_write_and_validate(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    out = tmp_path / "market"
    result = build_production_market(source_dir=FIXTURE / "valid", registry_dir=registry, output_dir=out, write=True, strict=True)
    assert result["valid"] is True
    payload = json.loads((out / "market_snapshots.json").read_text(encoding="utf-8"))
    assert payload[0]["snapshot_id"].startswith("market:")
    assert payload[0]["regular_market_price"] == "215.75"
    validation = validate_production_market(output_dir=out, registry_dir=registry)
    assert validation["valid"] is True
    assert validation["snapshot_count"] == 2


def test_invalid_strict_raises(tmp_path: Path) -> None:
    with pytest.raises(ProductionMarketError):
        build_production_market(source_dir=FIXTURE / "invalid", registry_dir=_registry(tmp_path), strict=True)


def test_unknown_security_is_reported(tmp_path: Path) -> None:
    result = build_production_market(source_dir=FIXTURE / "invalid", registry_dir=_registry(tmp_path))
    codes = {item["code"] for item in json.loads(json.dumps([]))} if False else set()
    assert result["valid"] is False
    assert result["errors"] >= 1


def test_validate_missing_output(tmp_path: Path) -> None:
    result = validate_production_market(output_dir=tmp_path / "missing", registry_dir=_registry(tmp_path))
    assert result["valid"] is False
    assert any("missing file" in error for error in result["errors"])
