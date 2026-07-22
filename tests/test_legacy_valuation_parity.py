from __future__ import annotations

from datetime import date
from decimal import Decimal

from axiom_engine.legacy_valuation_parity import (
    LegacyValuationInputs,
    LegacyValuationModel,
    LegacyValuationParityEngine,
    compare_legacy_value,
)
from axiom_engine.previous_close import DailyClose


def close():
    return DailyClose("NVDA", date(2026, 7, 21), Decimal("205.47"), "USD", "America/New_York")


def inputs():
    return LegacyValuationInputs(
        symbol="NVDA", previous_close=close(), forward_eps=Decimal("6"), current_eps=Decimal("4"),
        growth_percent=Decimal("30"), target_pe=Decimal("50"), forward_revenue_per_share=Decimal("10"),
        target_ps=Decimal("20"), book_value_per_share=Decimal("5"), target_pb=Decimal("12"),
        ebitda=Decimal("1000"), target_ev_ebitda=Decimal("35"), net_debt=Decimal("5000"),
        shares_outstanding=Decimal("100"), milestone_success_probability=Decimal("0.2"),
    )


def test_all_six_legacy_formulas_match_php_contract():
    results = {r.model: r for r in LegacyValuationParityEngine().calculate_all(inputs())}
    assert results[LegacyValuationModel.PEG].fair_value_per_share == Decimal("162.0")
    assert results[LegacyValuationModel.PE].fair_value_per_share == Decimal("300")
    assert results[LegacyValuationModel.PS].fair_value_per_share == Decimal("200")
    assert results[LegacyValuationModel.PB].fair_value_per_share == Decimal("60")
    assert results[LegacyValuationModel.EV_EBITDA].fair_value_per_share == Decimal("300")
    assert results[LegacyValuationModel.MILESTONE].fair_value_per_share == Decimal("205.470")


def test_payload_adapter_uses_previous_close_for_pe_and_milestone():
    payload = {
        "market_consensus_eps_forward": 6, "market_consensus_eps_current": 4,
        "growth_estimate": 0.30, "future_revenue_per_share": 10, "ps": 20,
        "book_value_per_share": 5, "target_pb": 12, "ebitda_estimate": 1000,
        "net_debt": 5000, "shares_outstanding": 100, "default_params": {"success_prob": 0.2},
    }
    parsed = LegacyValuationInputs.from_legacy_payload("NVDA", payload, close())
    assert parsed.target_pe == Decimal("205.47") / Decimal("4")
    assert parsed.growth_percent == Decimal("30.0")
    milestone = LegacyValuationParityEngine().calculate("milestone", parsed)
    assert milestone.display_value == Decimal("205.47")


def test_missing_inputs_return_unavailable_instead_of_fabricating_value():
    result = LegacyValuationParityEngine().calculate(
        "peg", LegacyValuationInputs(symbol="NVDA", previous_close=close())
    )
    assert result.status == "unavailable"
    assert result.fair_value_per_share is None


def test_comparison_uses_two_decimal_display_contract():
    result = LegacyValuationParityEngine().calculate("milestone", inputs())
    comparison = compare_legacy_value(result, Decimal("205.47"))
    assert comparison["status"] == "matched"
    assert comparison["absolute_difference"] == "0.00"


def test_symbol_mismatch_is_rejected():
    import pytest
    with pytest.raises(ValueError, match="symbol must match"):
        LegacyValuationInputs(symbol="AMD", previous_close=close())
