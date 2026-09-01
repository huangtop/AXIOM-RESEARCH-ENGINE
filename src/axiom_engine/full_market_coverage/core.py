from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote
from zipfile import BadZipFile, ZipFile

from axiom_engine.coverage_policy import CoveragePolicyService
from axiom_engine.unified_valuation import build_unified_valuation


MODELS = (
    "dcf",
    "forward_pe",
    "peg",
    "forward_ps",
    "ev_ebitda",
    "forward_pb",
    "milestone",
)



# Primary Business routing changes family preference only.  It does not create
# inputs, manufacture calculated models, or turn Primary Business into thematic
# evidence.  DCF stays diagnostic-only globally.


class FullMarketCoverageError(RuntimeError):
    pass


class FullMarketCoverageNotFound(FullMarketCoverageError):
    pass


def _load(path: Path, *, default: Any = None) -> Any:
    if not path.is_file() and default is not None:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FullMarketCoverageError(f"cannot read {path}: {exc}") from exc


def _number(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _latest(
    rows: list[Mapping[str, Any]],
    metric_field: str,
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        metric = str(row.get(metric_field) or "").strip().lower()
        if not metric:
            continue
        current = result.get(metric)
        key = str(
            row.get("period_end")
            or row.get("as_of_date")
            or row.get("observed_at")
            or ""
        )
        old = str(
            (current or {}).get("period_end")
            or (current or {}).get("as_of_date")
            or (current or {}).get("observed_at")
            or ""
        )
        if key >= old:
            result[metric] = row
    return result


def _metric(
    row: Mapping[str, Any] | None,
    *,
    source_id_field: str,
) -> dict[str, Any]:
    if not row:
        return {
            "status": "unavailable",
            "value": None,
            "reason_code": "canonical_metric_not_populated",
            "source_record_ids": [],
        }
    result = {
        "status": "ready",
        "value": str(row.get("value")),
        "unit": row.get("unit"),
        "currency": row.get("currency"),
        "as_of_date": row.get("period_end") or row.get("as_of_date"),
        "reason_code": None,
        "source_record_ids": (
            [row.get(source_id_field)] if row.get(source_id_field) else []
        ),
    }
    for key in (
        "forecast_basis", "horizon", "estimate_horizon", "fiscal_year",
        "period_start", "period_end", "growth_from_period", "growth_to_period",
        "growth_kind", "provenance", "is_proxy", "source",
    ):
        if row.get(key) not in (None, ""):
            result[key] = row.get(key)
    return result


def _snapshot_metric(
    row: Mapping[str, Any],
    field: str,
    *,
    ticker: str,
    unit: str | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    value = _number(row.get(field))
    if value is None:
        return {
            "status": "unavailable",
            "value": None,
            "reason_code": "provider_metric_not_populated",
            "source_record_ids": [],
        }
    return {
        "status": "ready",
        "value": format(value, "f"),
        "unit": unit,
        "currency": currency,
        "as_of_date": row.get("fetched_at") or row.get("last_refresh"),
        "reason_code": None,
        "source_record_ids": [f"yahoo-company-snapshot:{ticker}:{field}"],
        "provenance": "yahoo_company_snapshot_fallback",
    }


def _derived(
    value: Decimal | None,
    formula: str,
    source_ids: list[str],
    reason: str,
) -> dict[str, Any]:
    return {
        "status": "ready" if value is not None else "unavailable",
        "value": format(value, "f") if value is not None else None,
        "reason_code": None if value is not None else reason,
        "formula_version": formula,
        "source_record_ids": source_ids,
    }


def _retired_dual_fy_legacy_models(snapshot: Mapping[str, Any], financials: Mapping[str, Any], assumptions: Mapping[str, Any], market: Mapping[str, Any], dcf_policy: Mapping[str, Any]) -> dict[str, Any]:
    annual = snapshot.get("annual_estimates") or {}
    if not isinstance(annual, Mapping):
        annual = {}
    def num(value: Any) -> Decimal | None:
        return _number(value)
    price = num(market.get("current_price")) or num(snapshot.get("previous_close"))
    shares = num(snapshot.get("shares_outstanding")) or num((financials.get("diluted_shares_outstanding") or {}).get("value"))
    # The market-anchored P/E numerator and denominator must share the same
    # provider/as-of basis. SEC-derived EPS can represent a different period.
    trailing_eps = num(snapshot.get("trailing_eps")) or num((financials.get("trailing_eps") or {}).get("value"))
    revenue_ttm = num(snapshot.get("revenue_ttm")) or num((financials.get("revenue") or {}).get("value"))
    cash = num((financials.get("cash_and_cash_equivalents") or {}).get("value")) or num(snapshot.get("total_cash")) or Decimal("0")
    debt = num((financials.get("total_debt") or {}).get("value")) or num(snapshot.get("total_debt")) or Decimal("0")
    ebitda = num(snapshot.get("ebitda_ttm")) or num((financials.get("ebitda") or {}).get("value"))
    bvps = num((financials.get("book_value_per_share") or {}).get("value"))
    fcf = num((financials.get("free_cash_flow") or {}).get("value"))
    current_pe = price / trailing_eps if price and trailing_eps and trailing_eps > 0 else (num(snapshot.get("trailing_pe")) or Decimal("15"))
    current_ps = price * shares / revenue_ttm if price and shares and revenue_ttm and revenue_ttm > 0 else Decimal("8")
    current_pb = num(snapshot.get("price_to_book")) or num(assumptions.get("target_forward_pb")) or Decimal("5.5")
    current_ev = num(snapshot.get("enterprise_to_ebitda"))
    target_peg = Decimal("0.9")  # AXIOM CURRENT_FY legacy PEG contract
    success_prob = num(assumptions.get("milestone_success_probability")) or Decimal("0.5")
    success_prob = min(Decimal("1"), max(Decimal("0"), success_prob))
    dcf_value = None
    if fcf is not None and shares is not None and shares > 0:
        growth = num(dcf_policy.get("default_growth")) or Decimal("0.08")
        discount = num(dcf_policy.get("discount_rate")) or Decimal("0.10")
        tg = num(dcf_policy.get("terminal_growth")) or Decimal("0.03")
        years = int(dcf_policy.get("forecast_years") or 5)
        if discount > tg:
            projected = fcf
            enterprise = Decimal("0")
            for year in range(1, years + 1):
                projected *= Decimal("1") + growth
                enterprise += projected / ((Decimal("1") + discount) ** year)
            terminal = projected * (Decimal("1") + tg) / (discount - tg)
            enterprise += terminal / ((Decimal("1") + discount) ** years)
            candidate = (enterprise + cash - debt) / shares
            if candidate > 0:
                dcf_value = candidate
    out = {}
    for basis in ("CURRENT_FY", "NEXT_FY"):
        row = annual.get(basis) or {}
        eps = num(row.get("eps"))
        revenue = num(row.get("revenue"))
        growth = num(row.get("peg_growth"))
        growth_pct = growth * Decimal("100") if growth and growth > 0 else None
        pe = eps * current_pe if eps and eps > 0 else price
        peg = eps * target_peg * growth_pct if eps and eps > 0 and growth_pct else pe
        ps = revenue / shares * current_ps if revenue and revenue > 0 and shares and shares > 0 else price
        pb = bvps * current_pb if bvps and bvps > 0 else price
        ev_mult = current_ev if current_ev and current_ev > 0 else (Decimal("45") if growth and growth > Decimal("0.50") else Decimal("35"))
        ev = ((ebitda * ev_mult) - debt + cash) / shares if ebitda and ebitda > 0 and shares and shares > 0 else price
        milestone = price * (Decimal("3") * success_prob + Decimal("0.5") * (Decimal("1") - success_prob)) if price else pe
        dcf = dcf_value if dcf_value is not None else price
        def model(value, mode="formula", note=None):
            return {"status": "calculated", "fair_value": format(value, "f") if value is not None else None, "calculation_mode": mode, "note": note}
        out[basis] = {
            "estimate_basis": basis,
            "eps": format(eps, "f") if eps is not None else None,
            "revenue": format(revenue, "f") if revenue is not None else None,
            "peg_growth": format(growth, "f") if growth is not None else None,
            "growth_basis": row.get("growth_basis"),
            "model_count": 7,
            "models": {
                "dcf": model(dcf, "formula" if dcf_value is not None else "market_anchor_fallback"),
                "forward_pe": model(pe),
                "peg": model(peg, note="growth sets implied P/E; EPS is not projected a second time"),
                "forward_ps": model(ps),
                "ev_ebitda": model(ev, "formula" if ebitda and ebitda > 0 else "market_anchor_fallback"),
                "forward_pb": model(pb, "formula" if bvps and bvps > 0 else "market_anchor_fallback"),
                "milestone": model(milestone),
            },
        }
    return out



def _dual_fy_seven_models(
    snapshot: Mapping[str, Any],
    financials: Mapping[str, Any],
    assumptions: Mapping[str, Any],
    market: Mapping[str, Any],
    dcf_policy: Mapping[str, Any],
) -> dict[str, Any]:
    annual = snapshot.get("annual_estimates") or {}
    if not isinstance(annual, Mapping):
        annual = {}

    def num(value: Any) -> Decimal | None:
        return _number(value)

    price = num(market.get("current_price")) or num(snapshot.get("previous_close"))
    shares = num(snapshot.get("shares_outstanding")) or num((financials.get("diluted_shares_outstanding") or {}).get("value"))
    # Keep both sides of the observed P/E on the same provider/as-of basis.
    trailing_eps = num(snapshot.get("trailing_eps")) or num((financials.get("trailing_eps") or {}).get("value"))
    revenue_ttm = num(snapshot.get("revenue_ttm")) or num((financials.get("revenue") or {}).get("value"))
    cash = num((financials.get("cash_and_cash_equivalents") or {}).get("value")) or num(snapshot.get("total_cash")) or Decimal("0")
    debt = num((financials.get("total_debt") or {}).get("value")) or num(snapshot.get("total_debt")) or Decimal("0")
    ebitda = num(snapshot.get("ebitda_ttm")) or num((financials.get("ebitda") or {}).get("value"))
    bvps = num((financials.get("book_value_per_share") or {}).get("value"))
    fcf = num((financials.get("free_cash_flow") or {}).get("value"))

    current_pe = price / trailing_eps if price is not None and trailing_eps is not None and trailing_eps > 0 else (num(snapshot.get("trailing_pe")) or Decimal("15"))
    current_ps = price * shares / revenue_ttm if price is not None and shares is not None and revenue_ttm is not None and revenue_ttm > 0 else Decimal("8")
    current_pb = num(snapshot.get("price_to_book")) or num(assumptions.get("target_forward_pb")) or Decimal("5.5")
    current_ev_multiple = num(snapshot.get("enterprise_to_ebitda"))
    target_peg = Decimal("0.9")  # AXIOM CURRENT_FY legacy PEG contract
    success_probability = num(assumptions.get("milestone_success_probability")) or Decimal("0.5")
    success_probability = max(Decimal("0"), min(Decimal("1"), success_probability))

    dcf_value = None
    if fcf is not None and shares is not None and shares > 0:
        growth = num(dcf_policy.get("default_growth")) or Decimal("0.08")
        discount_rate = num(dcf_policy.get("discount_rate")) or Decimal("0.10")
        terminal_growth = num(dcf_policy.get("terminal_growth")) or Decimal("0.03")
        years = int(dcf_policy.get("forecast_years") or 5)
        if discount_rate > terminal_growth:
            projected = fcf
            enterprise = Decimal("0")
            for year in range(1, years + 1):
                projected *= Decimal("1") + growth
                enterprise += projected / ((Decimal("1") + discount_rate) ** year)
            terminal = projected * (Decimal("1") + terminal_growth) / (discount_rate - terminal_growth)
            enterprise += terminal / ((Decimal("1") + discount_rate) ** years)
            candidate = (enterprise + cash - debt) / shares
            if candidate > 0:
                dcf_value = candidate

    def model(
        value: Decimal | None,
        mode: str = "formula",
        note: str | None = None,
        reason_code: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "calculated" if value is not None else "unavailable",
            "fair_value": format(value, "f") if value is not None else None,
            "calculation_mode": mode,
            "note": note,
            "reason_code": reason_code if value is None else None,
            "included_in_weighting": value is not None,
            "weighting_exclusion_reason": reason_code if value is None else None,
        }

    out: dict[str, Any] = {}
    for basis in ("CURRENT_FY", "NEXT_FY"):
        row = annual.get(basis) or {}
        current_fiscal_year = snapshot.get("current_fiscal_year")
        fiscal_year = row.get("fiscal_year")
        if fiscal_year is None and current_fiscal_year is not None:
            fiscal_year = int(current_fiscal_year) + (1 if basis == "NEXT_FY" else 0)
        eps = num(row.get("eps"))
        revenue = num(row.get("revenue"))
        # PEG requires growth that starts at the EPS horizon being valued.
        # `reported_growth` describes how that EPS was reached and must never be
        # reused to project/value the same EPS a second time.
        eps_growth = num(row.get("peg_growth"))
        growth_pct = eps_growth * Decimal("100") if eps_growth is not None and eps_growth > 0 else None

        pe_value = eps * current_pe if eps is not None and eps > 0 else None
        ps_value = revenue / shares * current_ps if revenue is not None and revenue > 0 and shares is not None and shares > 0 else None
        peg_value = eps * growth_pct * target_peg if eps is not None and eps > 0 and growth_pct is not None else None
        pb_value = bvps * current_pb if bvps is not None and bvps > 0 else None

        ev_multiple = current_ev_multiple
        if ev_multiple is None or ev_multiple <= 0:
            ev_multiple = Decimal("45") if eps_growth is not None and eps_growth > Decimal("0.50") else Decimal("35")
        ev_value = ((ebitda * ev_multiple) - debt + cash) / shares if ebitda is not None and ebitda > 0 and shares is not None and shares > 0 else None

        milestone_value = price * (Decimal("3") * success_probability + Decimal("0.5") * (Decimal("1") - success_probability)) if price is not None else pe_value
        dcf_out = dcf_value

        models = {
            "dcf": model(dcf_out, reason_code="DCF_INPUTS_UNAVAILABLE"),
            "forward_pe": model(pe_value, reason_code="HORIZON_EPS_UNAVAILABLE"),
            "peg": model(peg_value, note="growth sets implied P/E; EPS is not grown a second time", reason_code="HORIZON_EPS_OR_MATCHED_GROWTH_UNAVAILABLE"),
            "forward_ps": model(ps_value, reason_code="HORIZON_REVENUE_OR_SHARES_UNAVAILABLE"),
            "ev_ebitda": model(ev_value, reason_code="EBITDA_OR_SHARES_UNAVAILABLE"),
            "forward_pb": model(pb_value, reason_code="BOOK_VALUE_PER_SHARE_UNAVAILABLE"),
            "milestone": model(milestone_value),
        }
        models["forward_pe"]["inputs"] = {
            "fiscal_year": fiscal_year,
            "eps": format(eps, "f") if eps is not None else None,
            "observed_trailing_pe": format(current_pe, "f"),
            "observed_price": format(price, "f") if price is not None else None,
            "trailing_eps": (
                format(trailing_eps, "f")
                if trailing_eps is not None
                else None
            ),
            "multiple_source": "observed_price_divided_by_trailing_eps",
            "eps_source": f"annual_estimates.{basis}.eps",
        }
        out[basis] = {
            "estimate_basis": basis,
            "fiscal_year": fiscal_year,
            "eps": format(eps, "f") if eps is not None else None,
            "revenue": format(revenue, "f") if revenue is not None else None,
            "eps_growth": format(eps_growth, "f") if eps_growth is not None else None,
            "growth_basis": row.get("growth_basis"),
            "growth_is_horizon_matched": bool(row.get("growth_basis")),
            "model_count": sum(m.get("status") == "calculated" for m in models.values()),
            "models": models,
        }
    return out

def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None












def _quarterly_history(
    rows: list[Mapping[str, Any]],
    limit: int = 8,
) -> dict[str, Any]:
    by_period: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        fiscal_period = str(row.get("fiscal_period") or "").upper()
        if fiscal_period not in {"Q1", "Q2", "Q3", "Q4"}:
            continue
        period_end = str(row.get("period_end") or "")
        fiscal_year = int(period_end[:4] or 0)
        metric = str(row.get("metric") or "")
        if not fiscal_year or not period_end or not metric:
            continue
        period = by_period.setdefault(
            (fiscal_period, period_end),
            {
                "fiscal_year": fiscal_year,
                "fiscal_period": fiscal_period,
                "period_end": period_end,
                "filed_at": row.get("filed_at"),
                "form_type": row.get("form_type"),
                "accession_number": row.get("accession_number"),
                "metrics": {},
            },
        )
        period["metrics"][metric] = _metric(
            row,
            source_id_field="financial_fact_id",
        )
    periods = sorted(
        by_period.values(),
        key=lambda row: str(row["period_end"]),
    )[-limit:]
    return {
        "status": "ready" if periods else "unavailable",
        "quarter_count": len(periods),
        "requested_quarter_count": limit,
        "periods": periods,
        "reason_code": (
            None if periods else "QUARTERLY_FINANCIAL_HISTORY_NOT_POPULATED"
        ),
    }



def _compat_aggregate_from_unified(
    unified: Mapping[str, Any],
) -> dict[str, Any]:
    headline = unified.get("headline") or {}
    aggregation = unified.get("aggregation") or {}
    models = unified.get("models") or {}

    dominant_family = headline.get("dominant_family")
    included_models = list(aggregation.get("included_models") or [])
    included_families = []
    for name in included_models:
        family = (models.get(name) or {}).get("family")
        if family and family not in included_families:
            included_families.append(family)

    model_diagnostics = {}
    for name, row in models.items():
        if not isinstance(row, Mapping):
            continue
        model_diagnostics[name] = {
            "family": row.get("family"),
            "input_freshness_score": row.get("data_quality_score"),
            "assumption_quality_score": row.get("assumption_quality_score"),
            "aggregation_role": row.get("assumption_role"),
            "included_in_independent_aggregation": row.get(
                "included_in_independent_aggregation"
            ),
            "effective_weight": row.get("effective_weight"),
        }
        if row.get("assumption_role") == "market_anchored":
            model_diagnostics[name]["exclusion_reason_code"] = (
                "MARKET_ANCHORED_NOT_INDEPENDENT"
            )

    base = headline.get("base_fair_value")
    return {
        "fair_value": base,
        "reason_code": None if base is not None else "NO_CALCULATED_MODELS",
        "aggregation": {
            "method": "unified-dynamic-weight.v1",
            "primary_family": dominant_family,
            "cross_check_families": [
                family
                for family in included_families
                if family != dominant_family
            ],
            "weighted_cross_check_center": base,
            "archetype": aggregation.get("financial_archetype"),
            "financial_archetype": aggregation.get("financial_archetype"),
            "business_archetype": None,
            "routing_source": "unified_valuation",
            "routing_reason_code": None,
            "archetype_reason_codes": list(
                aggregation.get("reason_codes") or []
            ),
            "family_count": len(included_families),
            "confidence": headline.get("confidence"),
            "disagreement_ratio": None,
            "range_low": headline.get("bear_fair_value"),
            "range_high": headline.get("bull_fair_value"),
            "families": {},
        },
        "model_diagnostics": model_diagnostics,
        "business_routing": {
            "status": "not_applied",
            "archetype": None,
            "reason_code": "UNIFIED_VALUATION_OWNS_MODEL_SELECTION",
        },
    }

def build_full_market_coverage(
    root: Path,
    *,
    companies_path: str = "data/universe/companies.json",
    securities_path: str = "data/universe/securities.json",
    financial_path: str = "data/generated/canonical_financial_population/financial_facts.json",
    quarterly_financial_path: str = "data/generated/canonical_financial_population/quarterly_index.json",
    market_path: str = "data/generated/market/previous_close_cache.json",
    estimate_path: str = "data/estimate_data/consensus_estimates.json",
    explicit_estimate_path: str = "data/valuation/estimates.json",
    security_identity_path: str = "data/generated/security_identity/security_identity_normalization.json",
    company_snapshot_path: str = "data/generated/company/yahoo_company_snapshot.json",
    valuation_routing_path: str = "data/valuation/company_routing.json",
    valuation_assumptions_path: str = "data/knowledge/valuation_assumptions.json",
    dcf_policy_path: str = "config/valuation_dcf_policy.v1.json",
) -> dict[str, Any]:
    companies = _load(root / companies_path)
    securities = _load(root / securities_path)
    financials = _load(root / financial_path, default=[])
    quarterly_payload = _load(root / quarterly_financial_path, default={})
    market_payload = _load(root / market_path, default={"symbols": {}})
    estimates = _load(root / estimate_path, default=[])
    explicit_estimates = _load(root / explicit_estimate_path, default=[])
    identity = _load(
        root / security_identity_path,
        default={"companies": [], "securities": []},
    )
    company_snapshot = _load(root / company_snapshot_path, default={"symbols": {}})
    routing_payload = _load(root / valuation_routing_path, default={"companies": {}})
    assumption_rows = _load(root / valuation_assumptions_path, default=[])
    dcf_policy = _load(root / dcf_policy_path)

    if not all(
        isinstance(rows, list)
        for rows in (
            companies,
            securities,
            financials,
            estimates,
            explicit_estimates,
            assumption_rows,
        )
    ):
        raise FullMarketCoverageError(
            "population and canonical layers must contain arrays"
        )

    scoped_company_ids = {
        str(row.get("company_id"))
        for row in identity.get("companies", [])
        if row.get("valuation_scope_status") == "included"
    }
    eligible_security_ids = {
        str(row.get("security_id"))
        for row in identity.get("securities", [])
        if row.get("valuation_eligible") is True
    }
    if not scoped_company_ids:
        scoped_company_ids = {
            str(row.get("company_id"))
            for row in companies
        }
    if not eligible_security_ids:
        eligible_security_ids = {
            str(row.get("security_id"))
            for row in securities
        }

    securities_by_company: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in securities:
        if (
            row.get("status") in (None, "active")
            and str(row.get("security_id")) in eligible_security_ids
        ):
            securities_by_company[str(row.get("company_id") or "")].append(row)

    financial_by_company: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in financials:
        financial_by_company[str(row.get("company_id") or "")].append(row)

    quarterly_files = (
        quarterly_payload.get("company_id_to_file")
        if isinstance(quarterly_payload, Mapping)
        else {}
    )
    quarterly_files = (
        quarterly_files if isinstance(quarterly_files, Mapping) else {}
    )

    estimates_by_company: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in estimates:
        estimates_by_company[str(row.get("company_id") or "")].append(row)

    explicit_metric_map = {
        "diluted_eps": "forward_eps",
        "growth_estimate": "forward_eps_growth",
        "revenue": "forward_revenue",
    }
    explicit_estimates_by_symbol: dict[
        str,
        dict[str, Mapping[str, Any]],
    ] = defaultdict(dict)
    for row in explicit_estimates:
        if row.get("scenario") != "base":
            continue
        metric = explicit_metric_map.get(str(row.get("metric") or ""))
        symbol = str(row.get("company_id") or "").rsplit("-", 1)[-1].upper()
        if metric and symbol:
            explicit_estimates_by_symbol[symbol][metric] = row

    assumption_rows_by_company = {
        str(row.get("company_id")): row
        for row in assumption_rows
        if row.get("company_id") and row.get("evidence_ids")
    }
    market_symbols = (
        market_payload.get("symbols")
        if isinstance(market_payload, Mapping)
        else {}
    )
    market_symbols = market_symbols if isinstance(market_symbols, Mapping) else {}
    snapshot_symbols = (
        company_snapshot.get("symbols")
        if isinstance(company_snapshot, Mapping)
        else {}
    )
    snapshot_symbols = (
        snapshot_symbols if isinstance(snapshot_symbols, Mapping) else {}
    )

    routing_by_company = (
        routing_payload.get("companies")
        if isinstance(routing_payload, Mapping)
        else {}
    )
    routing_by_company = (
        routing_by_company if isinstance(routing_by_company, Mapping) else {}
    )
    ai_company_ids = {
        str(company_id)
        for company_id, row in routing_by_company.items()
        if isinstance(row, Mapping) and row.get("ai_research_company") is True
    }

    cards: list[dict[str, Any]] = []
    ticker_index: dict[str, int] = {}
    model_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    routing_counts: Counter[str] = Counter()
    routing_applied_count = 0

    for company in sorted(
        companies,
        key=lambda row: str(row.get("company_id") or ""),
    ):
        company_id = str(company.get("company_id") or "")
        if company_id not in scoped_company_ids:
            continue

        company_securities = securities_by_company.get(company_id, [])
        primary = next(
            (
                row
                for row in company_securities
                if row.get("security_id") == company.get("primary_security_id")
            ),
            None,
        )
        primary = primary or next(
            (
                row
                for row in company_securities
                if row.get("primary_listing") is True
            ),
            None,
        )
        primary = primary or (company_securities[0] if company_securities else {})
        ticker = str(primary.get("ticker") or "").upper()

        latest_fin = _latest(financial_by_company.get(company_id, []), "metric")
        newest_financial_date = max(
            (_date(row.get("period_end")) for row in latest_fin.values()),
            default=None,
        )
        if newest_financial_date:
            latest_fin = {
                name: row
                for name, row in latest_fin.items()
                if (observed := _date(row.get("period_end"))) is not None
                and (newest_financial_date - observed).days <= 550
            }

        fin = {
            name: _metric(
                latest_fin.get(name),
                source_id_field="financial_fact_id",
            )
            for name in (
                "revenue",
                "net_income",
                "operating_cash_flow",
                "capital_expenditures",
                "cash_and_cash_equivalents",
                "total_debt",
                "diluted_shares_outstanding",
                "ebitda",
                "book_value_per_share",
            )
        }

        snapshot_row = snapshot_symbols.get(ticker) if ticker else None
        snapshot_row = snapshot_row if isinstance(snapshot_row, Mapping) else {}
        snapshot_currency = (
            str(snapshot_row.get("currency") or primary.get("currency") or "")
            or None
        )
        fallback_fields = {
            "revenue": ("revenue_ttm", "currency"),
            "cash_and_cash_equivalents": ("total_cash", "currency"),
            "total_debt": ("total_debt", "currency"),
            "diluted_shares_outstanding": ("shares_outstanding", "shares"),
            "ebitda": ("ebitda_ttm", "currency"),
        }
        if company_id in ai_company_ids:
            for metric_name, (snapshot_field, unit_kind) in fallback_fields.items():
                if fin[metric_name]["status"] == "ready":
                    continue
                fin[metric_name] = _snapshot_metric(
                    snapshot_row,
                    snapshot_field,
                    ticker=ticker,
                    unit="shares" if unit_kind == "shares" else None,
                    currency=(
                        snapshot_currency if unit_kind == "currency" else None
                    ),
                )

        net_income = _number((latest_fin.get("net_income") or {}).get("value"))
        shares = _number(fin["diluted_shares_outstanding"].get("value"))
        eps_ids = (
            [str((latest_fin.get("net_income") or {}).get("financial_fact_id"))]
            if (latest_fin.get("net_income") or {}).get("financial_fact_id")
            else []
        )
        eps_ids.extend(
            str(value)
            for value in fin["diluted_shares_outstanding"].get(
                "source_record_ids",
                [],
            )
            if value not in eps_ids
        )
        fin["trailing_eps"] = _derived(
            net_income / shares
            if net_income is not None and shares and shares > 0
            else None,
            "trailing_eps.v031.0",
            eps_ids,
            "EPS_INPUTS_UNAVAILABLE",
        )

        ocf = latest_fin.get("operating_cash_flow") or {}
        capex = latest_fin.get("capital_expenditures") or {}
        same_period = bool(
            ocf
            and capex
            and ocf.get("fiscal_year") == capex.get("fiscal_year")
            and ocf.get("fiscal_period") == capex.get("fiscal_period")
        )
        ocf_value = _number(ocf.get("value"))
        capex_value = _number(capex.get("value"))
        fcf_ids = [
            str(row.get("financial_fact_id"))
            for row in (ocf, capex)
            if row.get("financial_fact_id")
        ]
        fin["free_cash_flow"] = _derived(
            ocf_value - abs(capex_value)
            if same_period
            and ocf_value is not None
            and capex_value is not None
            else None,
            "free_cash_flow.v031.0",
            fcf_ids,
            "FCF_PERIOD_MISMATCH"
            if ocf and capex
            else "FCF_INPUTS_UNAVAILABLE",
        )

        latest_est = _latest(estimates_by_company.get(company_id, []), "metric")
        # Manual/explicit estimates may override canonical provider estimates only
        # when the explicit row itself carries a verifiable forecast period.
        # Legacy seed rows with only fiscal_period="Forward" must not silently
        # replace refreshed canonical Yahoo estimates with known horizon metadata.
        for explicit_metric, explicit_row in explicit_estimates_by_symbol.get(ticker, {}).items():
            explicit_period = str(explicit_row.get("fiscal_period") or "").strip().upper()
            explicit_has_horizon = bool(
                explicit_row.get("forecast_basis")
                or explicit_row.get("horizon")
                or explicit_row.get("estimate_horizon")
                or explicit_row.get("fiscal_year")
                or explicit_row.get("period_end")
                or (
                    explicit_period
                    and explicit_period not in {"FORWARD", "FORWARD_UNSPECIFIED", "PROVIDER_FORWARD"}
                )
            )
            if explicit_has_horizon or explicit_metric not in latest_est:
                latest_est[explicit_metric] = explicit_row
        est = {
            name: _metric(
                latest_est.get(name),
                source_id_field="estimate_id",
            )
            for name in (
                "forward_eps",
                "forward_eps_growth",
                "forward_revenue",
                "forward_ebitda",
                "ebitda_ttm",
                "milestone_probability",
                "milestone_value",
            )
        }
        forward_revenue = _number(est["forward_revenue"].get("value"))
        trailing_revenue = _number(fin["revenue"].get("value"))
        if (
            company_id in ai_company_ids
            and (forward_revenue is None or forward_revenue <= 0)
            and trailing_revenue is not None
            and trailing_revenue > 0
        ):
            est["forward_revenue"] = {
                "status": "ready",
                "value": format(trailing_revenue, "f"),
                "unit": fin["revenue"].get("unit"),
                "currency": fin["revenue"].get("currency"),
                "as_of_date": fin["revenue"].get("as_of_date"),
                "reason_code": None,
                "source_record_ids": list(
                    fin["revenue"].get("source_record_ids", [])
                ),
                "provenance": (
                    "trailing_revenue_proxy_when_forward_consensus_unavailable"
                ),
                "is_proxy": True,
            }

        company_assumption_row = assumption_rows_by_company.get(company_id, {})
        company_assumptions = company_assumption_row.get("assumptions") or {}
        company_assumption_roles = (
            company_assumption_row.get("assumption_roles") or {}
        )

        routing_row = routing_by_company.get(company_id, {})
        routing = (
            (routing_row.get("valuation") or {})
            if isinstance(routing_row, Mapping)
            else {}
        )
        routing_archetype = str(routing.get("archetype") or "pending")
        routing_counts[routing_archetype] += 1

        market_row = market_symbols.get(ticker) if ticker else None
        market = {
            "status": (
                "ready"
                if isinstance(market_row, Mapping)
                and _number(market_row.get("close")) is not None
                else "unavailable"
            ),
            "current_price": (
                str(market_row.get("close"))
                if isinstance(market_row, Mapping)
                and market_row.get("close") is not None
                else None
            ),
            "currency": (
                market_row.get("currency")
                if isinstance(market_row, Mapping)
                else primary.get("currency")
            ),
            "as_of_date": (
                market_row.get("session_date")
                if isinstance(market_row, Mapping)
                else None
            ),
            "reason_code": (
                None
                if isinstance(market_row, Mapping)
                else "CANONICAL_MARKET_NOT_POPULATED"
            ),
        }

        unified = build_unified_valuation(
            symbol=ticker,
            financials=fin,
            estimates=est,
            assumptions=company_assumptions,
            assumption_roles=company_assumption_roles,
            dcf_policy=dcf_policy,
            reference_price={
                "value": market.get("current_price"),
                "currency": market.get("currency"),
                "as_of_date": market.get("as_of_date"),
                "source": "full_market_coverage.market",
            },
        )
        models = unified["models"]
        aggregate = _compat_aggregate_from_unified(unified)

        calculated_values = [
            Decimal(row["fair_value"])
            for row in models.values()
            if row["status"] == "calculated"
        ]
        calculated_count = len(calculated_values)
        model_counts.update(
            name
            for name, row in models.items()
            if row["status"] == "calculated"
        )
        status = (
            "ready"
            if calculated_count >= 2
            else "partial"
            if calculated_count == 1
            else "unavailable"
        )
        status_counts[status] += 1

        analyst_target = _snapshot_metric(
            snapshot_row,
            "analyst_target_mean",
            ticker=ticker,
            unit="currency_per_share",
            currency=snapshot_currency,
        )
        analyst_target.update(
            {
                "label": "analyst_consensus_target",
                "aggregation_role": "external_reference",
                "included_in_independent_aggregation": False,
            }
        )

        valuation_horizons = _dual_fy_seven_models(
            snapshot_row,
            fin,
            company_assumptions,
            market,
            dcf_policy,
        )

        # Production default: unchanged frontend consumes CURRENT_FY.
        annual_estimates = snapshot_row.get("annual_estimates") if isinstance(snapshot_row, Mapping) else {}
        annual_estimates = annual_estimates if isinstance(annual_estimates, Mapping) else {}
        current_fy = annual_estimates.get("CURRENT_FY") or {}
        next_fy = annual_estimates.get("NEXT_FY") or {}
        current_eps = current_fy.get("eps")
        current_revenue = current_fy.get("revenue")
        current_growth = next_fy.get("eps_growth") or current_fy.get("peg_growth") or current_fy.get("eps_growth")
        if current_eps not in (None, ""):
            est["forward_eps"] = {**(est.get("forward_eps") or {}), "status": "ready", "value": str(current_eps), "forecast_basis": "CURRENT_FY", "fiscal_period": "CURRENT_FY", "reason_code": None}
        if current_revenue not in (None, ""):
            est["forward_revenue"] = {**(est.get("forward_revenue") or {}), "status": "ready", "value": str(current_revenue), "forecast_basis": "CURRENT_FY", "fiscal_period": "CURRENT_FY", "reason_code": None}
        if current_growth not in (None, ""):
            est["forward_eps_growth"] = {**(est.get("forward_eps_growth") or {}), "status": "ready", "value": str(current_growth), "growth_from_period": "CURRENT_FY", "growth_to_period": "NEXT_FY", "growth_kind": "period_transition", "reason_code": None}

        card = {
            "schema_version": "full-market-valuation-card.v031.0",
            "company": {
                "company_id": company_id,
                "display_name": company.get("display_name"),
                "legal_name": company.get("legal_name"),
                "country": company.get("country"),
                "business_summary": None,
                "business_summary_reason_code": (
                    "CANONICAL_BUSINESS_SUMMARY_NOT_POPULATED"
                ),
            },
            "primary_security": {
                "security_id": primary.get("security_id"),
                "ticker": ticker or None,
                "exchange": primary.get("exchange"),
                "currency": primary.get("currency"),
            },
            "securities": [
                {
                    "security_id": row.get("security_id"),
                    "ticker": row.get("ticker"),
                    "exchange": row.get("exchange"),
                    "primary_listing": row.get("primary_listing"),
                }
                for row in company_securities
            ],
            "status": status,
            "market": market,
            "financials": fin,
            "financial_history": _quarterly_history(
                _load(
                    (root / quarterly_financial_path).parent
                    / str(quarterly_files[company_id]),
                    default=[],
                )
                if company_id in quarterly_files
                else []
            ),
            "estimates": est,
            "valuation_horizons": valuation_horizons,
            "valuation": {
                "status": status,
                "calculated_model_count": calculated_count,
                "total_model_count": 7,
                "fair_value": aggregate["fair_value"],
                "unified_contract": unified,
                "aggregation_version": "unified-dynamic-weight.v1",
                "routing_version": "unified-valuation-routing.v1",
                "routing": {
                    "status": routing.get("status") or "pending_primary_business",
                    "archetype": routing.get("archetype"),
                    "preferred_model_families": list(
                        routing.get("preferred_model_families") or []
                    ),
                    "deprioritized_model_families": list(
                        routing.get("deprioritized_model_families") or []
                    ),
                    "reason_code": routing.get("reason_code"),
                    "source": "company_overview.routing.valuation",
                    "aggregation_applied": False,
                },
                "reason_code": aggregate["reason_code"],
                "aggregation": aggregate["aggregation"],
                "reference_values": {
                    "analyst_consensus_target": analyst_target,
                },
                "model_diagnostics": aggregate["model_diagnostics"],
                "models": models,
            },
        }

        position = len(cards)
        cards.append(card)
        for row in company_securities:
            symbol = str(row.get("ticker") or "").upper()
            if symbol:
                ticker_index.setdefault(symbol, position)

    return {
        "schema_version": "full-market-coverage.v031.0",
        "version": "V031.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "company_count": len(cards),
            "registry_company_count": len(companies),
            "excluded_non_company_instrument_count": len(companies) - len(cards),
            "security_count": len(securities),
            "valuation_security_count": len(eligible_security_ids),
            "status_counts": {
                name: status_counts[name]
                for name in ("ready", "partial", "unavailable")
            },
            "model_calculated_counts": {
                name: model_counts[name]
                for name in MODELS
            },
            "market_ready_company_count": sum(
                card["market"]["status"] == "ready"
                for card in cards
            ),
            "financial_present_company_count": sum(
                bool(financial_by_company.get(card["company"]["company_id"]))
                for card in cards
            ),
            "estimate_present_company_count": sum(
                bool(estimates_by_company.get(card["company"]["company_id"]))
                for card in cards
            ),
            "primary_business_routing_applied_count": routing_applied_count,
            "primary_business_routing_pending_count": len(cards) - routing_applied_count,
            "valuation_routing_archetype_counts": dict(
                sorted(routing_counts.items())
            ),
        },
        "cards": cards,
        "indexes": {
            "ticker_to_position": ticker_index,
            "company_id_to_position": {
                card["company"]["company_id"]: index
                for index, card in enumerate(cards)
            },
        },
    }


def write_full_market_coverage(
    report: Mapping[str, Any],
    output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    company_root = output.parent / "per-company"
    company_root.mkdir(parents=True, exist_ok=True)
    ticker_to_file: dict[str, str] = {}
    company_id_to_file: dict[str, str] = {}
    current_files: set[str] = set()

    for card in report.get("cards") or []:
        company_id = str((card.get("company") or {}).get("company_id") or "")
        if not company_id:
            continue
        filename = quote(company_id, safe="._-") + ".json"
        current_files.add(filename)
        path = company_root / filename
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(card, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        company_id_to_file[company_id] = f"per-company/{filename}"
        for security in card.get("securities") or []:
            ticker = str(security.get("ticker") or "").upper()
            if ticker:
                ticker_to_file[ticker] = f"per-company/{filename}"

    for stale in company_root.glob("*.json"):
        if stale.name not in current_files:
            stale.unlink()

    index = {
        "schema_version": "full-market-valuation-index.v031g.1",
        "version": "V031G.1",
        "generated_at": report.get("generated_at"),
        "summary": dict(report.get("summary") or {}),
        "indexes": {
            "ticker_to_file": dict(sorted(ticker_to_file.items())),
            "company_id_to_file": dict(sorted(company_id_to_file.items())),
        },
    }
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)


class FullMarketCoverageService:
    def __init__(
        self,
        *,
        root: Path | None = None,
        snapshot_path: Path | None = None,
        coverage_service: CoveragePolicyService | None = None,
        publication_root: Path | None = None,
    ) -> None:
        self.root = root or Path.cwd()
        self.snapshot_path = (
            snapshot_path
            or self.root
            / "data/generated/full_market_coverage/full_market_coverage.json"
        )
        self.coverage_service = (
            coverage_service or CoveragePolicyService(root=self.root)
        )
        self.publication_root = (
            publication_root or self.root / "data/generated/publication_gate"
        )
        self._payload: Mapping[str, Any] | None = None
        self._catalog: Mapping[str, Any] | None = None

    def _get_payload(self) -> Mapping[str, Any]:
        if self._payload is None:
            self._payload = (
                _load(self.snapshot_path)
                if self.snapshot_path.is_file()
                else build_full_market_coverage(self.root)
            )
        return self._payload

    def list(self) -> dict[str, Any]:
        catalog_path = self.publication_root / "company_catalog.json"
        if catalog_path.is_file():
            if self._catalog is None:
                self._catalog = _load(catalog_path)
            if (
                self._catalog.get("schema_version")
                == "publication-gate-catalog.v031f.2.1"
            ):
                companies = [
                    {
                        "company_id": row["company_id"],
                        "ticker": row["ticker"],
                        "display_name": row.get("display_name"),
                        "status": row.get("valuation_status"),
                    }
                    for row in self._catalog.get("companies") or []
                ]
                return {
                    "schema_version": "published-company-list.v031f.2.1",
                    "version": "V031F.2.1",
                    "summary": {
                        "company_count": len(companies),
                        "publication_gate": "coverage-policy.v031f.2.1",
                        "source": "compact_publication_catalog",
                    },
                    "companies": companies,
                }

        payload = self._get_payload()
        public_ids = self.coverage_service.public_company_ids()
        companies = [
            {
                "company_id": card["company"]["company_id"],
                "ticker": card["primary_security"]["ticker"],
                "display_name": card["company"]["display_name"],
                "status": card["status"],
            }
            for card in payload["cards"]
            if card["company"]["company_id"] in public_ids
        ]
        summary = {
            "company_count": len(companies),
            "source_company_count": payload["summary"].get("company_count"),
            "registry_company_count": payload["summary"].get(
                "registry_company_count"
            ),
            "publication_gate": "coverage-policy.v031f.1",
        }
        return {
            "schema_version": "published-company-list.v031f.2",
            "version": "V031F.2",
            "summary": summary,
            "companies": companies,
        }

    def get(self, ticker: str) -> Mapping[str, Any]:
        symbol = str(ticker or "").strip().upper()
        coverage = self.coverage_service.require_public(
            symbol,
            capability="valuation_card",
        )
        catalog_path = self.publication_root / "company_catalog.json"
        if catalog_path.is_file():
            if self._catalog is None:
                self._catalog = _load(catalog_path)
            filename = (
                (self._catalog.get("indexes") or {})
                .get("ticker_to_file", {})
                .get(symbol)
            )
            if filename:
                loose_projection = self.publication_root / "companies" / filename
                if loose_projection.is_file():
                    projection = _load(loose_projection)
                else:
                    archive = self.publication_root / "company_projections.zip"
                    try:
                        with ZipFile(archive) as bundle:
                            projection = json.loads(bundle.read(filename))
                    except (
                        OSError,
                        KeyError,
                        BadZipFile,
                        json.JSONDecodeError,
                    ) as exc:
                        raise FullMarketCoverageError(
                            f"cannot read company projection for {symbol}: {exc}"
                        ) from exc
                card = projection.get("valuation_card")
                if isinstance(card, Mapping):
                    return {
                        **card,
                        "coverage_policy": {
                            "product_scope": projection.get("product_scope"),
                            "research_scope": projection.get("research_scope"),
                            "scope_axes": projection.get("scope_axes") or {},
                            "reason_codes": (
                                (projection.get("coverage_policy") or {}).get(
                                    "reason_codes"
                                )
                                or []
                            ),
                        },
                    }

        payload = self._get_payload()
        filename = (
            payload.get("indexes", {})
            .get("ticker_to_file", {})
            .get(symbol)
        )
        if filename:
            card_path = self.snapshot_path.parent / str(filename)
            if not card_path.is_file():
                raise FullMarketCoverageNotFound(
                    f"valuation artifact missing for ticker {symbol}: {card_path}"
                )
            card = _load(card_path)
            return {
                **card,
                "coverage_policy": {
                    "publication_tier": coverage.get("publication_tier"),
                    "reason_codes": coverage.get("reason_codes") or [],
                },
            }

        position = (
            payload.get("indexes", {})
            .get("ticker_to_position", {})
            .get(symbol)
        )
        if position is None:
            raise FullMarketCoverageNotFound(
                f"ticker not found in full-market population: {symbol}"
            )
        return {
            **payload["cards"][position],
            "coverage_policy": {
                "publication_tier": coverage.get("publication_tier"),
                "reason_codes": coverage.get("reason_codes") or [],
            },
        }
