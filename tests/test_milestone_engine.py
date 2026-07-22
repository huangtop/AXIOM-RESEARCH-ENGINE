from datetime import date
from decimal import Decimal

import pytest

from axiom_engine.milestone_engine import MilestoneEngine
from axiom_engine.valuation_models import (
    MilestoneInputs,
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


def test_default_web_scenarios_are_probability_weighted() -> None:
    result = MilestoneEngine().calculate(
        MilestoneInputs(
            identity=identity(),
            current_price=Decimal("100"),
            success_probability=Decimal("0.20"),
        )
    )

    assert result.model_type is ValuationModelType.milestone_scenario
    assert result.failure_probability == Decimal("0.80")
    assert result.success_value_per_share == Decimal("300.0")
    assert result.failure_value_per_share == Decimal("50.0")
    assert result.expected_multiple == Decimal("1.000")
    assert result.fair_value_per_share == Decimal("100.000")
    assert result.upside == Decimal("0.000")


@pytest.mark.parametrize(
    ("probability", "expected_multiple"),
    [(Decimal("0"), Decimal("0.5")), (Decimal("1"), Decimal("3.0"))],
)
def test_probability_boundaries_select_failure_or_success_case(
    probability: Decimal,
    expected_multiple: Decimal,
) -> None:
    result = MilestoneEngine().calculate(
        MilestoneInputs(
            identity=identity(),
            current_price=Decimal("80"),
            success_probability=probability,
        )
    )
    assert result.expected_multiple == expected_multiple
    assert result.fair_value_per_share == Decimal("80") * expected_multiple


def test_custom_scenarios_preserve_decimal_precision() -> None:
    result = MilestoneEngine().calculate(
        MilestoneInputs(
            identity=identity(),
            current_price=Decimal("63.34"),
            success_probability=Decimal("0.234567891234567891"),
            success_multiple=Decimal("4.25"),
            failure_multiple=Decimal("0.15"),
        )
    )

    expected = Decimal("4.25") * Decimal("0.234567891234567891") + Decimal(
        "0.15"
    ) * (Decimal("1") - Decimal("0.234567891234567891"))
    assert result.expected_multiple == expected
    assert result.fair_value_per_share == Decimal("63.34") * expected
    assert result.to_dict()["expected_multiple"] == str(expected)


def test_zero_price_returns_value_but_no_upside() -> None:
    result = MilestoneEngine().calculate(
        MilestoneInputs(
            identity=identity(),
            current_price=Decimal("0"),
            success_probability=Decimal("0.5"),
        )
    )

    assert result.fair_value_per_share == Decimal("0.00")
    assert result.upside is None
    assert result.warnings == ("upside unavailable: current price is zero",)


def test_input_validation_rejects_invalid_probability_and_multiples() -> None:
    with pytest.raises(ValueError, match="success_probability must be between 0 and 1"):
        MilestoneInputs(
            identity=identity(),
            current_price=Decimal("10"),
            success_probability=Decimal("1.1"),
        )
    with pytest.raises(ValueError, match="success_multiple cannot be negative"):
        MilestoneInputs(
            identity=identity(),
            current_price=Decimal("10"),
            success_probability=Decimal("0.2"),
            success_multiple=Decimal("-1"),
        )
