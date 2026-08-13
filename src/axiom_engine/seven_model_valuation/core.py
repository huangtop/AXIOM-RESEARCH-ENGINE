from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


MODEL_NAMES = ("dcf", "forward_pe", "peg", "forward_ps", "ev_ebitda", "forward_pb", "milestone")


def _d(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _value(layer: Mapping[str, Any], name: str) -> Decimal | None:
    payload = layer.get(name)
    return _d(payload.get("value")) if isinstance(payload, Mapping) else None


def _result(
    value: Decimal | None,
    formula: str,
    inputs: list[str],
    missing: list[str],
    *,
    assumption_source: str,
) -> dict[str, Any]:
    valid = value is not None and value > 0
    return {
        "status": "calculated" if valid else "unavailable",
        "fair_value": format(value, "f") if valid else None,
        "formula_version": formula,
        "assumption_source": assumption_source,
        "input_names": inputs,
        "reason_code": None if valid else "MISSING_REQUIRED_INPUT" if missing else "NON_POSITIVE_FAIR_VALUE",
        "missing_inputs": missing,
    }


def calculate_seven_models(
    financials: Mapping[str, Any],
    estimates: Mapping[str, Any],
    assumptions: Mapping[str, Any],
    *,
    dcf_policy: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    fcf = _value(financials, "free_cash_flow")
    shares = _value(financials, "diluted_shares_outstanding")
    cash = _value(financials, "cash_and_cash_equivalents")
    debt = _value(financials, "total_debt")
    book_value_per_share = _value(financials, "book_value_per_share")
    ebitda = _value(estimates, "forward_ebitda") or _value(estimates, "ebitda_ttm") or _value(financials, "ebitda")
    forward_eps = _value(estimates, "forward_eps")
    growth = _value(estimates, "forward_eps_growth")
    forward_revenue = _value(estimates, "forward_revenue")

    growth_rate = _d(dcf_policy.get("default_growth"))
    discount_rate = _d(dcf_policy.get("discount_rate"))
    terminal_growth = _d(dcf_policy.get("terminal_growth"))
    years = int(dcf_policy.get("forecast_years") or 5)
    dcf_missing = [
        name
        for name, value in (
            ("free_cash_flow", fcf),
            ("cash_and_cash_equivalents", cash),
            ("total_debt", debt),
            ("diluted_shares_outstanding", shares),
            ("discount_rate", discount_rate),
            ("terminal_growth", terminal_growth),
            ("growth_rate", growth_rate),
        )
        if value is None
    ]
    dcf_value = None
    if not dcf_missing and shares and shares > 0 and discount_rate and terminal_growth is not None and growth_rate is not None and discount_rate > terminal_growth:
        projected = fcf
        enterprise = Decimal("0")
        for year in range(1, years + 1):
            projected *= Decimal("1") + growth_rate
            enterprise += projected / ((Decimal("1") + discount_rate) ** year)
        terminal = projected * (Decimal("1") + terminal_growth) / (discount_rate - terminal_growth)
        enterprise += terminal / ((Decimal("1") + discount_rate) ** years)
        dcf_value = (enterprise + cash - debt) / shares

    target_pe = _d(assumptions.get("target_forward_pe"))
    target_peg = _d(assumptions.get("target_peg"))
    target_ps = _d(assumptions.get("target_forward_ps"))
    target_ev_ebitda = _d(assumptions.get("target_ev_ebitda"))
    target_pb = _d(assumptions.get("target_forward_pb"))
    success_probability = _d(assumptions.get("milestone_success_probability"))
    success_value = _d(assumptions.get("milestone_success_value_per_share"))
    failure_value = _d(assumptions.get("milestone_failure_value_per_share"))

    def product(values: list[Decimal | None]) -> Decimal | None:
        if any(value is None for value in values):
            return None
        result = Decimal("1")
        for value in values:
            if value is not None:
                result *= value
        return result

    forward_pe_value = product([forward_eps, target_pe])
    peg_growth = growth if growth is not None and Decimal("0") < growth <= Decimal("1") else None
    peg_value = product([forward_eps, peg_growth * 100 if peg_growth is not None else None, target_peg])
    forward_ps_value = forward_revenue / shares * target_ps if forward_revenue is not None and shares and target_ps is not None else None
    ev_value = ((ebitda * target_ev_ebitda) - debt + cash) / shares if ebitda is not None and target_ev_ebitda is not None and debt is not None and cash is not None and shares else None
    pb_value = book_value_per_share * target_pb if book_value_per_share is not None and target_pb is not None else None
    milestone_value = success_probability * success_value + (Decimal("1") - success_probability) * failure_value if success_probability is not None and success_value is not None and failure_value is not None and Decimal("0") <= success_probability <= Decimal("1") else None

    return {
        "dcf": _result(dcf_value, "dcf-fair-value.v031v.5", ["free_cash_flow", "cash_and_cash_equivalents", "total_debt", "diluted_shares_outstanding", "growth_rate", "discount_rate", "terminal_growth"], dcf_missing, assumption_source="config/fair_value_snapshot.v030.14.0.json"),
        "forward_pe": _result(forward_pe_value, "forward-pe-fair-value.v031v.5", ["forward_eps", "target_forward_pe"], [name for name, value in (("forward_eps", forward_eps), ("target_forward_pe", target_pe)) if value is None], assumption_source="knowledge.valuation_assumptions"),
        "peg": _result(peg_value, "peg-fair-value.v031v.5", ["forward_eps", "forward_eps_growth", "target_peg"], [name for name, value in (("forward_eps", forward_eps), ("forward_eps_growth", peg_growth), ("target_peg", target_peg)) if value is None], assumption_source="knowledge.valuation_assumptions"),
        "forward_ps": _result(forward_ps_value, "forward-ps-fair-value.v031v.5", ["forward_revenue", "shares", "target_forward_ps"], [name for name, value in (("forward_revenue", forward_revenue), ("shares", shares), ("target_forward_ps", target_ps)) if value is None], assumption_source="knowledge.valuation_assumptions"),
        "ev_ebitda": _result(ev_value, "ev-ebitda-fair-value.v031v.6", ["forward_ebitda_or_ebitda_ttm", "cash", "debt", "shares", "target_ev_ebitda"], [name for name, value in (("forward_ebitda_or_ebitda_ttm", ebitda), ("cash", cash), ("debt", debt), ("shares", shares), ("target_ev_ebitda", target_ev_ebitda)) if value is None], assumption_source="knowledge.valuation_assumptions"),
        "forward_pb": _result(pb_value, "forward-pb-fair-value.v031v.5", ["book_value_per_share", "target_forward_pb"], [name for name, value in (("book_value_per_share", book_value_per_share), ("target_forward_pb", target_pb)) if value is None], assumption_source="knowledge.valuation_assumptions"),
        "milestone": _result(milestone_value, "milestone-fair-value.v031v.5", ["success_probability", "success_value_per_share", "failure_value_per_share"], [name for name, value in (("success_probability", success_probability), ("success_value_per_share", success_value), ("failure_value_per_share", failure_value)) if value is None], assumption_source="knowledge.valuation_assumptions"),
    }
