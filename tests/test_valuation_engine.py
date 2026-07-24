from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from axiom_engine.cli import app
from axiom_engine.valuation_engine import build_valuations, validate_valuations


def write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def fixture(tmp_path: Path):
    company_id = "company:US-CIK0000320193"
    financial = tmp_path / "financial"
    estimate = tmp_path / "estimate"
    market = tmp_path / "market"
    registry = tmp_path / "registry"
    output = tmp_path / "valuation"
    facts = []
    for metric, value, unit in [
        ("operating_cash_flow", "120000", "currency"),
        ("capital_expenditures", "20000", "currency"),
        ("cash_and_cash_equivalents", "50000", "currency"),
        ("total_debt", "30000", "currency"),
        ("diluted_shares_outstanding", "1000", "shares"),
    ]:
        facts.append({"financial_fact_id": f"financial_fact:a:{metric}", "company_id": company_id, "metric": metric, "value": value, "unit": unit, "currency": "USD" if unit == "currency" else None, "period_end": "2025-12-31"})
    estimates = [
        {"estimate_id": "estimate:a:eps", "company_id": company_id, "metric": "diluted_eps", "value": "8", "currency": "USD", "period_end": "2027-12-31"},
        {"estimate_id": "estimate:a:revenue", "company_id": company_id, "metric": "revenue", "value": "400000", "currency": "USD", "period_end": "2027-12-31"},
    ]
    observations = [
        {"market_observation_id": "market:a:price", "company_id": company_id, "metric": "current_price", "value": "180", "currency": "USD", "observed_at": "2026-07-24T12:00:00Z", "trading_date": "2026-07-24"},
        {"market_observation_id": "market:a:shares", "company_id": company_id, "metric": "shares_outstanding", "value": "1000", "observed_at": "2026-07-24T12:00:00Z", "trading_date": "2026-07-24"},
    ]
    write(financial / "financial_facts.json", facts)
    write(estimate / "estimates.json", estimates)
    write(market / "observations.json", observations)
    write(registry / "companies.json", [{"company_id": company_id, "display_name": "Apple"}])
    write(registry / "securities.json", [{"company_id": company_id, "ticker": "AAPL", "primary_listing": True}])
    assumptions = tmp_path / "assumptions.json"
    write(assumptions, {"as_of_date": "2026-07-24", "source": "test", "defaults": {"fcff_growth_rate": "0.06", "discount_rate": "0.09", "terminal_growth_rate": "0.025", "target_forward_pe": "20", "target_forward_ps": "4", "target_ev_ebitda": "12", "source": "test", "as_of_date": "2026-07-24", "method_weights": {"discounted_cash_flow": "0.5", "forward_pe": "0.3", "forward_ps": "0.2", "forward_ev_ebitda": "0"}, "scenarios": {"bear": {"discount_rate": "0.01"}, "base": {}, "bull": {"discount_rate": "-0.01"}}}, "companies": {}})
    return company_id, financial, estimate, market, registry, assumptions, output


def test_build_three_scenarios_and_write(tmp_path):
    _, financial, estimate, market, registry, assumptions, output = fixture(tmp_path)
    report = build_valuations(financial_dir=financial, estimate_dir=estimate, market_dir=market, registry_dir=registry, assumptions_file=assumptions, output_dir=output, write=True)
    assert report["valuations_built"] == 3
    assert report["valuations_partial"] == 3
    assert report["acceptance_passed"] is True
    rows = json.loads((output / "valuations.json").read_text())
    assert {row["scenario"] for row in rows} == {"bear", "base", "bull"}
    assert all(row["blended_fair_value_per_share"] is not None for row in rows)


def test_company_ticker_filter(tmp_path):
    _, financial, estimate, market, registry, assumptions, output = fixture(tmp_path)
    report = build_valuations(financial_dir=financial, estimate_dir=estimate, market_dir=market, registry_dir=registry, assumptions_file=assumptions, output_dir=output, company="AAPL")
    assert report["companies_requested"] == 1


def test_validate_written_bundle(tmp_path):
    _, financial, estimate, market, registry, assumptions, output = fixture(tmp_path)
    build_valuations(financial_dir=financial, estimate_dir=estimate, market_dir=market, registry_dir=registry, assumptions_file=assumptions, output_dir=output, write=True)
    report = validate_valuations(output)
    assert report["valid"] is True
    assert report["valuations"] == 3


def test_missing_ebitda_is_diagnostic_not_crash(tmp_path):
    _, financial, estimate, market, registry, assumptions, output = fixture(tmp_path)
    build_valuations(financial_dir=financial, estimate_dir=estimate, market_dir=market, registry_dir=registry, assumptions_file=assumptions, output_dir=output, write=True)
    diagnostics = json.loads((output / "diagnostics.json").read_text())
    assert any("EBITDA" in row["message"] for row in diagnostics)


def test_cli_help_exposes_v025_options():
    runner = CliRunner()
    result = runner.invoke(app, ["build-valuations", "--help"])
    assert result.exit_code == 0
    assert "--assumptions-file" in result.stdout
    assert "--compact" in result.stdout
    result = runner.invoke(app, ["validate-valuations", "--help"])
    assert result.exit_code == 0
