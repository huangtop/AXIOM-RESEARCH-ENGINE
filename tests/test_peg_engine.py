from datetime import date
from decimal import Decimal

import pytest

from axiom_engine.peg_engine import PEGEngine
from axiom_engine.valuation_models import PEGInputs, ValuationIdentity, ValuationModelType


def identity() -> ValuationIdentity:
    return ValuationIdentity(
        company_id="company:TEST",
        security_id="security:TEST",
        ticker="TEST",
        currency="USD",
        as_of_date=date(2026, 7, 22),
    )


def test_positive_growth_calculates_implied_pe_and_fair_value() -> None:
    result = PEGEngine().calculate(
        PEGInputs(
            identity=identity(),
            forward_earnings_per_share=Decimal("12.8436"),
            growth_rate=Decimal("0.4293"),
            peg_ratio=Decimal("0.9"),
            market_price=Decimal("207.29"),
        )
    )

    assert result.model_type is ValuationModelType.price_earnings_growth
    assert result.implied_price_to_earnings == Decimal("38.63700")
    assert result.applied_price_to_earnings == Decimal("38.63700")
    assert result.fair_value_per_share == Decimal("496.238173200")
    assert result.used_fallback is False
    assert result.upside == result.fair_value_per_share / Decimal("207.29") - Decimal("1")
    assert result.warnings == ()


@pytest.mark.parametrize("growth_rate", [Decimal("0"), Decimal("-0.10")])
def test_non_positive_growth_uses_configured_fallback_pe(growth_rate: Decimal) -> None:
    result = PEGEngine().calculate(
        PEGInputs(
            identity=identity(),
            forward_earnings_per_share=Decimal("5"),
            growth_rate=growth_rate,
            fallback_price_to_earnings=Decimal("15"),
        )
    )

    assert result.implied_price_to_earnings is None
    assert result.applied_price_to_earnings == Decimal("15")
    assert result.fair_value_per_share == Decimal("75")
    assert result.used_fallback is True
    assert "fallback P/E applied" in result.warnings[0]
    assert "market price missing" in result.warnings[1]


def test_non_positive_forward_eps_returns_unavailable_result() -> None:
    result = PEGEngine().calculate(
        PEGInputs(
            identity=identity(),
            forward_earnings_per_share=Decimal("-1.25"),
            growth_rate=Decimal("0.50"),
            market_price=Decimal("20"),
        )
    )

    assert result.fair_value_per_share is None
    assert result.applied_price_to_earnings is None
    assert result.upside is None
    assert result.used_fallback is False
    assert result.warnings == (
        "PEG unavailable: forward earnings per share must be positive",
    )


def test_zero_market_price_suppresses_upside_without_rounding_value() -> None:
    result = PEGEngine().calculate(
        PEGInputs(
            identity=identity(),
            forward_earnings_per_share=Decimal("1.123456789123456789"),
            growth_rate=Decimal("0.234567891234567891"),
            peg_ratio=Decimal("0.987654321987654321"),
            market_price=Decimal("0"),
        )
    )

    assert result.upside is None
    assert result.warnings == ("upside unavailable: market price is zero",)
    assert result.to_dict()["fair_value_per_share"] == str(result.fair_value_per_share)


def test_input_validation_rejects_invalid_assumptions() -> None:
    with pytest.raises(ValueError, match="peg_ratio must be positive"):
        PEGInputs(
            identity=identity(),
            forward_earnings_per_share=Decimal("1"),
            growth_rate=Decimal("0.10"),
            peg_ratio=Decimal("0"),
        )
    with pytest.raises(ValueError, match="fallback_price_to_earnings must be positive"):
        PEGInputs(
            identity=identity(),
            forward_earnings_per_share=Decimal("1"),
            growth_rate=Decimal("0.10"),
            fallback_price_to_earnings=Decimal("0"),
        )
