from datetime import date
from decimal import Decimal

import pytest

from axiom_engine.multiples_engine import MultiplesEngine
from axiom_engine.valuation_models import (
    CapitalStructure,
    MultipleAssumption,
    MultiplesFinancials,
    MultiplesInputs,
    RelativeMultipleType,
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


def inputs(
    *,
    financials: MultiplesFinancials | None = None,
    capital: CapitalStructure | None = None,
    assumptions: tuple[MultipleAssumption, ...] = (),
    market_price: Decimal | None = Decimal("20"),
) -> MultiplesInputs:
    return MultiplesInputs(
        identity=identity(),
        financials=financials
        or MultiplesFinancials(
            revenue=Decimal("1000"),
            ebit=Decimal("100"),
            ebitda=Decimal("125"),
            free_cash_flow=Decimal("80"),
            net_income=Decimal("75"),
            book_value=Decimal("500"),
            basic_shares_outstanding=Decimal("90"),
        ),
        capital_structure=capital
        or CapitalStructure(
            cash_and_equivalents=Decimal("50"),
            total_debt=Decimal("150"),
            non_controlling_interest=Decimal("10"),
            preferred_stock=Decimal("5"),
            diluted_shares_outstanding=Decimal("100"),
        ),
        assumptions=assumptions,
        market_price=market_price,
    )


def by_type(result, multiple_type: RelativeMultipleType):
    return next(item for item in result.valuations if item.multiple_type is multiple_type)


def test_observed_enterprise_and_equity_multiples_use_correct_market_values() -> None:
    result = MultiplesEngine().calculate(inputs())

    assert result.model_type is ValuationModelType.relative_multiples
    assert result.market_equity_value == Decimal("2000")
    assert result.market_enterprise_value == Decimal("2115")
    assert by_type(result, RelativeMultipleType.ev_to_revenue).observed_multiple == (
        Decimal("2115") / Decimal("1000")
    )
    assert by_type(result, RelativeMultipleType.price_to_book).observed_multiple == Decimal(
        "4"
    )


def test_target_enterprise_multiple_bridges_to_equity_and_per_share_value() -> None:
    result = MultiplesEngine().calculate(
        inputs(
            assumptions=(
                MultipleAssumption(RelativeMultipleType.ev_to_ebitda, Decimal("10")),
            )
        )
    )
    valuation = by_type(result, RelativeMultipleType.ev_to_ebitda)

    assert valuation.implied_enterprise_value == Decimal("1250")
    assert valuation.implied_equity_value == Decimal("1135")
    assert valuation.implied_value_per_share == Decimal("11.35")
    assert valuation.upside == Decimal("11.35") / Decimal("20") - Decimal("1")


def test_target_equity_multiple_bridges_to_enterprise_value() -> None:
    result = MultiplesEngine().calculate(
        inputs(
            assumptions=(
                MultipleAssumption(RelativeMultipleType.price_to_book, Decimal("3")),
            )
        )
    )
    valuation = by_type(result, RelativeMultipleType.price_to_book)

    assert valuation.implied_equity_value == Decimal("1500")
    assert valuation.implied_enterprise_value == Decimal("1615")
    assert valuation.implied_value_per_share == Decimal("15")


def test_basic_pe_uses_basic_shares_while_diluted_pe_uses_diluted_shares() -> None:
    assumptions = (
        MultipleAssumption(RelativeMultipleType.price_to_earnings_basic, Decimal("12")),
        MultipleAssumption(RelativeMultipleType.price_to_earnings_diluted, Decimal("12")),
    )
    result = MultiplesEngine().calculate(inputs(assumptions=assumptions))

    basic = by_type(result, RelativeMultipleType.price_to_earnings_basic)
    diluted = by_type(result, RelativeMultipleType.price_to_earnings_diluted)
    assert basic.implied_equity_value == diluted.implied_equity_value == Decimal("900")
    assert basic.implied_value_per_share == Decimal("10")
    assert diluted.implied_value_per_share == Decimal("9")


def test_missing_or_non_positive_denominator_is_isolated_per_multiple() -> None:
    result = MultiplesEngine().calculate(
        inputs(
            financials=MultiplesFinancials(
                revenue=Decimal("1000"),
                ebit=Decimal("0"),
                ebitda=None,
                free_cash_flow=Decimal("80"),
                net_income=Decimal("75"),
                book_value=Decimal("500"),
                basic_shares_outstanding=Decimal("90"),
            )
        )
    )

    ebit = by_type(result, RelativeMultipleType.ev_to_ebit)
    ebitda = by_type(result, RelativeMultipleType.ev_to_ebitda)
    revenue = by_type(result, RelativeMultipleType.ev_to_revenue)
    assert ebit.observed_multiple is None
    assert ebit.warnings == ("multiple unavailable: denominator must be positive",)
    assert ebitda.observed_multiple is None
    assert ebitda.warnings == ("multiple unavailable: denominator missing",)
    assert revenue.observed_multiple is not None


def test_missing_market_price_still_calculates_target_valuation() -> None:
    result = MultiplesEngine().calculate(
        inputs(
            market_price=None,
            assumptions=(
                MultipleAssumption(RelativeMultipleType.ev_to_free_cash_flow, Decimal("15")),
            ),
        )
    )
    valuation = by_type(result, RelativeMultipleType.ev_to_free_cash_flow)

    assert result.market_equity_value is None
    assert valuation.observed_multiple is None
    assert valuation.implied_enterprise_value == Decimal("1200")
    assert valuation.implied_value_per_share == Decimal("10.85")
    assert "upside unavailable: market price missing" in valuation.warnings


def test_duplicate_assumptions_and_non_positive_multiples_are_rejected() -> None:
    with pytest.raises(ValueError, match="multiple must be positive"):
        MultipleAssumption(RelativeMultipleType.price_to_book, Decimal("0"))

    duplicate = MultipleAssumption(RelativeMultipleType.price_to_book, Decimal("2"))
    with pytest.raises(ValueError, match="must be unique"):
        inputs(assumptions=(duplicate, duplicate))


def test_result_serialization_preserves_decimal_precision() -> None:
    result = MultiplesEngine().calculate(
        inputs(
            assumptions=(
                MultipleAssumption(
                    RelativeMultipleType.ev_to_revenue,
                    Decimal("2.123456789123456789"),
                ),
            )
        )
    )

    serialized = result.to_dict()
    valuation = serialized["valuations"][0]
    assert valuation["target_multiple"] == "2.123456789123456789"
    assert valuation["implied_enterprise_value"] == "2123.456789123456789000"
