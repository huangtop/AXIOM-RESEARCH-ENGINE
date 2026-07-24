from __future__ import annotations

import json
from pathlib import Path

import pytest

from axiom_engine.production_build import build_production
from axiom_engine.production_research_card import (
    ProductionResearchCardError,
    build_production_research_cards,
    get_production_research_card,
    validate_production_research_cards,
)


FIXTURE = Path("examples/full_production_fixture")


def _production(tmp_path: Path) -> Path:
    output = tmp_path / "production"
    build_production(
        registry_source_dir=FIXTURE / "registry",
        financial_source_dir=FIXTURE / "financial",
        market_source_dir=FIXTURE / "market",
        estimate_source_dir=FIXTURE / "estimate",
        output_dir=output,
        write=True,
        strict=True,
    )
    return output


def test_build_production_research_cards(tmp_path: Path) -> None:
    output = tmp_path / "cards"
    result = build_production_research_cards(
        production_dir=_production(tmp_path), output_dir=output, write=True, strict=True
    )
    assert result["valid"] is True
    assert result["card_count"] == 1
    assert result["complete_card_count"] == 1
    assert (output / "cards" / "aapl.json").exists()


def test_get_card_by_symbol_and_company_id(tmp_path: Path) -> None:
    output = tmp_path / "cards"
    build_production_research_cards(
        production_dir=_production(tmp_path), output_dir=output, write=True, strict=True
    )
    by_symbol = get_production_research_card(output_dir=output, symbol="aapl")
    by_company = get_production_research_card(
        output_dir=output, company_id="company:US-CIK0000320193"
    )
    assert by_symbol["card_id"] == by_company["card_id"]
    assert by_symbol["market"]["latest"]["regular_market_price"] == "216.1"
    assert by_symbol["coverage"]["valuation_ready"] is True


def test_card_contains_four_layer_payload(tmp_path: Path) -> None:
    output = tmp_path / "cards"
    build_production_research_cards(
        production_dir=_production(tmp_path), output_dir=output, write=True
    )
    card = get_production_research_card(output_dir=output, symbol="AAPL")
    assert card["company"]["display_name"] == "Apple"
    assert card["primary_security"]["ticker"] == "AAPL"
    assert len(card["financials"]) == 3
    assert len(card["market"]["history"]) == 2
    assert len(card["estimates"]) == 3


def test_validate_detects_missing_indexed_card(tmp_path: Path) -> None:
    output = tmp_path / "cards"
    build_production_research_cards(
        production_dir=_production(tmp_path), output_dir=output, write=True
    )
    (output / "cards" / "aapl.json").unlink()
    result = validate_production_research_cards(output_dir=output)
    assert result["valid"] is False
    assert any("indexed card not found" in error for error in result["errors"])


def test_get_requires_exactly_one_lookup_key(tmp_path: Path) -> None:
    with pytest.raises(ProductionResearchCardError, match="exactly one"):
        get_production_research_card(output_dir=tmp_path)
    with pytest.raises(ProductionResearchCardError, match="exactly one"):
        get_production_research_card(output_dir=tmp_path, symbol="AAPL", company_id="x")


def test_missing_production_file_fails(tmp_path: Path) -> None:
    with pytest.raises(ProductionResearchCardError, match="required file not found"):
        build_production_research_cards(production_dir=tmp_path / "missing")
