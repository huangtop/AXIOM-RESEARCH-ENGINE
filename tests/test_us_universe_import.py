from __future__ import annotations

import json
from pathlib import Path

import pytest

from axiom_engine.us_universe_import import (
    build_us_universe_import,
    load_source_snapshot,
    transform_us_source_records,
)
from axiom_engine.us_universe_sources import USListingSourceRecord, USUniverseSourceError


def record(ticker: str, exchange: str, *, cik: int | None, name: str) -> USListingSourceRecord:
    return USListingSourceRecord(
        ticker=ticker,
        exchange=exchange,
        security_name=name,
        cik=cik,
        legal_name=f"{name} Legal" if cik else None,
        source_ids=("official:test",),
    )


def test_same_cik_groups_multiple_listings_into_one_company() -> None:
    bundle = transform_us_source_records([
        record("ACME", "NASDAQ", cik=123, name="Acme Inc. - Common Stock"),
        record("ACM.A", "NYSE", cik=123, name="Acme Inc. Class A"),
    ])
    assert len(bundle.companies) == 1
    assert len(bundle.securities) == 2
    assert bundle.companies[0].company_id == "company:US-CIK0000000123"
    assert bundle.companies[0].primary_security_id == "security:NASDAQ-ACME"
    assert sum(item.primary_listing for item in bundle.securities) == 1


def test_missing_cik_uses_deterministic_listing_company_id() -> None:
    bundle = transform_us_source_records(
        [record("XYZ", "NYSE_AMERICAN", cik=None, name="XYZ Corp")]
    )
    assert bundle.companies[0].company_id == "company:US-NYSE-AMERICAN-XYZ"
    assert bundle.securities[0].company_id == bundle.companies[0].company_id


def test_transform_emits_no_valuation_assignments() -> None:
    bundle = transform_us_source_records([record("ACME", "NASDAQ", cik=123, name="Acme")])
    assert bundle.valuation_profile_assignments == ()
    assert bundle.companies[0].research_level.value == "none"


def test_load_source_snapshot_rejects_invalid_contract(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text('{"records": [42]}', encoding="utf-8")
    with pytest.raises(USUniverseSourceError, match="must be an object"):
        load_source_snapshot(source)


def test_build_writes_importer_compatible_json(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    output = tmp_path / "import.json"
    source.write_text(json.dumps({
        "schema_version": "1.0.0",
        "records": [{
            "ticker": "ACME",
            "exchange": "NASDAQ",
            "security_name": "Acme Inc. - Common Stock",
            "cik": 123,
            "legal_name": "Acme Inc.",
            "source_ids": ["nasdaq_trader:nasdaqlisted", "sec:company_tickers"],
        }],
    }), encoding="utf-8")
    report = build_us_universe_import(source, output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert report.company_count == 1
    assert report.security_count == 1
    assert payload["companies"][0]["company_id"] == "company:US-CIK0000000123"
    assert payload["securities"][0]["security_id"] == "security:NASDAQ-ACME"
    assert payload["valuation_profile_assignments"] == []


def test_security_ids_preserve_distinct_official_ticker_symbols() -> None:
    bundle = transform_us_source_records([
        record("DCOM", "NYSE", cik=1, name="Dime Community Bancshares"),
        record("DCOM^G", "NYSE", cik=2, name="Dime Community Bancshares Preferred G"),
    ])
    assert {item.security_id for item in bundle.securities} == {
        "security:NYSE-DCOM",
        "security:NYSE-DCOM~5E~G",
    }


def test_safe_ticker_encoding_avoids_previous_normalization_collision() -> None:
    bundle = transform_us_source_records([
        record("ABC$A", "NYSE", cik=1, name="ABC Preferred A"),
        record("ABC^A", "NYSE", cik=2, name="ABC Depositary A"),
    ])
    assert len({item.security_id for item in bundle.securities}) == 2
