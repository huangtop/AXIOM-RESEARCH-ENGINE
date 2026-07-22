from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from axiom_engine.full_market_valuation_service import (
    FullMarketValuationRequest,
    FullMarketValuationService,
    ModelExecutionStatus,
)
from axiom_engine.market_snapshot import MarketSnapshot
from axiom_engine.model_eligibility import EligibilityModel
from axiom_engine.valuation_models import (
    CapitalStructure,
    IntrinsicValueInputs,
    MilestoneInputs,
    PEGInputs,
    ValuationIdentity,
)


class Provider:
    def __init__(self, snapshot: MarketSnapshot) -> None:
        self.value = snapshot
        self.calls: list[tuple[str, bool]] = []

    def snapshot(self, symbol: str, *, refresh: bool = False) -> MarketSnapshot:
        self.calls.append((symbol, refresh))
        return self.value


def identity() -> ValuationIdentity:
    return ValuationIdentity("apple", "aapl", "AAPL", "USD", date(2026, 7, 22))


def snapshot(**changes: object) -> MarketSnapshot:
    values: dict[str, object] = {
        "symbol": "AAPL",
        "company_name": "Apple Inc.",
        "currency": "USD",
        "observed_at": datetime(2026, 7, 22, tzinfo=timezone.utc),
        "regular_market_price": Decimal("200"),
        "shares_outstanding": Decimal("1000"),
        "forward_earnings_per_share": Decimal("10"),
        "provider": "test",
    }
    values.update(changes)
    return MarketSnapshot(**values)


def peg_inputs() -> IntrinsicValueInputs:
    key = identity()
    return IntrinsicValueInputs(
        identity=key,
        peg=PEGInputs(
            identity=key,
            forward_earnings_per_share=Decimal("1"),
            growth_rate=Decimal("0.20"),
            market_price=Decimal("1"),
        ),
    )


def test_request_normalizes_symbol_and_requires_matching_identity() -> None:
    request = FullMarketValuationRequest(" aapl ", peg_inputs())
    assert request.symbol == "AAPL"
    with pytest.raises(ValueError, match="match"):
        FullMarketValuationRequest("MSFT", peg_inputs())


def test_service_fetches_snapshot_and_enriches_peg_market_fields() -> None:
    provider = Provider(snapshot())
    result = FullMarketValuationService(provider).value(
        FullMarketValuationRequest("AAPL", peg_inputs(), refresh_market_data=True)
    )
    execution = result.for_model("peg")
    assert provider.calls == [("AAPL", True)]
    assert execution.status is ModelExecutionStatus.EXECUTED
    assert str(execution.result.forward_earnings_per_share) == "10"
    assert str(execution.result.market_price) == "200"
    assert result.executed_models == (EligibilityModel.PEG,)
    assert result.degraded is False


def test_requested_missing_model_is_explicitly_skipped() -> None:
    result = FullMarketValuationService(Provider(snapshot())).value(
        FullMarketValuationRequest(
            "AAPL",
            peg_inputs(),
            requested_models=(EligibilityModel.DCF, EligibilityModel.PEG),
        )
    )
    assert result.for_model("dcf").status is ModelExecutionStatus.SKIPPED
    assert result.for_model("dcf").reason_code == "input_not_supplied"
    assert result.for_model("peg").status is ModelExecutionStatus.EXECUTED
    assert result.degraded is True


def test_ineligible_supplied_model_is_skipped_before_engine_execution() -> None:
    key = identity()
    inputs = IntrinsicValueInputs(
        identity=key,
        peg=PEGInputs(
            identity=key,
            forward_earnings_per_share=Decimal("1"),
            growth_rate=Decimal("0"),
        ),
    )
    result = FullMarketValuationService(Provider(snapshot())).value(
        FullMarketValuationRequest("AAPL", inputs)
    )
    execution = result.for_model("peg")
    assert execution.status is ModelExecutionStatus.SKIPPED
    assert execution.reason_code == "model_ineligible"


def test_milestone_uses_live_market_price() -> None:
    key = identity()
    inputs = IntrinsicValueInputs(
        identity=key,
        milestone=MilestoneInputs(
            identity=key,
            current_price=Decimal("1"),
            success_probability=Decimal("0.5"),
        ),
    )
    result = FullMarketValuationService(Provider(snapshot())).value(
        FullMarketValuationRequest("AAPL", inputs)
    )
    execution = result.for_model("milestone")
    assert execution.status is ModelExecutionStatus.EXECUTED
    assert str(execution.result.current_price) == "200"
    assert str(execution.result.fair_value_per_share) == "350.00"


def test_snapshot_symbol_mismatch_fails_closed() -> None:
    with pytest.raises(ValueError, match="snapshot symbol"):
        FullMarketValuationService(Provider(snapshot(symbol="MSFT"))).value(
            FullMarketValuationRequest("AAPL", peg_inputs())
        )


def test_duplicate_requested_models_are_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        FullMarketValuationRequest(
            "AAPL",
            peg_inputs(),
            requested_models=(EligibilityModel.PEG, EligibilityModel.PEG),
        )


def test_result_serializes_nested_decimal_and_enum_values() -> None:
    result = FullMarketValuationService(Provider(snapshot())).value(
        FullMarketValuationRequest("AAPL", peg_inputs())
    )
    payload = result.to_dict()
    assert payload["executions"][0]["status"] == "executed"
    assert payload["executions"][0]["result"]["fair_value_per_share"] == "180.000"


def test_model_failure_is_isolated_and_reported() -> None:
    class BrokenEngine:
        def calculate(self, _inputs: IntrinsicValueInputs) -> object:
            raise RuntimeError("boom")

    result = FullMarketValuationService(
        Provider(snapshot()),
        intrinsic_value_engine=BrokenEngine(),  # type: ignore[arg-type]
    ).value(FullMarketValuationRequest("AAPL", peg_inputs()))
    execution = result.for_model("peg")
    assert execution.status is ModelExecutionStatus.FAILED
    assert execution.reason_code == "model_execution_failed"
    assert "RuntimeError: boom" == execution.message


def test_capital_structure_helper_remains_compatible() -> None:
    capital = CapitalStructure(diluted_shares_outstanding=Decimal("5"))
    assert capital.diluted_shares_outstanding == Decimal("5")
