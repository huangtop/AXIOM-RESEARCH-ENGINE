from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Iterable

from axiom_engine.market_snapshot import MarketSnapshot


class EligibilityStatus(StrEnum):
    ELIGIBLE = "eligible"
    CONDITIONAL = "conditional"
    INELIGIBLE = "ineligible"


class EligibilityModel(StrEnum):
    DCF = "dcf"
    REVERSE_DCF = "reverse_dcf"
    MULTIPLES = "multiples"
    PEG = "peg"
    MILESTONE = "milestone"


@dataclass(frozen=True, slots=True)
class EligibilityReason:
    code: str
    message: str
    field: str | None = None

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("code cannot be empty")
        if not self.message.strip():
            raise ValueError("message cannot be empty")


@dataclass(frozen=True, slots=True)
class ModelEligibility:
    model: EligibilityModel
    status: EligibilityStatus
    reasons: tuple[EligibilityReason, ...] = ()
    missing_required_fields: tuple[str, ...] = ()
    missing_optional_fields: tuple[str, ...] = ()
    fallback_models: tuple[EligibilityModel, ...] = ()

    @property
    def can_run(self) -> bool:
        return self.status is not EligibilityStatus.INELIGIBLE

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True, slots=True)
class EligibilityInputs:
    """Provider-neutral facts used to determine which valuation models may run.

    Market fields come from ``MarketSnapshot``. Fundamental and research fields
    are explicit because Yahoo quotes alone are not authoritative enough to build
    DCF forecasts, peer assumptions, or milestone probabilities.
    """

    snapshot: MarketSnapshot
    forecast_free_cash_flows: tuple[Decimal, ...] = ()
    current_free_cash_flow: Decimal | None = None
    revenue: Decimal | None = None
    ebit: Decimal | None = None
    ebitda: Decimal | None = None
    net_income: Decimal | None = None
    book_value: Decimal | None = None
    forward_growth_rate: Decimal | None = None
    has_discount_rate_assumptions: bool = False
    has_terminal_value_assumptions: bool = False
    has_peer_multiple_assumptions: bool = False
    has_milestone_case: bool = False
    milestone_success_probability: Decimal | None = None

    def __post_init__(self) -> None:
        if self.milestone_success_probability is not None and not (
            Decimal("0") <= self.milestone_success_probability <= Decimal("1")
        ):
            raise ValueError("milestone_success_probability must be between zero and one")


@dataclass(frozen=True, slots=True)
class EligibilityReport:
    symbol: str
    decisions: tuple[ModelEligibility, ...]

    def __post_init__(self) -> None:
        models = [decision.model for decision in self.decisions]
        if len(models) != len(set(models)):
            raise ValueError("eligibility decisions must be unique by model")

    def for_model(self, model: EligibilityModel | str) -> ModelEligibility:
        try:
            normalized = EligibilityModel(model)
        except ValueError as exc:
            raise KeyError(str(model)) from exc
        for decision in self.decisions:
            if decision.model is normalized:
                return decision
        raise KeyError(normalized.value)

    @property
    def runnable_models(self) -> tuple[EligibilityModel, ...]:
        return tuple(decision.model for decision in self.decisions if decision.can_run)

    @property
    def preferred_models(self) -> tuple[EligibilityModel, ...]:
        eligible = tuple(
            decision.model
            for decision in self.decisions
            if decision.status is EligibilityStatus.ELIGIBLE
        )
        if eligible:
            return eligible
        return tuple(
            decision.model
            for decision in self.decisions
            if decision.status is EligibilityStatus.CONDITIONAL
        )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


class ModelEligibilityEngine:
    """Deterministically classify model readiness without running a valuation."""

    def evaluate(self, inputs: EligibilityInputs) -> EligibilityReport:
        return EligibilityReport(
            symbol=inputs.snapshot.symbol,
            decisions=(
                self._dcf(inputs),
                self._reverse_dcf(inputs),
                self._multiples(inputs),
                self._peg(inputs),
                self._milestone(inputs),
            ),
        )

    def _dcf(self, inputs: EligibilityInputs) -> ModelEligibility:
        missing: list[str] = []
        reasons: list[EligibilityReason] = []
        if not inputs.forecast_free_cash_flows:
            missing.append("forecast_free_cash_flows")
        if not inputs.has_discount_rate_assumptions:
            missing.append("discount_rate_assumptions")
        if not inputs.has_terminal_value_assumptions:
            missing.append("terminal_value_assumptions")
        if not _has_positive_shares(inputs.snapshot):
            missing.append("shares_outstanding")
        if missing:
            reasons.append(_missing_reason(EligibilityModel.DCF, missing))
            return _decision(
                EligibilityModel.DCF,
                EligibilityStatus.INELIGIBLE,
                reasons,
                missing,
                fallbacks=(EligibilityModel.MULTIPLES, EligibilityModel.PEG),
            )
        if all(value <= 0 for value in inputs.forecast_free_cash_flows):
            reasons.append(
                EligibilityReason(
                    "non_positive_forecast_fcf",
                    "DCF is conditional because every forecast free cash flow is non-positive.",
                    "forecast_free_cash_flows",
                )
            )
            return _decision(
                EligibilityModel.DCF,
                EligibilityStatus.CONDITIONAL,
                reasons,
                optional=("positive_forecast_free_cash_flow",),
                fallbacks=(EligibilityModel.MULTIPLES, EligibilityModel.MILESTONE),
            )
        return _decision(EligibilityModel.DCF, EligibilityStatus.ELIGIBLE)

    def _reverse_dcf(self, inputs: EligibilityInputs) -> ModelEligibility:
        missing: list[str] = []
        if not inputs.snapshot.has_market_price:
            missing.append("market_price")
        if inputs.current_free_cash_flow is None or inputs.current_free_cash_flow <= 0:
            missing.append("current_free_cash_flow")
        if not _has_positive_shares(inputs.snapshot):
            missing.append("shares_outstanding")
        if not inputs.has_discount_rate_assumptions:
            missing.append("discount_rate_assumptions")
        if not inputs.has_terminal_value_assumptions:
            missing.append("terminal_value_assumptions")
        if missing:
            return _decision(
                EligibilityModel.REVERSE_DCF,
                EligibilityStatus.INELIGIBLE,
                (_missing_reason(EligibilityModel.REVERSE_DCF, missing),),
                missing,
                fallbacks=(EligibilityModel.MULTIPLES,),
            )
        return _decision(EligibilityModel.REVERSE_DCF, EligibilityStatus.ELIGIBLE)

    def _multiples(self, inputs: EligibilityInputs) -> ModelEligibility:
        positive_denominators = tuple(
            name
            for name, value in (
                ("revenue", inputs.revenue),
                ("ebit", inputs.ebit),
                ("ebitda", inputs.ebitda),
                ("net_income", inputs.net_income),
                ("book_value", inputs.book_value),
                ("free_cash_flow", inputs.current_free_cash_flow),
            )
            if value is not None and value > 0
        )
        missing: list[str] = []
        if not positive_denominators:
            missing.append("positive_financial_denominator")
        if not inputs.has_peer_multiple_assumptions:
            missing.append("peer_multiple_assumptions")
        if not _has_positive_shares(inputs.snapshot):
            missing.append("shares_outstanding")
        if missing:
            return _decision(
                EligibilityModel.MULTIPLES,
                EligibilityStatus.INELIGIBLE,
                (_missing_reason(EligibilityModel.MULTIPLES, missing),),
                missing,
                fallbacks=(EligibilityModel.PEG, EligibilityModel.MILESTONE),
            )
        if len(positive_denominators) == 1:
            return _decision(
                EligibilityModel.MULTIPLES,
                EligibilityStatus.CONDITIONAL,
                (
                    EligibilityReason(
                        "single_multiple_basis",
                        "Multiples valuation is conditional because only one positive denominator is available.",
                        positive_denominators[0],
                    ),
                ),
                optional=("second_positive_financial_denominator",),
            )
        return _decision(EligibilityModel.MULTIPLES, EligibilityStatus.ELIGIBLE)

    def _peg(self, inputs: EligibilityInputs) -> ModelEligibility:
        missing: list[str] = []
        eps = inputs.snapshot.forward_earnings_per_share
        if eps is None or eps <= 0:
            missing.append("forward_earnings_per_share")
        if inputs.forward_growth_rate is None or inputs.forward_growth_rate <= 0:
            missing.append("forward_growth_rate")
        if missing:
            return _decision(
                EligibilityModel.PEG,
                EligibilityStatus.INELIGIBLE,
                (_missing_reason(EligibilityModel.PEG, missing),),
                missing,
                fallbacks=(EligibilityModel.MULTIPLES, EligibilityModel.MILESTONE),
            )
        optional: tuple[str, ...] = ()
        status = EligibilityStatus.ELIGIBLE
        reasons: tuple[EligibilityReason, ...] = ()
        if not inputs.snapshot.has_market_price:
            status = EligibilityStatus.CONDITIONAL
            optional = ("market_price",)
            reasons = (
                EligibilityReason(
                    "missing_market_price_for_upside",
                    "PEG can estimate fair value, but upside cannot be calculated without a market price.",
                    "market_price",
                ),
            )
        return _decision(EligibilityModel.PEG, status, reasons, optional=optional)

    def _milestone(self, inputs: EligibilityInputs) -> ModelEligibility:
        missing: list[str] = []
        if not inputs.snapshot.has_market_price:
            missing.append("market_price")
        if not inputs.has_milestone_case:
            missing.append("milestone_case")
        if inputs.milestone_success_probability is None:
            missing.append("milestone_success_probability")
        if missing:
            return _decision(
                EligibilityModel.MILESTONE,
                EligibilityStatus.INELIGIBLE,
                (_missing_reason(EligibilityModel.MILESTONE, missing),),
                missing,
                fallbacks=(EligibilityModel.MULTIPLES,),
            )
        return _decision(EligibilityModel.MILESTONE, EligibilityStatus.ELIGIBLE)


def _has_positive_shares(snapshot: MarketSnapshot) -> bool:
    return snapshot.shares_outstanding is not None and snapshot.shares_outstanding > 0


def _missing_reason(model: EligibilityModel, fields: Iterable[str]) -> EligibilityReason:
    names = tuple(fields)
    return EligibilityReason(
        code="missing_required_inputs",
        message=f"{model.value} is missing required inputs: {', '.join(names)}.",
    )


def _decision(
    model: EligibilityModel,
    status: EligibilityStatus,
    reasons: Iterable[EligibilityReason] = (),
    required: Iterable[str] = (),
    *,
    optional: Iterable[str] = (),
    fallbacks: Iterable[EligibilityModel] = (),
) -> ModelEligibility:
    return ModelEligibility(
        model=model,
        status=status,
        reasons=tuple(reasons),
        missing_required_fields=tuple(dict.fromkeys(required)),
        missing_optional_fields=tuple(dict.fromkeys(optional)),
        fallback_models=tuple(dict.fromkeys(fallbacks)),
    )


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serialize(item) for item in value]
    return value
