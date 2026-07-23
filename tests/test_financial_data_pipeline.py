from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from axiom_engine.financial_data import FinancialDataImportError, import_financial_data, validate_financial_data


def source_payload(company_id: str = "company:US-NVDA") -> dict:
    return {
        "schema_version": "1.0.0", "provider_id": "provider:test", "provider_name": "Test",
        "as_of_date": "2026-07-23",
        "provenance": [{"provenance_id": "provenance:test:1", "provider_id": "provider:test", "source_type": "manual_fixture", "source_name": "fixture", "source_record_id": "1", "retrieved_at": "2026-07-23T00:00:00Z"}],
        "facts": [{"financial_fact_id": "financial_fact:test:revenue:2025", "company_id": company_id, "metric": "revenue", "value": "100", "unit": "currency", "currency": "USD", "period_type": "duration", "period_start": "2025-01-01", "period_end": "2025-12-31", "fiscal_year": 2025, "fiscal_period": "FY", "statement": "income_statement", "provenance_ids": ["provenance:test:1"]}],
    }


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_registry(path: Path, company_id: str = "company:US-NVDA") -> None:
    path.mkdir()
    write_json(path / "companies.json", [{"company_id": company_id}])


def test_import_is_dry_run_by_default(tmp_path: Path) -> None:
    source = tmp_path / "source.json"; write_json(source, source_payload())
    registry = tmp_path / "registry"; write_registry(registry)
    output = tmp_path / "out"
    report = import_financial_data(source, output_dir=output, company_registry_dir=registry)
    assert report.dry_run is True and not output.exists()


def test_write_outputs_only_financial_bundle(tmp_path: Path) -> None:
    source = tmp_path / "source.json"; write_json(source, source_payload())
    registry = tmp_path / "registry"; write_registry(registry)
    output = tmp_path / "out"
    report = import_financial_data(source, output_dir=output, company_registry_dir=registry, dry_run=False)
    assert report.facts_found == 1
    assert sorted(x.name for x in output.iterdir()) == ["financial_facts.json", "manifest.json", "provenance.json"]
    assert validate_financial_data(output)["fact_count"] == 1


def test_rejects_missing_company(tmp_path: Path) -> None:
    source = tmp_path / "source.json"; write_json(source, source_payload("company:US-MISSING"))
    registry = tmp_path / "registry"; write_registry(registry)
    with pytest.raises(FinancialDataImportError, match="missing from registry"):
        import_financial_data(source, company_registry_dir=registry)


def test_rejects_valuation_and_estimate_fields(tmp_path: Path) -> None:
    payload = source_payload(); payload["valuation"] = {"fair_value": 1}
    source = tmp_path / "source.json"; write_json(source, payload)
    with pytest.raises(FinancialDataImportError, match="forbidden"):
        import_financial_data(source, company_registry_dir=None)


def test_duration_fact_requires_period_start(tmp_path: Path) -> None:
    payload = source_payload(); del payload["facts"][0]["period_start"]
    source = tmp_path / "source.json"; write_json(source, payload)
    with pytest.raises(FinancialDataImportError, match="period_start"):
        import_financial_data(source, company_registry_dir=None)


def test_currency_fact_requires_currency(tmp_path: Path) -> None:
    payload = source_payload(); del payload["facts"][0]["currency"]
    source = tmp_path / "source.json"; write_json(source, payload)
    with pytest.raises(FinancialDataImportError, match="currency"):
        import_financial_data(source, company_registry_dir=None)


def test_module_has_no_legacy_or_yfinance_imports() -> None:
    root = Path(__file__).parents[1] / "src" / "axiom_engine" / "financial_data"
    forbidden = {"yfinance", "research_report", "legacy_valuation", "yahoo_market_data"}
    imports: set[str] = set()
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imports.update(x.name for x in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module: imports.add(node.module)
    assert not any(any(part in name for part in forbidden) for name in imports)


def test_source_schema_is_provider_agnostic() -> None:
    from axiom_engine.financial_data.models import FinancialDataSource
    fields = set(FinancialDataSource.model_fields)
    assert "provider_id" in fields and "facts" in fields
    assert not ({"sec", "fmp", "polygon", "yfinance"} & fields)
