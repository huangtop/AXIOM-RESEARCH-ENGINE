from datetime import date
from decimal import Decimal

import pytest

from axiom_engine.intrinsic_value_engine import IntrinsicValueEngine
from axiom_engine.valuation_models import (
    CapitalStructure,
    DCFInputs,
    DiscountRateAssumptions,
    ForecastPeriod,
    IntrinsicValueInputs,
    MultipleAssumption,
    MultiplesFinancials,
    MultiplesInputs,
    RelativeMultipleType,
    ReverseDCFInputs,
    TerminalValueAssumptions,
    TerminalValueMethod,
    ValuationIdentity,
    ValuationModelType,
)


def identity(ticker: str = "TEST") -> ValuationIdentity:
    return ValuationIdentity(
        company_id=f"company:{ticker}",
        security_id=f"security:{ticker}",
        ticker=ticker,
        currency="USD",
        as_of_date=date(2026, 7, 22),
    )


def rates() -> DiscountRateAssumptions:
    return DiscountRateAssumptions(
        risk_free_rate=Decimal("0.10"),
        equity_risk_premium=Decimal("0"),
        beta=Decimal("0"),
    )


def capital() -> CapitalStructure:
    return CapitalStructure(
        cash_and_equivalents=Decimal("50"),
        total_debt=Decimal("100"),
        diluted_shares_outstanding=Decimal("10"),
    )


def dcf_inputs() -> DCFInputs:
    return DCFInputs(
        identity=identity(),
        forecasts=(
            ForecastPeriod(2027, free_cash_flow=Decimal("100")),
            ForecastPeriod(2028, free_cash_flow=Decimal("110")),
        ),
        discount_rates=rates(),
        terminal_value=TerminalValueAssumptions(
            method=TerminalValueMethod.perpetual_growth,
            perpetual_growth_rate=Decimal("0.02"),
        ),
        capital_structure=capital(),
    )


def reverse_inputs(market_price: Decimal) -> ReverseDCFInputs:
    return ReverseDCFInputs(
        identity=identity(),
        current_free_cash_flow=Decimal("100"),
        forecast_years=5,
        discount_rates=rates(),
        terminal_value=TerminalValueAssumptions(
            method=TerminalValueMethod.perpetual_growth,
            perpetual_growth_rate=Decimal("0.02"),
        ),
        capital_structure=capital(),
        market_price=market_price,
        tolerance=Decimal("0.0000001"),
    )


def multiples_inputs() -> MultiplesInputs:
    return MultiplesInputs(
        identity=identity(),
        financials=MultiplesFinancials(
            revenue=Decimal("1000"),
            ebitda=Decimal("125"),
            net_income=Decimal("75"),
        ),
        capital_structure=capital(),
        assumptions=(
            MultipleAssumption(RelativeMultipleType.ev_to_ebitda, Decimal("10")),
        ),
        market_price=Decimal("20"),
    )


def test_unified_api_runs_dcf_and_passes_market_price() -> None:
    result = IntrinsicValueEngine().calculate(
        IntrinsicValueInputs(
            identity=identity(),
            dcf=dcf_inputs(),
            market_price=Decimal("100"),
        )
    )

    assert result.dcf is not None
    assert result.dcf.model_type is ValuationModelType.discounted_cash_flow
    assert result.dcf.market_price == Decimal("100")
    assert result.reverse_dcf is None
    assert result.multiples is None


def test_unified_api_runs_all_supplied_models() -> None:
    direct = IntrinsicValueEngine().calculate(
        IntrinsicValueInputs(identity=identity(), dcf=dcf_inputs())
    )
    assert direct.dcf is not None
    assert direct.dcf.fair_value_per_share is not None

    result = IntrinsicValueEngine().calculate(
        IntrinsicValueInputs(
            identity=identity(),
            dcf=dcf_inputs(),
            reverse_dcf=reverse_inputs(direct.dcf.fair_value_per_share),
            multiples=multiples_inputs(),
        )
    )

    assert result.dcf is not None
    assert result.reverse_dcf is not None
    assert result.reverse_dcf.converged is True
    assert result.multiples is not None
    assert len(result.multiples.valuations) == len(RelativeMultipleType)


def test_each_model_is_optional_and_multiples_can_run_alone() -> None:
    result = IntrinsicValueEngine().calculate(
        IntrinsicValueInputs(identity=identity(), multiples=multiples_inputs())
    )

    assert result.dcf is None
    assert result.reverse_dcf is None
    assert result.multiples is not None


def test_reverse_dcf_non_convergence_is_exposed_as_api_warning() -> None:
    reverse = reverse_inputs(Decimal("200"))
    reverse = ReverseDCFInputs(
        identity=reverse.identity,
        current_free_cash_flow=reverse.current_free_cash_flow,
        forecast_years=reverse.forecast_years,
        discount_rates=reverse.discount_rates,
        terminal_value=reverse.terminal_value,
        capital_structure=reverse.capital_structure,
        market_price=reverse.market_price,
        tolerance=Decimal("1e-40"),
        max_iterations=1,
    )
    result = IntrinsicValueEngine().calculate(
        IntrinsicValueInputs(identity=identity(), reverse_dcf=reverse)
    )

    assert result.reverse_dcf is not None
    assert result.reverse_dcf.converged is False
    assert result.warnings == ("reverse DCF did not converge",)


def test_inputs_require_at_least_one_model() -> None:
    with pytest.raises(ValueError, match="at least one valuation input is required"):
        IntrinsicValueInputs(identity=identity())


def test_inputs_reject_identity_mismatch() -> None:
    with pytest.raises(ValueError, match="same identity"):
        IntrinsicValueInputs(identity=identity("OTHER"), dcf=dcf_inputs())


def test_to_dict_serializes_nested_results_and_decimals() -> None:
    result = IntrinsicValueEngine().calculate(
        IntrinsicValueInputs(identity=identity(), multiples=multiples_inputs())
    )
    payload = result.to_dict()

    assert payload["identity"]["as_of_date"] == "2026-07-22"
    assert payload["multiples"]["market_equity_value"] == "200"
    assert payload["dcf"] is None
