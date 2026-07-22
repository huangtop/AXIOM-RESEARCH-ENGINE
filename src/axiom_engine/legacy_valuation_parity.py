from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from typing import Any, Mapping

from axiom_engine.previous_close import DailyClose

CENT = Decimal("0.01")


class LegacyValuationModel(StrEnum):
    PEG = "peg"
    PE = "pe"
    PS = "ps"
    PB = "pb"
    EV_EBITDA = "ev_ebitda"
    MILESTONE = "milestone"


@dataclass(frozen=True, slots=True)
class LegacyValuationInputs:
    symbol: str
    previous_close: DailyClose
    forward_eps: Decimal | None = None
    current_eps: Decimal | None = None
    growth_percent: Decimal | None = None
    target_peg: Decimal = Decimal("0.9")
    target_pe: Decimal | None = None
    forward_revenue_per_share: Decimal | None = None
    target_ps: Decimal | None = None
    book_value_per_share: Decimal | None = None
    target_pb: Decimal | None = None
    ebitda: Decimal | None = None
    target_ev_ebitda: Decimal | None = None
    net_debt: Decimal = Decimal("0")
    shares_outstanding: Decimal | None = None
    milestone_success_probability: Decimal = Decimal("0.2")
    milestone_success_multiple: Decimal = Decimal("3.0")
    milestone_failure_multiple: Decimal = Decimal("0.5")

    def __post_init__(self) -> None:
        normalized = self.symbol.strip().upper()
        object.__setattr__(self, "symbol", normalized)
        if normalized != self.previous_close.symbol:
            raise ValueError("symbol must match previous_close symbol")
        if not Decimal("0") <= self.milestone_success_probability <= Decimal("1"):
            raise ValueError("milestone_success_probability must be between zero and one")

    @classmethod
    def from_legacy_payload(
        cls, symbol: str, payload: Mapping[str, Any], previous_close: DailyClose
    ) -> LegacyValuationInputs:
        defaults = payload.get("default_params")
        defaults = defaults if isinstance(defaults, Mapping) else {}
        close = previous_close.close
        current_eps = _decimal(payload.get("market_consensus_eps_current"))
        current_pe = close / current_eps if current_eps and current_eps > 0 else None
        target_pb = _first_positive(payload.get("target_pb"), defaults.get("target_pb"))
        current_pb = _decimal(payload.get("pb"))
        if target_pb is None:
            target_pb = current_pb
        target_ps = _first_positive(payload.get("ps"), payload.get("current_ps"), payload.get("target_ps"))
        growth = _decimal(payload.get("growth_estimate"))
        if growth is not None and abs(growth) <= Decimal("3"):
            growth *= Decimal("100")
        net_debt = _decimal(payload.get("net_debt"))
        if net_debt is None:
            debt = _decimal(payload.get("total_debt"))
            cash = _decimal(payload.get("total_cash"))
            net_debt = (debt - cash) if debt is not None and cash is not None else Decimal("0")
        probability = _decimal(defaults.get("success_prob")) or Decimal("0.2")
        return cls(
            symbol=symbol,
            previous_close=previous_close,
            forward_eps=_decimal(payload.get("market_consensus_eps_forward")),
            current_eps=current_eps,
            growth_percent=growth,
            target_pe=current_pe,
            forward_revenue_per_share=_first_positive(
                payload.get("future_revenue_per_share"),
                _per_share(payload.get("revenue_estimate"), payload.get("shares_outstanding")),
            ),
            target_ps=target_ps,
            book_value_per_share=_decimal(payload.get("book_value_per_share")),
            target_pb=target_pb,
            ebitda=_first_positive(payload.get("ebitda_estimate"), payload.get("ebitda"), payload.get("operating_income")),
            target_ev_ebitda=Decimal("45") if growth is not None and growth > 50 else Decimal("35"),
            net_debt=net_debt,
            shares_outstanding=_decimal(payload.get("shares_outstanding")),
            milestone_success_probability=probability,
        )


@dataclass(frozen=True, slots=True)
class LegacyValuationResult:
    model: LegacyValuationModel
    fair_value_per_share: Decimal | None
    status: str
    reason: str | None = None

    @property
    def display_value(self) -> Decimal | None:
        return self.fair_value_per_share.quantize(CENT, rounding=ROUND_HALF_UP) if self.fair_value_per_share is not None else None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["model"] = self.model.value
        payload["fair_value_per_share"] = str(self.fair_value_per_share) if self.fair_value_per_share is not None else None
        payload["display_value"] = str(self.display_value) if self.display_value is not None else None
        return payload


class LegacyValuationParityEngine:
    def calculate_all(self, inputs: LegacyValuationInputs) -> tuple[LegacyValuationResult, ...]:
        return tuple(self.calculate(model, inputs) for model in LegacyValuationModel)

    def calculate(self, model: LegacyValuationModel | str, i: LegacyValuationInputs) -> LegacyValuationResult:
        m = LegacyValuationModel(model)
        value: Decimal | None = None
        reason: str | None = None
        if m is LegacyValuationModel.PEG:
            if _positive(i.forward_eps) and _positive(i.growth_percent) and _positive(i.target_peg):
                value = i.forward_eps * i.target_peg * i.growth_percent
            else:
                reason = "positive forward_eps, growth_percent and target_peg required"
        elif m is LegacyValuationModel.PE:
            if _positive(i.forward_eps) and _positive(i.target_pe):
                value = i.forward_eps * i.target_pe
            else:
                reason = "positive forward_eps and target_pe required"
        elif m is LegacyValuationModel.PS:
            if _positive(i.forward_revenue_per_share) and _positive(i.target_ps):
                value = i.forward_revenue_per_share * i.target_ps
            else:
                reason = "positive forward_revenue_per_share and target_ps required"
        elif m is LegacyValuationModel.PB:
            if _positive(i.book_value_per_share) and _positive(i.target_pb):
                value = i.book_value_per_share * i.target_pb
            else:
                reason = "positive book_value_per_share and target_pb required"
        elif m is LegacyValuationModel.EV_EBITDA:
            if _positive(i.ebitda) and _positive(i.target_ev_ebitda) and _positive(i.shares_outstanding):
                value = (i.ebitda * i.target_ev_ebitda - i.net_debt) / i.shares_outstanding
            else:
                reason = "positive ebitda, target_ev_ebitda and shares_outstanding required"
        else:
            p = i.milestone_success_probability
            value = i.previous_close.close * (
                i.milestone_success_multiple * p
                + i.milestone_failure_multiple * (Decimal("1") - p)
            )
        return LegacyValuationResult(m, value, "calculated" if value is not None else "unavailable", reason)


def compare_legacy_value(result: LegacyValuationResult, expected: Decimal, *, tolerance: Decimal = CENT) -> dict[str, Any]:
    if result.fair_value_per_share is None:
        return {"model": result.model.value, "status": "unavailable", "expected": str(expected), "actual": None}
    difference = abs(result.display_value - expected.quantize(CENT, rounding=ROUND_HALF_UP))
    return {
        "model": result.model.value,
        "status": "matched" if difference <= tolerance else "mismatched",
        "expected": str(expected.quantize(CENT, rounding=ROUND_HALF_UP)),
        "actual": str(result.display_value),
        "absolute_difference": str(difference),
    }


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _positive(value: Decimal | None) -> bool:
    return value is not None and value > 0


def _first_positive(*values: Any) -> Decimal | None:
    for value in values:
        parsed = value if isinstance(value, Decimal) else _decimal(value)
        if _positive(parsed):
            return parsed
    return None


def _per_share(total: Any, shares: Any) -> Decimal | None:
    total_value = _decimal(total)
    share_value = _decimal(shares)
    if _positive(total_value) and _positive(share_value):
        return total_value / share_value
    return None
