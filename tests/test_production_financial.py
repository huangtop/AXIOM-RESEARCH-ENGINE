from __future__ import annotations

import json
from pathlib import Path

import pytest

from axiom_engine.production_financial import (
    ProductionFinancialError,
    build_production_financials,
    validate_production_financials,
)


FIXTURE = Path(__file__).parents[1] / "examples" / "production_financial_fixture"


def _registry(tmp_path: Path) -> Path:
    root = tmp_path / "registry"
    root.mkdir()
    (root / "companies.json").write_text(
        json.dumps([{"company_id": "company:US-CIK0000320193"}]), encoding="utf-8"
    )
    return root


def test_valid_import_dry_run(tmp_path: Path) -> None:
    result = build_production_financials(
        source_dir=FIXTURE / "valid",
        output_dir=tmp_path / "out",
        registry_dir=_registry(tmp_path),
    )
    assert result["valid"] is True
    assert result["fact_count"] == 3
    assert result["company_count"] == 1
    assert result["dry_run"] is True
    assert not (tmp_path / "out").exists()


def test_write_and_validate(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    output = tmp_path / "out"
    result = build_production_financials(
        source_dir=FIXTURE / "valid",
        output_dir=output,
        registry_dir=registry,
        write=True,
        strict=True,
    )
    assert result["dry_run"] is False
    validation = validate_production_financials(output_dir=output, registry_dir=registry)
    assert validation["valid"] is True
    facts = json.loads((output / "financial_facts.json").read_text())
    revenue = next(row for row in facts if row["concept"] == "revenue")
    assert revenue["value"] == "391035000000"
    assert revenue["company_id"] == "company:US-CIK0000320193"


def test_invalid_company_link_is_reported(tmp_path: Path) -> None:
    result = build_production_financials(
        source_dir=FIXTURE / "invalid",
        output_dir=tmp_path / "out",
        registry_dir=_registry(tmp_path),
    )
    assert result["valid"] is False
    assert result["errors"] >= 1


def test_strict_invalid_import_raises(tmp_path: Path) -> None:
    with pytest.raises(ProductionFinancialError):
        build_production_financials(
            source_dir=FIXTURE / "invalid",
            registry_dir=_registry(tmp_path),
            strict=True,
        )


def test_missing_source_raises(tmp_path: Path) -> None:
    with pytest.raises(ProductionFinancialError, match="source directory not found"):
        build_production_financials(source_dir=tmp_path / "missing", registry_dir=None)
