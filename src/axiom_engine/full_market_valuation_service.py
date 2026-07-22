from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from axiom_engine.intrinsic_value_engine import IntrinsicValueEngine
from axiom_engine.market_snapshot import MarketSnapshot
from axiom_engine.model_eligibility import (
    EligibilityInputs,
    EligibilityModel,
    EligibilityReport,
    ModelEligibility,
    ModelEligibilityEngine,
)
from axiom_engine.valuation_models import (
    IntrinsicValueInputs,
    IntrinsicValueResult,
    MultiplesFinancials,
)


class MarketSnapshotProvider(Protocol):
    def snapshot(self, symbol: str, *, refresh: bool = False) -> MarketSnapshot: ...


class ModelExecutionStatus(StrEnum):
    EXECUTED = "executed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class FullMarketValuationRequest:
    symbol: str
    valuation_inputs: IntrinsicValueInputs
    requested_models: tuple[EligibilityModel, ...] = ()
    refresh_market_data: bool = False

    def __post_init__(self) -> None:
        normalized = self.symbol.strip().upper()
        if not normalized:
            raise ValueError("symbol cannot be empty")
        object.__setattr__(self, "symbol", normalized)
        if self.valuation_inputs.identity.ticker.strip().upper() != normalized:
            raise ValueError("request symbol must match valuation identity ticker")
        if len(self.requested_models) != len(set(self.requested_models)):
            raise ValueError("requested_models must be unique")


@dataclass(frozen=True, slots=True)
class ModelExecution:
    model: EligibilityModel
    status: ModelExecutionStatus
    eligibility: ModelEligibility
    result: Any | None = None
    reason_code: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.status is ModelExecutionStatus.EXECUTED and self.result is None:
            raise ValueError("executed model must include a result")
        if self.status is not ModelExecutionStatus.EXECUTED and self.reason_code is None:
            raise ValueError("skipped or failed model must include a reason_code")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True, slots=True)
class FullMarketValuationResult:
    symbol: str
    snapshot: MarketSnapshot
    eligibility: EligibilityReport
    executions: tuple[ModelExecution, ...]
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        models = [execution.model for execution in self.executions]
        if len(models) != len(set(models)):
            raise ValueError("executions must be unique by model")

    def for_model(self, model: EligibilityModel | str) -> ModelExecution:
        normalized = EligibilityModel(model)
        for execution in self.executions:
            if execution.model is normalized:
                return execution
        raise KeyError(normalized.value)

    @property
    def executed_models(self) -> tuple[EligibilityModel, ...]:
        return tuple(
            execution.model
            for execution in self.executions
            if execution.status is ModelExecutionStatus.EXECUTED
        )

    @property
    def degraded(self) -> bool:
        return any(
            execution.status is not ModelExecutionStatus.EXECUTED
            for execution in self.executions
        )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


class FullMarketValuationService:
    """Fetch market context, evaluate readiness, and isolate model execution."""

    def __init__(
        self,
        market_data: MarketSnapshotProvider,
        *,
        eligibility_engine: ModelEligibilityEngine | None = None,
        intrinsic_value_engine: IntrinsicValueEngine | None = None,
    ) -> None:
        self._market_data = market_data
        self._eligibility_engine = eligibility_engine or ModelEligibilityEngine()
        self._intrinsic_value_engine = intrinsic_value_engine or IntrinsicValueEngine()

    def value(self, request: FullMarketValuationRequest) -> FullMarketValuationResult:
        snapshot = self._market_data.snapshot(
            request.symbol,
            refresh=request.refresh_market_data,
        )
        if snapshot.symbol.upper() != request.symbol:
            raise ValueError("market snapshot symbol does not match request symbol")

        enriched = _enrich_inputs(request.valuation_inputs, snapshot)
        report = self._eligibility_engine.evaluate(_eligibility_inputs(enriched, snapshot))
        selected = request.requested_models or _supplied_models(enriched)

        executions = tuple(
            self._execute(model, enriched, report.for_model(model)) for model in selected
        )
        warnings = tuple(
            f"{execution.model.value}: {execution.reason_code}"
            for execution in executions
            if execution.status is not ModelExecutionStatus.EXECUTED
        )
        return FullMarketValuationResult(
            symbol=request.symbol,
            snapshot=snapshot,
            eligibility=report,
            executions=executions,
            warnings=warnings,
        )

    def _execute(
        self,
        model: EligibilityModel,
        inputs: IntrinsicValueInputs,
        eligibility: ModelEligibility,
    ) -> ModelExecution:
        model_input = _input_for_model(inputs, model)
        if model_input is None:
            return ModelExecution(
                model=model,
                status=ModelExecutionStatus.SKIPPED,
                eligibility=eligibility,
                reason_code="input_not_supplied",
                message=f"No {model.value} input was supplied.",
            )
        if not eligibility.can_run:
            return ModelExecution(
                model=model,
                status=ModelExecutionStatus.SKIPPED,
                eligibility=eligibility,
                reason_code="model_ineligible",
                message="Model was skipped by the eligibility engine.",
            )

        try:
            result = self._intrinsic_value_engine.calculate(
                _single_model_inputs(inputs, model, model_input)
            )
        except Exception as exc:  # model isolation is an orchestration boundary
            return ModelExecution(
                model=model,
                status=ModelExecutionStatus.FAILED,
                eligibility=eligibility,
                reason_code="model_execution_failed",
                message=f"{type(exc).__name__}: {exc}",
            )
        return ModelExecution(
            model=model,
            status=ModelExecutionStatus.EXECUTED,
            eligibility=eligibility,
            result=_result_for_model(result, model),
        )


def _enrich_inputs(inputs: IntrinsicValueInputs, snapshot: MarketSnapshot) -> IntrinsicValueInputs:
    shares = snapshot.shares_outstanding
    market_price = snapshot.regular_market_price
    dcf = inputs.dcf
    reverse_dcf = inputs.reverse_dcf
    multiples = inputs.multiples
    peg = inputs.peg
    milestone = inputs.milestone

    if dcf is not None and shares is not None:
        dcf = replace(
            dcf,
            capital_structure=replace(
                dcf.capital_structure,
                diluted_shares_outstanding=shares,
            ),
        )
    if reverse_dcf is not None:
        capital = reverse_dcf.capital_structure
        if shares is not None:
            capital = replace(capital, diluted_shares_outstanding=shares)
        reverse_dcf = replace(
            reverse_dcf,
            capital_structure=capital,
            market_price=market_price or reverse_dcf.market_price,
        )
    if multiples is not None:
        capital = multiples.capital_structure
        financials = multiples.financials
        if shares is not None:
            capital = replace(capital, diluted_shares_outstanding=shares)
            financials = replace(financials, basic_shares_outstanding=shares)
        multiples = replace(
            multiples,
            capital_structure=capital,
            financials=financials,
            market_price=market_price if market_price is not None else multiples.market_price,
        )
    if peg is not None:
        peg = replace(
            peg,
            forward_earnings_per_share=(
                snapshot.forward_earnings_per_share
                if snapshot.forward_earnings_per_share is not None
                else peg.forward_earnings_per_share
            ),
            market_price=market_price if market_price is not None else peg.market_price,
        )
    if milestone is not None and market_price is not None:
        milestone = replace(milestone, current_price=market_price)

    return IntrinsicValueInputs(
        identity=inputs.identity,
        dcf=dcf,
        reverse_dcf=reverse_dcf,
        multiples=multiples,
        market_price=market_price if market_price is not None else inputs.market_price,
        model_version=inputs.model_version,
        peg=peg,
        milestone=milestone,
    )


def _eligibility_inputs(
    inputs: IntrinsicValueInputs,
    snapshot: MarketSnapshot,
) -> EligibilityInputs:
    dcf = inputs.dcf
    reverse = inputs.reverse_dcf
    multiples = inputs.multiples
    peg = inputs.peg
    milestone = inputs.milestone
    financials = multiples.financials if multiples is not None else MultiplesFinancials()
    return EligibilityInputs(
        snapshot=snapshot,
        forecast_free_cash_flows=tuple(
            period.free_cash_flow
            for period in dcf.forecasts
            if period.free_cash_flow is not None
        ) if dcf is not None else (),
        current_free_cash_flow=(
            reverse.current_free_cash_flow
            if reverse is not None
            else financials.free_cash_flow
        ),
        revenue=financials.revenue,
        ebit=financials.ebit,
        ebitda=financials.ebitda,
        net_income=financials.net_income,
        book_value=financials.book_value,
        forward_growth_rate=peg.growth_rate if peg is not None else None,
        has_discount_rate_assumptions=dcf is not None or reverse is not None,
        has_terminal_value_assumptions=dcf is not None or reverse is not None,
        has_peer_multiple_assumptions=bool(multiples and multiples.assumptions),
        has_milestone_case=milestone is not None,
        milestone_success_probability=(
            milestone.success_probability if milestone is not None else None
        ),
    )


def _supplied_models(inputs: IntrinsicValueInputs) -> tuple[EligibilityModel, ...]:
    return tuple(
        model
        for model in EligibilityModel
        if _input_for_model(inputs, model) is not None
    )


def _input_for_model(inputs: IntrinsicValueInputs, model: EligibilityModel) -> Any | None:
    return {
        EligibilityModel.DCF: inputs.dcf,
        EligibilityModel.REVERSE_DCF: inputs.reverse_dcf,
        EligibilityModel.MULTIPLES: inputs.multiples,
        EligibilityModel.PEG: inputs.peg,
        EligibilityModel.MILESTONE: inputs.milestone,
    }[model]


def _single_model_inputs(
    inputs: IntrinsicValueInputs,
    model: EligibilityModel,
    model_input: Any,
) -> IntrinsicValueInputs:
    kwargs: dict[str, Any] = {
        "identity": inputs.identity,
        "market_price": inputs.market_price,
        "model_version": inputs.model_version,
        model.value: model_input,
    }
    return IntrinsicValueInputs(**kwargs)


def _result_for_model(result: IntrinsicValueResult, model: EligibilityModel) -> Any:
    value = getattr(result, model.value)
    if value is None:
        raise RuntimeError(f"{model.value} engine returned no result")
    return value


def _serialize(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serialize(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
