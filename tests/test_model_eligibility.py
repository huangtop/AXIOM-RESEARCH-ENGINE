from datetime import datetime, timezone
from decimal import Decimal

import pytest

from axiom_engine.market_snapshot import MarketSnapshot
from axiom_engine.model_eligibility import (
    EligibilityInputs,
    EligibilityModel,
    EligibilityStatus,
    ModelEligibilityEngine,
)


def snapshot(**overrides: object) -> MarketSnapshot:
    values: dict[str, object] = {
        "symbol": "AAPL",
        "provider": "test",
        "observed_at": datetime(2026, 7, 22, tzinfo=timezone.utc),
        "regular_market_price": Decimal("200"),
        "shares_outstanding": Decimal("1000"),
        "forward_earnings_per_share": Decimal("8"),
    }
    values.update(overrides)
    return MarketSnapshot(**values)  # type: ignore[arg-type]


def full_inputs(**overrides: object) -> EligibilityInputs:
    values: dict[str, object] = {
        "snapshot": snapshot(),
        "forecast_free_cash_flows": (Decimal("100"), Decimal("110")),
        "current_free_cash_flow": Decimal("90"),
        "revenue": Decimal("1000"),
        "ebitda": Decimal("250"),
        "net_income": Decimal("150"),
        "forward_growth_rate": Decimal("0.12"),
        "has_discount_rate_assumptions": True,
        "has_terminal_value_assumptions": True,
        "has_peer_multiple_assumptions": True,
        "has_milestone_case": True,
        "milestone_success_probability": Decimal("0.65"),
    }
    values.update(overrides)
    return EligibilityInputs(**values)  # type: ignore[arg-type]


def test_fully_populated_company_is_eligible_for_every_model() -> None:
    report = ModelEligibilityEngine().evaluate(full_inputs())
    assert all(decision.status is EligibilityStatus.ELIGIBLE for decision in report.decisions)
    assert report.runnable_models == tuple(EligibilityModel)
    assert report.preferred_models == tuple(EligibilityModel)


def test_report_lookup_and_serialization() -> None:
    report = ModelEligibilityEngine().evaluate(full_inputs())
    assert report.for_model("peg").model is EligibilityModel.PEG
    assert report.to_dict()["decisions"][0]["status"] == "eligible"
    with pytest.raises(KeyError):
        report.for_model(EligibilityModel("dcf").value + "x")


def test_dcf_lists_all_missing_required_inputs() -> None:
    inputs = full_inputs(
        forecast_free_cash_flows=(),
        has_discount_rate_assumptions=False,
        has_terminal_value_assumptions=False,
        snapshot=snapshot(shares_outstanding=None),
    )
    decision = ModelEligibilityEngine().evaluate(inputs).for_model(EligibilityModel.DCF)
    assert decision.status is EligibilityStatus.INELIGIBLE
    assert decision.missing_required_fields == (
        "forecast_free_cash_flows",
        "discount_rate_assumptions",
        "terminal_value_assumptions",
        "shares_outstanding",
    )
    assert EligibilityModel.MULTIPLES in decision.fallback_models


def test_dcf_with_only_non_positive_forecasts_is_conditional() -> None:
    decision = ModelEligibilityEngine().evaluate(
        full_inputs(forecast_free_cash_flows=(Decimal("-10"), Decimal("0")))
    ).for_model("dcf")
    assert decision.status is EligibilityStatus.CONDITIONAL
    assert decision.can_run is True
    assert decision.reasons[0].code == "non_positive_forecast_fcf"


def test_reverse_dcf_requires_market_fcf_shares_and_assumptions() -> None:
    inputs = full_inputs(
        snapshot=snapshot(regular_market_price=None, shares_outstanding=None),
        current_free_cash_flow=Decimal("0"),
        has_discount_rate_assumptions=False,
        has_terminal_value_assumptions=False,
    )
    decision = ModelEligibilityEngine().evaluate(inputs).for_model("reverse_dcf")
    assert decision.status is EligibilityStatus.INELIGIBLE
    assert set(decision.missing_required_fields) == {
        "market_price",
        "current_free_cash_flow",
        "shares_outstanding",
        "discount_rate_assumptions",
        "terminal_value_assumptions",
    }


def test_multiples_requires_positive_denominator_peer_assumptions_and_shares() -> None:
    inputs = full_inputs(
        snapshot=snapshot(shares_outstanding=None),
        current_free_cash_flow=Decimal("-1"),
        revenue=None,
        ebit=None,
        ebitda=Decimal("0"),
        net_income=Decimal("-5"),
        book_value=None,
        has_peer_multiple_assumptions=False,
    )
    decision = ModelEligibilityEngine().evaluate(inputs).for_model("multiples")
    assert decision.status is EligibilityStatus.INELIGIBLE
    assert decision.missing_required_fields == (
        "positive_financial_denominator",
        "peer_multiple_assumptions",
        "shares_outstanding",
    )


def test_multiples_with_one_denominator_is_conditional() -> None:
    inputs = full_inputs(
        revenue=Decimal("1000"),
        ebit=None,
        ebitda=None,
        net_income=None,
        book_value=None,
        current_free_cash_flow=None,
    )
    decision = ModelEligibilityEngine().evaluate(inputs).for_model("multiples")
    assert decision.status is EligibilityStatus.CONDITIONAL
    assert decision.missing_optional_fields == ("second_positive_financial_denominator",)


def test_peg_requires_positive_forward_eps_and_growth() -> None:
    inputs = full_inputs(
        snapshot=snapshot(forward_earnings_per_share=Decimal("-1")),
        forward_growth_rate=Decimal("0"),
    )
    decision = ModelEligibilityEngine().evaluate(inputs).for_model("peg")
    assert decision.status is EligibilityStatus.INELIGIBLE
    assert decision.missing_required_fields == (
        "forward_earnings_per_share",
        "forward_growth_rate",
    )


def test_peg_without_market_price_is_conditional_but_runnable() -> None:
    inputs = full_inputs(snapshot=snapshot(regular_market_price=None))
    decision = ModelEligibilityEngine().evaluate(inputs).for_model("peg")
    assert decision.status is EligibilityStatus.CONDITIONAL
    assert decision.can_run is True
    assert decision.missing_optional_fields == ("market_price",)


def test_milestone_requires_research_case_probability_and_price() -> None:
    inputs = full_inputs(
        snapshot=snapshot(regular_market_price=None),
        has_milestone_case=False,
        milestone_success_probability=None,
    )
    decision = ModelEligibilityEngine().evaluate(inputs).for_model("milestone")
    assert decision.status is EligibilityStatus.INELIGIBLE
    assert decision.missing_required_fields == (
        "market_price",
        "milestone_case",
        "milestone_success_probability",
    )


def test_probability_is_validated_at_contract_boundary() -> None:
    with pytest.raises(ValueError, match="between zero and one"):
        full_inputs(milestone_success_probability=Decimal("1.1"))


def test_preferred_models_fall_back_to_conditional_when_none_are_fully_eligible() -> None:
    inputs = EligibilityInputs(
        snapshot=snapshot(regular_market_price=None),
        forward_growth_rate=Decimal("0.10"),
    )
    report = ModelEligibilityEngine().evaluate(inputs)
    assert report.preferred_models == (EligibilityModel.PEG,)


def test_report_rejects_duplicate_model_decisions() -> None:
    report = ModelEligibilityEngine().evaluate(full_inputs())
    with pytest.raises(ValueError, match="unique"):
        type(report)(symbol="AAPL", decisions=(report.decisions[0], report.decisions[0]))
