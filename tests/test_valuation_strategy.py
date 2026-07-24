import json
from pathlib import Path

from typer.testing import CliRunner

from axiom_engine.cli import app
from axiom_engine.valuation_strategy import build_valuation_strategies, validate_valuation_strategies

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "valuation_strategy_fixture"


def test_strategy_selection_all_tiers(tmp_path):
    result = build_valuation_strategies(
        registry_dir=FIXTURE / "company_registry",
        financial_dir=FIXTURE / "financial_data",
        estimate_dir=FIXTURE / "estimate_data",
        market_dir=FIXTURE / "market_data",
        output_dir=tmp_path,
        write=True,
    )
    assert result["valid"] is True
    assert result["company_count"] == 5
    assert result["coverage_tiers"] == {"A": 1, "B": 1, "C": 1, "D": 1, "X": 1}
    rows = json.loads((tmp_path / "valuation_strategies.json").read_text())["strategies"]
    by_ticker = {row["ticker"]: row for row in rows}
    assert by_ticker["A"]["selected_strategy"] == "forward_pe"
    assert by_ticker["B"]["selected_strategy"] == "historical_fcff_multiple"
    assert by_ticker["C"]["selected_strategy"] == "revenue_multiple"
    assert by_ticker["D"]["selected_strategy"] == "book_value"
    assert by_ticker["X"]["status"] == "unavailable"


def test_fallback_metadata_is_explicit(tmp_path):
    build_valuation_strategies(registry_dir=FIXTURE / "company_registry", financial_dir=FIXTURE / "financial_data", estimate_dir=FIXTURE / "estimate_data", market_dir=FIXTURE / "market_data", output_dir=tmp_path, write=True)
    rows = json.loads((tmp_path / "valuation_strategies.json").read_text())["strategies"]
    b = next(row for row in rows if row["ticker"] == "B")
    assert b["coverage_tier"] == "B"
    assert b["fallback_reason"] == "missing_forward_estimates"
    assert "forward_eps" in b["missing_inputs"]
    assert b["confidence"] < 85


def test_validate_strategy_output(tmp_path):
    build_valuation_strategies(registry_dir=FIXTURE / "company_registry", financial_dir=FIXTURE / "financial_data", estimate_dir=FIXTURE / "estimate_data", market_dir=FIXTURE / "market_data", output_dir=tmp_path, write=True)
    assert validate_valuation_strategies(output_dir=tmp_path) == {"valid": True, "errors": [], "output_dir": str(tmp_path), "company_count": 5}


def test_cli_commands_present():
    runner = CliRunner()
    assert runner.invoke(app, ["build-valuation-strategies", "--help"]).exit_code == 0
    assert runner.invoke(app, ["validate-valuation-strategies", "--help"]).exit_code == 0
