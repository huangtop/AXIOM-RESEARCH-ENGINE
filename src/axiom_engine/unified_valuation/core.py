from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from axiom_engine.seven_model_valuation import calculate_seven_models


MODEL_NAMES = (
    "dcf",
    "forward_pe",
    "peg",
    "forward_ps",
    "ev_ebitda",
    "forward_pb",
    "milestone",
)

MODEL_FAMILIES = {
    "dcf": "intrinsic_cash_flow",
    "forward_pe": "forward_earnings",
    "peg": "forward_earnings",
    "forward_ps": "forward_revenue",
    "ev_ebitda": "enterprise_operations",
    "forward_pb": "balance_sheet",
    "milestone": "event_probability",
}

BASE_FAMILY_PRIORS = {
    "intrinsic_cash_flow": Decimal("0.85"),
    "forward_earnings": Decimal("1.00"),
    "forward_revenue": Decimal("0.65"),
    "enterprise_operations": Decimal("0.85"),
    "balance_sheet": Decimal("0.40"),
    "event_probability": Decimal("0.25"),
}

MODEL_ASSUMPTION_KEYS = {
    "forward_pe": "target_forward_pe",
    "peg": "target_peg",
    "forward_ps": "target_forward_ps",
    "ev_ebitda": "target_ev_ebitda",
    "forward_pb": "target_forward_pb",
}

SCENARIO_MULTIPLIERS = {
    "bear": Decimal("0.85"),
    "base": Decimal("1.00"),
    "bull": Decimal("1.15"),
}


def _d(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _metric(layer: Mapping[str, Any], name: str) -> Decimal | None:
    payload = layer.get(name)
    return _d(payload.get("value")) if isinstance(payload, Mapping) else None


def _as_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _financial_shape(
    financials: Mapping[str, Any],
    estimates: Mapping[str, Any],
) -> tuple[str, dict[str, Decimal], list[str]]:
    priors = dict(BASE_FAMILY_PRIORS)
    reasons: list[str] = []

    revenue = _metric(financials, "revenue")
    net_income = _metric(financials, "net_income")
    fcf = _metric(financials, "free_cash_flow")
    forward_eps = _metric(estimates, "forward_eps")
    growth = _metric(estimates, "forward_eps_growth")
    margin = net_income / revenue if revenue and net_income is not None else None

    if net_income is not None and net_income <= 0:
        priors.update({
            "intrinsic_cash_flow": Decimal("0.35"),
            "forward_earnings": Decimal("0"),
            "forward_revenue": Decimal("1.20"),
            "enterprise_operations": Decimal("0.55"),
            "balance_sheet": Decimal("0.35"),
            "event_probability": Decimal("1.00"),
        })
        return "loss_making_or_pre_profit", priors, ["NON_POSITIVE_NET_INCOME"]

    if (
        margin is not None
        and margin >= Decimal("0.10")
        and fcf is not None
        and fcf > 0
        and forward_eps is not None
        and forward_eps > 0
        and growth is not None
        and growth > 0
    ):
        priors.update({
            "intrinsic_cash_flow": Decimal("0.70"),
            "forward_earnings": Decimal("1.35"),
            "forward_revenue": Decimal("0.75"),
            "enterprise_operations": Decimal("0.95"),
            "balance_sheet": Decimal("0.20"),
            "event_probability": Decimal("0.10"),
        })
        reasons.extend([
            "POSITIVE_FORWARD_EARNINGS",
            "POSITIVE_FREE_CASH_FLOW",
            "NET_MARGIN_AT_LEAST_10_PERCENT",
        ])
        if growth >= Decimal("0.30"):
            priors["forward_earnings"] *= Decimal("1.10")
            priors["forward_revenue"] *= Decimal("1.10")
            priors["intrinsic_cash_flow"] *= Decimal("0.90")
            reasons.append("HIGH_FORWARD_GROWTH")
        return "profitable_growth", priors, reasons

    if fcf is not None and fcf > 0 and (growth is None or growth < Decimal("0.10")):
        priors.update({
            "intrinsic_cash_flow": Decimal("1.20"),
            "forward_earnings": Decimal("1.05"),
            "forward_revenue": Decimal("0.35"),
            "enterprise_operations": Decimal("1.00"),
            "balance_sheet": Decimal("0.45"),
            "event_probability": Decimal("0"),
        })
        return "mature_cash_generator", priors, ["POSITIVE_FCF_LOW_GROWTH"]

    return "general_operating_company", priors, ["DEFAULT_FINANCIAL_SHAPE"]


def _quality_scores(
    model: Mapping[str, Any],
    financials: Mapping[str, Any],
    estimates: Mapping[str, Any],
) -> tuple[Decimal, Decimal]:
    dated: list[date] = []
    for layer in (financials, estimates):
        for payload in layer.values():
            if isinstance(payload, Mapping):
                observed = _as_date(payload.get("as_of_date"))
                if observed:
                    dated.append(observed)
    reference = max(dated, default=None)

    model_dates: list[date] = []
    for input_name in model.get("input_names") or []:
        for layer in (financials, estimates):
            payload = layer.get(input_name)
            if isinstance(payload, Mapping):
                observed = _as_date(payload.get("as_of_date"))
                if observed:
                    model_dates.append(observed)

    freshness = Decimal("1")
    newest = max(model_dates, default=None)
    if reference and newest:
        age = (reference - newest).days
        freshness = (
            Decimal("0.45") if age > 550
            else Decimal("0.65") if age > 370
            else Decimal("0.80") if age > 185
            else Decimal("1")
        )
    elif reference:
        freshness = Decimal("0.70")

    source = str(model.get("assumption_source") or "")
    assumption_quality = Decimal("0.70") if source.startswith("config/") else Decimal("1")
    return freshness, assumption_quality


def _scenario_value(base: Decimal, scenario: str) -> Decimal:
    return base * SCENARIO_MULTIPLIERS[scenario]


def build_unified_valuation(
    *,
    symbol: str,
    financials: Mapping[str, Any],
    estimates: Mapping[str, Any],
    assumptions: Mapping[str, Any],
    dcf_policy: Mapping[str, Any],
    assumption_roles: Mapping[str, str] | None = None,
    reference_price: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase-1 unified valuation service.

    This module is intentionally additive. It does not alter current API,
    publication, full-market coverage, or WordPress paths.
    """
    assumption_roles = assumption_roles or {}
    raw_models = calculate_seven_models(
        financials,
        estimates,
        assumptions,
        dcf_policy=dcf_policy,
    )

    archetype, family_priors, archetype_reasons = _financial_shape(
        financials, estimates
    )

    prepared: dict[str, dict[str, Any]] = {}
    raw_weights: dict[str, Decimal] = {}
    market_anchored: list[str] = []

    for name in MODEL_NAMES:
        raw = dict(raw_models.get(name) or {})
        status = raw.get("status") or "unavailable"
        family = MODEL_FAMILIES[name]
        fair_value = _d(raw.get("fair_value"))
        freshness, assumption_quality = _quality_scores(
            raw, financials, estimates
        )

        assumption_key = MODEL_ASSUMPTION_KEYS.get(name)
        role = assumption_roles.get(assumption_key or "", "independent")
        independent = role != "market_anchored"
        if not independent:
            market_anchored.append(name)

        suitability = family_priors.get(family, Decimal("0"))
        if status != "calculated" or fair_value is None or fair_value <= 0:
            suitability = Decimal("0")

        effective_raw = (
            suitability * freshness * assumption_quality
            if independent
            else Decimal("0")
        )
        raw_weights[name] = effective_raw

        prepared[name] = {
            **raw,
            "family": family,
            "suitability_score": format(suitability, "f"),
            "data_quality_score": format(freshness, "f"),
            "assumption_quality_score": format(assumption_quality, "f"),
            "assumption_role": role,
            "included_in_independent_aggregation": bool(effective_raw > 0),
            "effective_weight": "0",
            "bear_fair_value": (
                format(_scenario_value(fair_value, "bear"), "f")
                if fair_value is not None and fair_value > 0 else None
            ),
            "base_fair_value": (
                format(fair_value, "f")
                if fair_value is not None and fair_value > 0 else None
            ),
            "bull_fair_value": (
                format(_scenario_value(fair_value, "bull"), "f")
                if fair_value is not None and fair_value > 0 else None
            ),
        }

    total = sum(raw_weights.values(), Decimal("0"))
    normalized: dict[str, Decimal] = {}
    if total > 0:
        included_names = [name for name in MODEL_NAMES if raw_weights[name] > 0]

        running = Decimal("0")
        for name in included_names[:-1]:
            weight = raw_weights[name] / total
            normalized[name] = weight
            running += weight

        if included_names:
            # Force exact normalization in Decimal arithmetic so the published
            # weights sum to exactly 1 instead of 0.9999... from repeating ratios.
            normalized[included_names[-1]] = Decimal("1") - running

        for name in MODEL_NAMES:
            normalized.setdefault(name, Decimal("0"))
            prepared[name]["effective_weight"] = format(normalized[name], "f")
    else:
        normalized = {name: Decimal("0") for name in MODEL_NAMES}

    def aggregate(field: str) -> Decimal | None:
        rows: list[tuple[Decimal, Decimal]] = []
        for name in MODEL_NAMES:
            weight = normalized[name]
            value = _d(prepared[name].get(field))
            if weight > 0 and value is not None and value > 0:
                rows.append((value, weight))
        if not rows:
            return None
        weight_sum = sum((weight for _, weight in rows), Decimal("0"))
        return sum((value * weight for value, weight in rows), Decimal("0")) / weight_sum

    bear = aggregate("bear_fair_value")
    base = aggregate("base_fair_value")
    bull = aggregate("bull_fair_value")

    dominant_model = None
    if total > 0:
        dominant_model = max(MODEL_NAMES, key=lambda name: normalized[name])
        if normalized[dominant_model] <= 0:
            dominant_model = None

    price = _d((reference_price or {}).get("value"))

    def upside(value: Decimal | None) -> str | None:
        if value is None or price is None or price <= 0:
            return None
        return format((value / price) - Decimal("1"), "f")

    included = [name for name in MODEL_NAMES if normalized[name] > 0]
    excluded = [name for name in MODEL_NAMES if normalized[name] <= 0]

    confidence = (
        "unavailable" if not included
        else "high" if len(included) >= 4
        else "medium" if len(included) >= 2
        else "low"
    )

    return {
        "contract_version": "unified-valuation.v1",
        "symbol": symbol.upper(),
        "as_of_date": (reference_price or {}).get("as_of_date"),
        "currency": (reference_price or {}).get("currency"),
        "reference_price": dict(reference_price or {}),
        "headline": {
            "bear_fair_value": format(bear, "f") if bear is not None else None,
            "base_fair_value": format(base, "f") if base is not None else None,
            "bull_fair_value": format(bull, "f") if bull is not None else None,
            "bear_upside": upside(bear),
            "base_upside": upside(base),
            "bull_upside": upside(bull),
            "dominant_model": dominant_model,
            "dominant_family": MODEL_FAMILIES.get(dominant_model) if dominant_model else None,
            "confidence": confidence,
        },
        "scenarios": {
            "bear": {"status": "calculated" if bear is not None else "unavailable", "fair_value": format(bear, "f") if bear is not None else None},
            "base": {"status": "calculated" if base is not None else "unavailable", "fair_value": format(base, "f") if base is not None else None},
            "bull": {"status": "calculated" if bull is not None else "unavailable", "fair_value": format(bull, "f") if bull is not None else None},
        },
        "range": {
            "low": format(bear, "f") if bear is not None else None,
            "base": format(base, "f") if base is not None else None,
            "high": format(bull, "f") if bull is not None else None,
        },
        "models": prepared,
        "aggregation": {
            "methodology_version": "unified-dynamic-weight.v1",
            "financial_archetype": archetype,
            "included_models": included,
            "excluded_models": excluded,
            "normalized_weights": {
                name: format(normalized[name], "f") for name in MODEL_NAMES
            },
            "reason_codes": archetype_reasons,
        },
        "diagnostics": {
            "market_anchored_models": market_anchored,
            "warnings": [],
        },
    }