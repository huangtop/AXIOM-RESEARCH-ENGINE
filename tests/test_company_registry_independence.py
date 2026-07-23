from __future__ import annotations

import json
from pathlib import Path

import pytest

from axiom_engine.company_registry import import_company_universe, load_company_universe_source
from axiom_engine.company_registry.importer import CompanyRegistryImportError, OUTPUT_FILES


def source_payload() -> dict:
    return {
        "schema_version": "1.0.0",
        "as_of_date": "2026-07-23",
        "source_name": "official-test-source",
        "provenance": [{
            "provenance_id": "provenance:official-test:NVDA",
            "source_type": "regulator",
            "source_name": "Official Test",
            "source_record_id": "NVDA",
            "retrieved_at": "2026-07-23T00:00:00Z"
        }],
        "companies": [{
            "company_id": "company:US-CIK0001045810",
            "legal_name": "NVIDIA Corporation",
            "country": "US",
            "official_sector": "Information Technology",
            "official_industry": "Semiconductors",
            "business_description": "Designs accelerated computing platforms.",
            "provenance_ids": ["provenance:official-test:NVDA"]
        }],
        "securities": [{
            "security_id": "security:NASDAQ-NVDA",
            "company_id": "company:US-CIK0001045810",
            "exchange": "NASDAQ",
            "ticker": "NVDA",
            "currency": "USD",
            "primary_listing": True,
            "provenance_ids": ["provenance:official-test:NVDA"]
        }]
    }


def test_import_is_dry_run_by_default(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    output = tmp_path / "registry"
    source.write_text(json.dumps(source_payload()), encoding="utf-8")
    report = import_company_universe(source, output_dir=output)
    assert report.dry_run is True
    assert not output.exists()


def test_write_creates_only_independent_registry_files(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    output = tmp_path / "registry"
    source.write_text(json.dumps(source_payload()), encoding="utf-8")
    report = import_company_universe(source, output_dir=output, dry_run=False)
    assert {path.name for path in output.iterdir()} == set(OUTPUT_FILES)
    assert report.companies_found == 1
    combined = "".join(path.read_text(encoding="utf-8") for path in output.iterdir())
    for forbidden in ("current_price", "revenue_ttm", "logic_type", "default_params"):
        assert forbidden not in combined


@pytest.mark.parametrize("field", [
    "current_price", "revenue_ttm", "EPS", "analyst_target", "growth_estimate",
    "shares_outstanding", "enterprise_value", "logic_type", "default_params",
])
def test_forbidden_legacy_market_fields_are_rejected(tmp_path: Path, field: str) -> None:
    payload = source_payload()
    payload["companies"][0][field] = "legacy-value"
    source = tmp_path / "source.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CompanyRegistryImportError, match="forbidden"):
        load_company_universe_source(source)


def test_security_must_reference_registry_company(tmp_path: Path) -> None:
    payload = source_payload()
    payload["securities"][0]["company_id"] = "company:US-MISSING"
    source = tmp_path / "source.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CompanyRegistryImportError, match="missing company"):
        load_company_universe_source(source)


def test_new_registry_module_has_no_legacy_pipeline_dependencies() -> None:
    import ast

    root = Path(__file__).resolve().parents[1] / "src" / "axiom_engine" / "company_registry"
    imported: set[str] = set()
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    forbidden_imports = ("yfinance", "research_report", "legacy_valuation", "yahoo_market_data")
    for forbidden in forbidden_imports:
        assert all(forbidden not in name for name in imported)
