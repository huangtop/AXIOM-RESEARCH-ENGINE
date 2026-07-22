from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from axiom_engine.valuation_models import (
    CapitalStructure,
    DCFInputs,
    DiscountRateAssumptions,
    DiscountedCashFlowPeriod,
    ForecastPeriod,
    TerminalValueAssumptions,
    TerminalValueMethod,
    ValuationIdentity,
    ValuationModelType,
    ValuationResult,
)


def identity() -> ValuationIdentity:
    return ValuationIdentity(
        company_id="company:US-NVDA",
        security_id="security:US-NVDA",
        ticker="NVDA",
        currency="USD",
        as_of_date=date(2026, 7, 22),
    )


def rates() -> DiscountRateAssumptions:
    return DiscountRateAssumptions(
        risk_free_rate=Decimal("0.04"),
        equity_risk_premium=Decimal("0.05"),
        beta=Decimal("1.2"),
        cost_of_debt=Decimal("0.05"),
        tax_rate=Decimal("0.21"),
        debt_weight=Decimal("0.1"),
        equity_weight=Decimal("0.9"),
    )


def test_discount_rates_calculate_capm_and_wacc_without_rounding() -> None:
    assumptions = rates()

    assert assumptions.cost_of_equity == Decimal("0.100")
    assert assumptions.weighted_average_cost_of_capital == Decimal("0.093950")


def test_discount_rate_weights_must_sum_to_one() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        DiscountRateAssumptions(
            risk_free_rate=Decimal("0.04"),
            equity_risk_premium=Decimal("0.05"),
            beta=Decimal("1"),
            debt_weight=Decimal("0.2"),
            equity_weight=Decimal("0.7"),
        )


def test_terminal_value_method_requires_matching_parameter() -> None:
    with pytest.raises(ValueError, match="perpetual_growth_rate is required"):
        TerminalValueAssumptions(method=TerminalValueMethod.perpetual_growth)

    with pytest.raises(ValueError, match="exit_multiple is required"):
        TerminalValueAssumptions(method=TerminalValueMethod.exit_multiple)


def test_capital_structure_calculates_net_debt() -> None:
    capital = CapitalStructure(
        cash_and_equivalents=Decimal("30"),
        total_debt=Decimal("80"),
        diluted_shares_outstanding=Decimal("10"),
    )

    assert capital.net_debt == Decimal("50")


def test_dcf_inputs_require_ordered_unique_forecasts_with_fcf() -> None:
    terminal = TerminalValueAssumptions(
        method=TerminalValueMethod.perpetual_growth,
        perpetual_growth_rate=Decimal("0.03"),
    )

    with pytest.raises(ValueError, match="ordered"):
        DCFInputs(
            identity=identity(),
            forecasts=(
                ForecastPeriod(2028, free_cash_flow=Decimal("120")),
                ForecastPeriod(2027, free_cash_flow=Decimal("100")),
            ),
            discount_rates=rates(),
            terminal_value=terminal,
        )

    with pytest.raises(ValueError, match="requires free_cash_flow"):
        DCFInputs(
            identity=identity(),
            forecasts=(ForecastPeriod(2027),),
            discount_rates=rates(),
            terminal_value=terminal,
        )


def test_perpetual_growth_must_be_lower_than_wacc() -> None:
    with pytest.raises(ValueError, match="lower than WACC"):
        DCFInputs(
            identity=identity(),
            forecasts=(ForecastPeriod(2027, free_cash_flow=Decimal("100")),),
            discount_rates=rates(),
            terminal_value=TerminalValueAssumptions(
                method=TerminalValueMethod.perpetual_growth,
                perpetual_growth_rate=Decimal("0.10"),
            ),
        )


def test_dcf_inputs_are_immutable_and_json_compatible() -> None:
    inputs = DCFInputs(
        identity=identity(),
        forecasts=(
            ForecastPeriod(2027, revenue=Decimal("200"), free_cash_flow=Decimal("100")),
            ForecastPeriod(2028, revenue=Decimal("240"), free_cash_flow=Decimal("120")),
        ),
        discount_rates=rates(),
        terminal_value=TerminalValueAssumptions(
            method=TerminalValueMethod.perpetual_growth,
            perpetual_growth_rate=Decimal("0.03"),
        ),
        capital_structure=CapitalStructure(diluted_shares_outstanding=Decimal("25")),
    )

    with pytest.raises(FrozenInstanceError):
        inputs.model_version = "2.0"  # type: ignore[misc]

    payload = inputs.to_dict()
    assert payload["identity"]["as_of_date"] == "2026-07-22"
    assert payload["forecasts"][0]["free_cash_flow"] == "100"
    assert payload["terminal_value"]["method"] == "perpetual_growth"


def test_valuation_result_serializes_common_output_contract() -> None:
    result = ValuationResult(
        identity=identity(),
        model_type=ValuationModelType.discounted_cash_flow,
        model_version="1.0",
        enterprise_value=Decimal("1000"),
        equity_value=Decimal("950"),
        fair_value_per_share=Decimal("95"),
        market_price=Decimal("80"),
        upside=Decimal("0.1875"),
        forecast_values=(
            DiscountedCashFlowPeriod(
                fiscal_year=2027,
                free_cash_flow=Decimal("100"),
                discount_factor=Decimal("0.91"),
                present_value=Decimal("91"),
            ),
        ),
        warnings=("illustrative",),
    )

    payload = result.to_dict()
    assert payload["model_type"] == "discounted_cash_flow"
    assert payload["fair_value_per_share"] == "95"
    assert payload["forecast_values"][0]["present_value"] == "91"
    assert payload["warnings"] == ["illustrative"]
