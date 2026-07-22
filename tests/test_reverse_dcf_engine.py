from datetime import date
from decimal import Decimal

import pytest

from axiom_engine.dcf_engine import DiscountedCashFlowEngine
from axiom_engine.reverse_dcf_engine import ReverseDiscountedCashFlowEngine
from axiom_engine.valuation_models import (
    CapitalStructure,
    DCFInputs,
    DiscountRateAssumptions,
    ForecastPeriod,
    ReverseDCFInputs,
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


def rates() -> DiscountRateAssumptions:
    return DiscountRateAssumptions(
        risk_free_rate=Decimal("0.10"),
        equity_risk_premium=Decimal("0"),
        beta=Decimal("0"),
    )


def reverse_inputs(*, market_price: Decimal, **overrides: object) -> ReverseDCFInputs:
    values = {
        "identity": identity(),
        "current_free_cash_flow": Decimal("100"),
        "forecast_years": 5,
        "discount_rates": rates(),
        "terminal_value": TerminalValueAssumptions(
            method=TerminalValueMethod.perpetual_growth,
            perpetual_growth_rate=Decimal("0.02"),
        ),
        "capital_structure": CapitalStructure(
            cash_and_equivalents=Decimal("50"),
            total_debt=Decimal("100"),
            diluted_shares_outstanding=Decimal("10"),
        ),
        "market_price": market_price,
        "tolerance": Decimal("0.0000000001"),
    }
    values.update(overrides)
    return ReverseDCFInputs(**values)  # type: ignore[arg-type]


def market_price_for_growth(growth: Decimal) -> Decimal:
    forecasts = tuple(
        ForecastPeriod(
            2026 + year,
            free_cash_flow=Decimal("100") * ((Decimal("1") + growth) ** year),
        )
        for year in range(1, 6)
    )
    result = DiscountedCashFlowEngine().calculate(
        DCFInputs(
            identity=identity(),
            forecasts=forecasts,
            discount_rates=rates(),
            terminal_value=TerminalValueAssumptions(
                method=TerminalValueMethod.perpetual_growth,
                perpetual_growth_rate=Decimal("0.02"),
            ),
            capital_structure=CapitalStructure(
                cash_and_equivalents=Decimal("50"),
                total_debt=Decimal("100"),
                diluted_shares_outstanding=Decimal("10"),
            ),
        )
    )
    assert result.fair_value_per_share is not None
    return result.fair_value_per_share


def test_reverse_dcf_recovers_market_implied_growth() -> None:
    expected_growth = Decimal("0.12")
    result = ReverseDiscountedCashFlowEngine().calculate(
        reverse_inputs(market_price=market_price_for_growth(expected_growth))
    )

    assert result.model_type is ValuationModelType.reverse_discounted_cash_flow
    assert result.converged is True
    assert abs(result.implied_growth_rate - expected_growth) < Decimal("0.0000000001")
    assert abs(result.implied_value_per_share - result.market_price) < Decimal("0.0000000001")
    assert abs(result.valuation_error) <= Decimal("0.0000000001")


def test_reverse_dcf_builds_compounded_forecast_path() -> None:
    growth = Decimal("0.08")
    result = ReverseDiscountedCashFlowEngine().calculate(
        reverse_inputs(market_price=market_price_for_growth(growth))
    )

    assert abs(result.forecast_values[0].free_cash_flow - Decimal("108")) < Decimal("1e-10")
    expected_final = Decimal("100") * Decimal("1.08") ** 5
    assert abs(result.forecast_values[-1].free_cash_flow - expected_final) < Decimal("1e-9")


def test_reverse_dcf_supports_exit_multiple_terminal_value() -> None:
    terminal = TerminalValueAssumptions(
        method=TerminalValueMethod.exit_multiple,
        exit_multiple=Decimal("12"),
    )
    direct = DiscountedCashFlowEngine().calculate(
        DCFInputs(
            identity=identity(),
            forecasts=tuple(
                ForecastPeriod(2026 + year, free_cash_flow=Decimal("100") * Decimal("1.05") ** year)
                for year in range(1, 6)
            ),
            discount_rates=rates(),
            terminal_value=terminal,
            capital_structure=CapitalStructure(diluted_shares_outstanding=Decimal("10")),
        )
    )
    assert direct.fair_value_per_share is not None

    result = ReverseDiscountedCashFlowEngine().calculate(
        reverse_inputs(
            market_price=direct.fair_value_per_share,
            terminal_value=terminal,
            capital_structure=CapitalStructure(diluted_shares_outstanding=Decimal("10")),
        )
    )
    assert abs(result.implied_growth_rate - Decimal("0.05")) < Decimal("0.0000000001")


def test_reverse_dcf_rejects_target_outside_growth_bounds() -> None:
    with pytest.raises(ValueError, match="outside the configured growth-rate bounds"):
        ReverseDiscountedCashFlowEngine().calculate(
            reverse_inputs(
                market_price=Decimal("1000000"),
                minimum_growth_rate=Decimal("0"),
                maximum_growth_rate=Decimal("0.10"),
            )
        )


def test_reverse_dcf_reports_non_convergence() -> None:
    result = ReverseDiscountedCashFlowEngine().calculate(
        reverse_inputs(
            market_price=market_price_for_growth(Decimal("0.123456")),
            tolerance=Decimal("1e-40"),
            max_iterations=1,
        )
    )
    assert result.converged is False
    assert result.iterations == 1
    assert result.warnings == ("solver reached max_iterations before tolerance",)


def test_reverse_dcf_input_validation() -> None:
    with pytest.raises(ValueError, match="diluted_shares_outstanding is required"):
        reverse_inputs(
            market_price=Decimal("100"),
            capital_structure=CapitalStructure(),
        )
    with pytest.raises(ValueError, match="current_free_cash_flow must be positive"):
        reverse_inputs(market_price=Decimal("100"), current_free_cash_flow=Decimal("0"))
    with pytest.raises(ValueError, match="minimum_growth_rate must be greater than -1"):
        reverse_inputs(market_price=Decimal("100"), minimum_growth_rate=Decimal("-1"))
