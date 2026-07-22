from datetime import date
from decimal import Decimal

import pytest

from axiom_engine.dcf_engine import DiscountedCashFlowEngine
from axiom_engine.valuation_models import (
    CapitalStructure,
    DCFInputs,
    DiscountRateAssumptions,
    ForecastPeriod,
    TerminalValueAssumptions,
    TerminalValueMethod,
    ValuationIdentity,
    ValuationModelType,
)


def identity() -> ValuationIdentity:
    return ValuationIdentity(
        company_id="company:TEST",
        security_id="security:TEST",
        ticker="TEST",
        currency="USD",
        as_of_date=date(2026, 7, 22),
    )


def rates(*, wacc: Decimal = Decimal("0.10")) -> DiscountRateAssumptions:
    return DiscountRateAssumptions(
        risk_free_rate=wacc,
        equity_risk_premium=Decimal("0"),
        beta=Decimal("0"),
    )


def inputs(
    *,
    terminal: TerminalValueAssumptions | None = None,
    capital: CapitalStructure | None = None,
) -> DCFInputs:
    return DCFInputs(
        identity=identity(),
        forecasts=(
            ForecastPeriod(2027, free_cash_flow=Decimal("100")),
            ForecastPeriod(2028, free_cash_flow=Decimal("110")),
        ),
        discount_rates=rates(),
        terminal_value=terminal
        or TerminalValueAssumptions(
            method=TerminalValueMethod.perpetual_growth,
            perpetual_growth_rate=Decimal("0.02"),
        ),
        capital_structure=capital or CapitalStructure(),
    )


def test_dcf_discounts_each_forecast_as_year_end_cash_flow() -> None:
    result = DiscountedCashFlowEngine().calculate(inputs())

    first, second = result.forecast_values
    assert first.discount_factor == Decimal("1") / Decimal("1.10")
    assert first.present_value == Decimal("100") / Decimal("1.10")
    assert second.discount_factor == Decimal("1") / (Decimal("1.10") ** 2)
    assert second.present_value == Decimal("110") / (Decimal("1.10") ** 2)


def test_perpetual_growth_terminal_value_and_enterprise_value() -> None:
    result = DiscountedCashFlowEngine().calculate(inputs())

    expected_terminal = Decimal("110") * Decimal("1.02") / Decimal("0.08")
    expected_pv_terminal = expected_terminal / (Decimal("1.10") ** 2)
    expected_enterprise = (
        Decimal("100") / Decimal("1.10")
        + Decimal("110") / (Decimal("1.10") ** 2)
        + expected_pv_terminal
    )

    assert result.model_type is ValuationModelType.discounted_cash_flow
    assert result.terminal_value == expected_terminal
    assert result.present_value_terminal == expected_pv_terminal
    assert result.enterprise_value == expected_enterprise


def test_exit_multiple_uses_final_forecast_free_cash_flow() -> None:
    result = DiscountedCashFlowEngine().calculate(
        inputs(
            terminal=TerminalValueAssumptions(
                method=TerminalValueMethod.exit_multiple,
                exit_multiple=Decimal("12"),
            )
        )
    )

    assert result.terminal_value == Decimal("1320")
    assert result.present_value_terminal == Decimal("1320") / (Decimal("1.10") ** 2)


def test_enterprise_to_equity_bridge_and_per_share_value() -> None:
    capital = CapitalStructure(
        cash_and_equivalents=Decimal("50"),
        total_debt=Decimal("120"),
        non_controlling_interest=Decimal("10"),
        preferred_stock=Decimal("5"),
        diluted_shares_outstanding=Decimal("25"),
    )
    result = DiscountedCashFlowEngine().calculate(inputs(capital=capital))

    assert result.equity_value == result.enterprise_value - Decimal("85")
    assert result.fair_value_per_share == result.equity_value / Decimal("25")


def test_market_price_calculates_upside_without_rounding() -> None:
    capital = CapitalStructure(diluted_shares_outstanding=Decimal("10"))
    result = DiscountedCashFlowEngine().calculate(
        inputs(capital=capital),
        market_price=Decimal("100"),
    )

    assert result.upside == result.fair_value_per_share / Decimal("100") - Decimal("1")
    assert result.market_price == Decimal("100")


def test_missing_shares_and_zero_market_price_return_warnings() -> None:
    result = DiscountedCashFlowEngine().calculate(inputs(), market_price=Decimal("0"))

    assert result.fair_value_per_share is None
    assert result.upside is None
    assert result.warnings == (
        "fair value per share unavailable: diluted shares missing",
        "upside unavailable: market price is zero",
    )


def test_negative_equity_does_not_emit_negative_per_share_value() -> None:
    result = DiscountedCashFlowEngine().calculate(
        inputs(
            capital=CapitalStructure(
                total_debt=Decimal("10000"),
                diluted_shares_outstanding=Decimal("10"),
            )
        ),
        market_price=Decimal("50"),
    )

    assert result.equity_value < 0
    assert result.fair_value_per_share is None
    assert result.upside is None
    assert result.warnings == (
        "fair value per share unavailable: equity value is negative",
        "upside unavailable: fair value per share unavailable",
    )


def test_engine_rejects_non_positive_wacc_and_negative_market_price() -> None:
    zero_wacc_inputs = DCFInputs(
        identity=identity(),
        forecasts=(ForecastPeriod(2027, free_cash_flow=Decimal("100")),),
        discount_rates=rates(wacc=Decimal("0")),
        terminal_value=TerminalValueAssumptions(
            method=TerminalValueMethod.exit_multiple,
            exit_multiple=Decimal("10"),
        ),
    )

    with pytest.raises(ValueError, match="WACC must be positive"):
        DiscountedCashFlowEngine().calculate(zero_wacc_inputs)

    with pytest.raises(ValueError, match="market_price cannot be negative"):
        DiscountedCashFlowEngine().calculate(inputs(), market_price=Decimal("-1"))
