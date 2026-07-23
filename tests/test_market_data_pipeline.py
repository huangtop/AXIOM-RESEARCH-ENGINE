from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from axiom_engine.market_data import MarketDataImportError, import_market_data, validate_market_data


def payload() -> dict:
    return {
        "schema_version": "1.0.0", "provider_id": "provider:test", "provider_name": "Test", "as_of_date": "2026-07-23",
        "provenance": [{"provenance_id": "provenance:test:1", "provider_id": "provider:test", "source_type": "manual_fixture", "source_name": "fixture", "source_record_id": "1", "retrieved_at": "2026-07-23T21:00:00Z"}],
        "observations": [{"market_observation_id": "market_observation:test:price", "company_id": "company:US-AAPL", "security_id": "security:US-AAPL", "metric": "current_price", "value": "200", "unit": "currency", "currency": "USD", "observed_at": "2026-07-23T20:00:00Z", "trading_date": "2026-07-23", "session": "regular", "provenance_ids": ["provenance:test:1"]}],
        "trading_statuses": [{"trading_status_id": "trading_status:test:1", "company_id": "company:US-AAPL", "security_id": "security:US-AAPL", "status": "active", "observed_at": "2026-07-23T20:00:00Z", "trading_date": "2026-07-23", "provenance_ids": ["provenance:test:1"]}],
    }


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def write_registry(path: Path) -> None:
    path.mkdir()
    write_json(path / "companies.json", [{"company_id": "company:US-AAPL"}])
    write_json(path / "securities.json", [{"security_id": "security:US-AAPL", "company_id": "company:US-AAPL"}])


def test_import_is_dry_run_by_default(tmp_path: Path) -> None:
    source=tmp_path/"source.json"; write_json(source,payload()); registry=tmp_path/"registry"; write_registry(registry)
    output=tmp_path/"out"; report=import_market_data(source,output_dir=output,company_registry_dir=registry)
    assert report.dry_run is True and not output.exists()


def test_write_and_validate_bundle(tmp_path: Path) -> None:
    source=tmp_path/"source.json"; write_json(source,payload()); registry=tmp_path/"registry"; write_registry(registry)
    output=tmp_path/"out"; report=import_market_data(source,output_dir=output,company_registry_dir=registry,dry_run=False)
    assert report.observations_found == 1
    assert sorted(x.name for x in output.iterdir()) == ["manifest.json","market_observations.json","provenance.json","trading_statuses.json"]
    assert validate_market_data(output)["security_count"] == 1


def test_rejects_missing_security(tmp_path: Path) -> None:
    source=tmp_path/"source.json"; write_json(source,payload()); registry=tmp_path/"registry"; registry.mkdir(); write_json(registry/"companies.json",[{"company_id":"company:US-AAPL"}]); write_json(registry/"securities.json",[])
    with pytest.raises(MarketDataImportError,match="securities missing"):
        import_market_data(source,company_registry_dir=registry)


def test_rejects_valuation_fields(tmp_path: Path) -> None:
    value=payload(); value["fair_value"]="300"; source=tmp_path/"source.json"; write_json(source,value)
    with pytest.raises(MarketDataImportError,match="forbidden"):
        import_market_data(source,company_registry_dir=None)


def test_currency_metric_requires_currency(tmp_path: Path) -> None:
    value=payload(); del value["observations"][0]["currency"]; source=tmp_path/"source.json"; write_json(source,value)
    with pytest.raises(MarketDataImportError,match="currency"):
        import_market_data(source,company_registry_dir=None)


def test_shares_metric_rejects_currency(tmp_path: Path) -> None:
    value=payload(); item=value["observations"][0]; item.update(metric="shares_outstanding",unit="shares",currency="USD")
    source=tmp_path/"source.json"; write_json(source,value)
    with pytest.raises(MarketDataImportError,match="shares_outstanding"):
        import_market_data(source,company_registry_dir=None)


def test_module_is_provider_agnostic_and_has_no_legacy_imports() -> None:
    root=Path(__file__).parents[1]/"src"/"axiom_engine"/"market_data"; imports=set()
    for path in root.glob("*.py"):
        tree=ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node,ast.Import): imports.update(x.name for x in node.names)
            elif isinstance(node,ast.ImportFrom) and node.module: imports.add(node.module)
    forbidden={"yfinance","yahoo_market_data","legacy_valuation","research_report"}
    assert not any(any(part in name for part in forbidden) for name in imports)


def test_source_model_has_generic_provider_contract() -> None:
    from axiom_engine.market_data.models import MarketDataSource
    fields=set(MarketDataSource.model_fields)
    assert {"provider_id","observations","provenance"} <= fields
    assert not ({"polygon","fmp","yfinance","alpha_vantage"} & fields)
