from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import date
from decimal import Decimal

import pytest

from axiom_engine.normalized_financials import (
    EfficiencyMetrics,
    LeverageMetrics,
    LiquidityMetrics,
    NormalizedBalance,
    NormalizedCashFlow,
    NormalizedFinancials,
    NormalizedIdentity,
    NormalizedIncome,
    ProfitabilityMetrics,
)


def _snapshot() -> NormalizedFinancials:
    return NormalizedFinancials(
        identity=NormalizedIdentity(
            identifier="NVDA",
            cik="0001045810",
            entity_name="NVIDIA CORP",
        ),
        fiscal_year=2026,
        fiscal_period="FY",
        period_start=date(2025, 1, 27),
        period_end=date(2026, 1, 25),
        income=NormalizedIncome(
            revenue=Decimal("130497000000"),
            net_income=Decimal("72880000000"),
        ),
        balance=NormalizedBalance(
            cash=Decimal("8658000000"),
            total_assets=Decimal("111601000000"),
            shareholders_equity=Decimal("79327000000"),
        ),
        cash_flow=NormalizedCashFlow(
            operating_cash_flow=Decimal("102718000000"),
            capital_expenditure=Decimal("6042000000"),
            free_cash_flow=Decimal("96676000000"),
        ),
    )


def test_normalized_financials_is_immutable() -> None:
    snapshot = _snapshot()

    with pytest.raises(FrozenInstanceError):
        snapshot.fiscal_year = 2025  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        snapshot.identity.identifier = "OTHER"  # type: ignore[misc]


def test_statement_sections_preserve_decimal_values() -> None:
    snapshot = _snapshot()

    assert snapshot.income.revenue == Decimal("130497000000")
    assert snapshot.balance.cash == Decimal("8658000000")
    assert snapshot.cash_flow.free_cash_flow == Decimal("96676000000")
    assert isinstance(snapshot.income.revenue, Decimal)


def test_metric_sections_default_to_missing_values() -> None:
    snapshot = _snapshot()

    assert snapshot.profitability == ProfitabilityMetrics()
    assert snapshot.efficiency == EfficiencyMetrics()
    assert snapshot.liquidity == LiquidityMetrics()
    assert snapshot.leverage == LeverageMetrics()
    assert snapshot.profitability.net_margin is None


def test_metric_sections_accept_decimal_fractions() -> None:
    snapshot = NormalizedFinancials(
        identity=NormalizedIdentity("NVDA", "0001045810", "NVIDIA CORP"),
        fiscal_year=2026,
        fiscal_period="FY",
        income=NormalizedIncome(),
        balance=NormalizedBalance(),
        cash_flow=NormalizedCashFlow(),
        profitability=ProfitabilityMetrics(net_margin=Decimal("0.55848")),
        efficiency=EfficiencyMetrics(return_on_equity=Decimal("1.02")),
        liquidity=LiquidityMetrics(current_ratio=Decimal("4.10")),
        leverage=LeverageMetrics(debt_ratio=Decimal("0.29")),
    )

    assert snapshot.profitability.net_margin == Decimal("0.55848")
    assert snapshot.efficiency.return_on_equity == Decimal("1.02")
    assert snapshot.liquidity.current_ratio == Decimal("4.10")
    assert snapshot.leverage.debt_ratio == Decimal("0.29")


def test_to_dict_is_json_compatible_and_exact() -> None:
    payload = _snapshot().to_dict()

    assert payload["identity"] == {
        "identifier": "NVDA",
        "cik": "0001045810",
        "entity_name": "NVIDIA CORP",
        "currency": "USD",
    }
    assert payload["income"]["revenue"] == "130497000000"
    assert payload["period_start"] == "2025-01-27"
    assert payload["period_end"] == "2026-01-25"
    assert payload["profitability"]["net_margin"] is None


def test_model_shape_exposes_normalization_sections() -> None:
    names = tuple(field.name for field in fields(NormalizedFinancials))

    assert names == (
        "identity",
        "fiscal_year",
        "fiscal_period",
        "income",
        "balance",
        "cash_flow",
        "profitability",
        "efficiency",
        "liquidity",
        "leverage",
        "period_start",
        "period_end",
    )
