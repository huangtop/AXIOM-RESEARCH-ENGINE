from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote
from zipfile import BadZipFile, ZipFile

from axiom_engine.seven_model_valuation import calculate_seven_models
from axiom_engine.coverage_policy import CoveragePolicyService


MODELS = ("dcf", "forward_pe", "peg", "forward_ps", "ev_ebitda", "forward_pb", "milestone")
MODEL_FAMILIES = {
    "dcf": "intrinsic_cash_flow",
    "forward_pe": "forward_earnings",
    "peg": "forward_earnings",
    "forward_ps": "forward_revenue",
    "ev_ebitda": "enterprise_operations",
    "forward_pb": "balance_sheet",
    "milestone": "event_probability",
}
DEFAULT_FAMILY_WEIGHTS = {
    "intrinsic_cash_flow": Decimal("0"),
    "forward_earnings": Decimal("1.00"),
    "forward_revenue": Decimal("0.75"),
    "enterprise_operations": Decimal("0.90"),
    "balance_sheet": Decimal("0.45"),
    "event_probability": Decimal("1.00"),
}


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


def _latest(rows: list[Mapping[str, Any]], metric_field: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        metric = str(row.get(metric_field) or "").strip().lower()
        if not metric:
            continue
        current = result.get(metric)
        key = str(row.get("period_end") or row.get("as_of_date") or row.get("observed_at") or "")
        old = str((current or {}).get("period_end") or (current or {}).get("as_of_date") or (current or {}).get("observed_at") or "")
        if key >= old:
            result[metric] = row
    return result


def _metric(row: Mapping[str, Any] | None, *, source_id_field: str) -> dict[str, Any]:
    if not row:
        return {"status": "unavailable", "value": None, "reason_code": "canonical_metric_not_populated", "source_record_ids": []}
    return {
        "status": "ready",
        "value": str(row.get("value")),
        "unit": row.get("unit"),
        "currency": row.get("currency"),
        "as_of_date": row.get("period_end") or row.get("as_of_date"),
        "reason_code": None,
        "source_record_ids": [row.get(source_id_field)] if row.get(source_id_field) else [],
    }


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
        return {"status": "unavailable", "value": None, "reason_code": "provider_metric_not_populated", "source_record_ids": []}
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


def _derived(value: Decimal | None, formula: str, source_ids: list[str], reason: str) -> dict[str, Any]:
    return {
        "status": "ready" if value is not None else "unavailable",
        "value": format(value, "f") if value is not None else None,
        "reason_code": None if value is not None else reason,
        "formula_version": formula,
        "source_record_ids": source_ids,
    }


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _weighted_quantile(rows: list[tuple[Decimal, Decimal]], quantile: Decimal) -> Decimal:
    ordered = sorted(rows, key=lambda row: row[0])
    total = sum((weight for _, weight in ordered), Decimal("0"))
    threshold = total * quantile
    cumulative = Decimal("0")
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return ordered[-1][0]


def _valuation_archetype(
    financials: Mapping[str, Mapping[str, Any]],
    estimates: Mapping[str, Mapping[str, Any]],
) -> tuple[str, dict[str, Decimal], list[str]]:
    def value(layer: Mapping[str, Mapping[str, Any]], name: str) -> Decimal | None:
        payload = layer.get(name) or {}
        return _number(payload.get("value"))

    revenue = value(financials, "revenue")
    net_income = value(financials, "net_income")
    free_cash_flow = value(financials, "free_cash_flow")
    forward_eps = value(estimates, "forward_eps")
    forward_growth = value(estimates, "forward_eps_growth")
    net_margin = net_income / revenue if revenue and net_income is not None else None
    profitable_growth = bool(
        net_margin is not None
        and net_margin >= Decimal("0.10")
        and free_cash_flow is not None
        and free_cash_flow > 0
        and forward_eps is not None
        and forward_eps > 0
        and forward_growth is not None
        and forward_growth > 0
    )
    if profitable_growth:
        weights = {
            "intrinsic_cash_flow": Decimal("0"),
            "forward_earnings": Decimal("1.40"),
            "forward_revenue": Decimal("0.65"),
            "enterprise_operations": Decimal("0.85"),
            "balance_sheet": Decimal("0.20"),
            "event_probability": Decimal("0.25"),
        }
        reasons = ["POSITIVE_FORWARD_EARNINGS", "NET_MARGIN_AT_LEAST_10_PERCENT", "POSITIVE_FREE_CASH_FLOW"]
        reasons.append("DCF_EXCLUDED_FROM_AGGREGATION_BY_PRODUCT_POLICY")
        return "profitable_growth", weights, reasons
    if net_income is not None and net_income <= 0:
        weights = dict(DEFAULT_FAMILY_WEIGHTS)
        weights.update({"forward_earnings": Decimal("0.20"), "forward_revenue": Decimal("1.20"), "balance_sheet": Decimal("0.35"), "event_probability": Decimal("0.90")})
        return "loss_making_or_pre_profit", weights, ["NON_POSITIVE_NET_INCOME"]
    return "general_operating_company", dict(DEFAULT_FAMILY_WEIGHTS), ["DEFAULT_OPERATING_COMPANY_PROFILE"]


def _aggregate_models(
    models: Mapping[str, Mapping[str, Any]],
    financials: Mapping[str, Mapping[str, Any]],
    estimates: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate independent model families without using the market price.

    Correlated models first share one family vote.  The family vote is then
    adjusted for source freshness and generic-assumption risk before a lightly
    winsorized weighted center is calculated.
    """
    dated_inputs: dict[str, date] = {}
    for layer in (financials, estimates):
        for name, payload in layer.items():
            if isinstance(payload, Mapping):
                observed = _date(payload.get("as_of_date"))
                if observed:
                    dated_inputs[name] = observed
    reference_date = max(dated_inputs.values(), default=None)
    archetype, family_weights, archetype_reasons = _valuation_archetype(financials, estimates)
    family_models: dict[str, list[tuple[str, Decimal, Decimal]]] = defaultdict(list)
    model_diagnostics: dict[str, dict[str, Any]] = {}
    for name, model in models.items():
        if model.get("status") != "calculated":
            continue
        value = _number(model.get("fair_value"))
        if value is None or value <= 0:
            continue
        family = MODEL_FAMILIES[name]
        input_dates = [dated_inputs[input_name] for input_name in model.get("input_names") or [] if input_name in dated_inputs]
        freshness = Decimal("1")
        newest_input = max(input_dates, default=None)
        if reference_date and newest_input:
            age = (reference_date - newest_input).days
            freshness = Decimal("0.45") if age > 550 else Decimal("0.65") if age > 370 else Decimal("0.80") if age > 185 else Decimal("1")
        elif reference_date:
            freshness = Decimal("0.70")
        assumption_quality = Decimal("0.70") if str(model.get("assumption_source") or "").startswith("config/") else Decimal("1")
        quality = freshness * assumption_quality
        family_models[family].append((name, value, quality))
        model_diagnostics[name] = {
            "family": family,
            "input_freshness_score": format(freshness, "f"),
            "assumption_quality_score": format(assumption_quality, "f"),
            "newest_dated_input": newest_input.isoformat() if newest_input else None,
        }

    families: dict[str, dict[str, Any]] = {}
    weighted_families: list[tuple[Decimal, Decimal]] = []
    for family, members in sorted(family_models.items()):
        family_base = family_weights[family]
        quality_total = sum((quality for _, _, quality in members), Decimal("0"))
        representative = sum((value * quality for _, value, quality in members), Decimal("0")) / quality_total
        family_quality = quality_total / Decimal(len(members))
        weight = family_base * family_quality
        if weight > 0:
            weighted_families.append((representative, weight))
        families[family] = {
            "model_names": [name for name, _, _ in members],
            "representative_fair_value": format(representative, "f"),
            "weight": format(weight, "f"),
            "included_in_aggregation": weight > 0,
            "exclusion_reason_code": None if weight > 0 else "ARCHETYPE_MODEL_FAMILY_EXCLUDED",
        }
        for name, _, quality in members:
            model_diagnostics[name]["effective_weight"] = format(weight * quality / quality_total, "f")

    if not weighted_families:
        return {
            "fair_value": None,
            "reason_code": "NO_CALCULATED_MODELS",
            "aggregation": None,
            "model_diagnostics": model_diagnostics,
        }

    raw_values = [value for value, _ in weighted_families]
    median = _weighted_quantile(weighted_families, Decimal("0.50"))
    lower_cap, upper_cap = median * Decimal("0.50"), median * Decimal("2.00")
    winsorized = [(max(lower_cap, min(value, upper_cap)), weight) for value, weight in weighted_families]
    total_weight = sum((weight for _, weight in winsorized), Decimal("0"))
    weighted_center = sum((value * weight for value, weight in winsorized), Decimal("0")) / total_weight
    primary_family = "forward_earnings" if archetype == "profitable_growth" and "forward_earnings" in families else None
    center = _number(families[primary_family]["representative_fair_value"]) if primary_family else weighted_center
    center = center if center is not None else weighted_center
    minimum, maximum = min(raw_values), max(raw_values)
    disagreement_ratio = maximum / minimum if minimum > 0 else Decimal("999")
    independent_family_count = sum(
        bool(row["included_in_aggregation"]) for row in families.values()
    )
    confidence = (
        "high"
        if independent_family_count >= 3 and disagreement_ratio <= Decimal("1.35")
        else "medium"
        if independent_family_count >= 2 and disagreement_ratio <= Decimal("2.00")
        else "low"
    )
    return {
        "fair_value": format(center, "f"),
        "reason_code": None,
        "aggregation": {
            "method": "archetype-primary-family" if primary_family else "confidence-weighted-family-winsorized-center",
            "primary_family": primary_family,
            "cross_check_families": [family for family in families if family != primary_family and families[family]["included_in_aggregation"]],
            "weighted_cross_check_center": format(weighted_center, "f"),
            "archetype": archetype,
            "archetype_reason_codes": archetype_reasons,
            "family_count": independent_family_count,
            "confidence": confidence,
            "disagreement_ratio": format(disagreement_ratio, ".4f"),
            "range_low": format(_weighted_quantile(weighted_families, Decimal("0.20")), "f"),
            "range_high": format(_weighted_quantile(weighted_families, Decimal("0.80")), "f"),
            "families": families,
        },
        "model_diagnostics": model_diagnostics,
    }


def _apply_market_sanity_gate(aggregate: dict[str, Any], current_price: Decimal | None) -> None:
    fair_value = _number(aggregate.get("fair_value"))
    if fair_value is None or current_price is None or current_price <= 0:
        return
    ratio = fair_value / current_price
    if Decimal("0.10") <= ratio <= Decimal("10"):
        return
    aggregation = aggregate.get("aggregation")
    if isinstance(aggregation, dict):
        aggregation["publication_gate"] = {
            "status": "blocked",
            "reason_code": "FAIR_VALUE_TO_MARKET_PRICE_EXTREME_OUTLIER",
            "fair_value_to_market_ratio": format(ratio, ".4f"),
            "permitted_ratio_low": "0.10",
            "permitted_ratio_high": "10.00",
        }
    aggregate["fair_value"] = None
    aggregate["reason_code"] = "FAIR_VALUE_TO_MARKET_PRICE_EXTREME_OUTLIER"


def _quarterly_history(rows: list[Mapping[str, Any]], limit: int = 8) -> dict[str, Any]:
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
        period["metrics"][metric] = _metric(row, source_id_field="financial_fact_id")
    periods = sorted(by_period.values(), key=lambda row: str(row["period_end"]))[-limit:]
    return {
        "status": "ready" if periods else "unavailable",
        "quarter_count": len(periods),
        "requested_quarter_count": limit,
        "periods": periods,
        "reason_code": None if periods else "QUARTERLY_FINANCIAL_HISTORY_NOT_POPULATED",
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
    company_overview_path: str = "data/generated/company_overview/index.json",
    valuation_assumptions_path: str = "data/knowledge/valuation_assumptions.json",
    dcf_policy_path: str = "config/fair_value_snapshot.v030.14.0.json",
) -> dict[str, Any]:
    companies = _load(root / companies_path)
    securities = _load(root / securities_path)
    financials = _load(root / financial_path, default=[])
    quarterly_payload = _load(root / quarterly_financial_path, default={})
    market_payload = _load(root / market_path, default={"symbols": {}})
    estimates = _load(root / estimate_path, default=[])
    explicit_estimates = _load(root / explicit_estimate_path, default=[])
    identity = _load(root / security_identity_path, default={"companies": [], "securities": []})
    company_snapshot = _load(root / company_snapshot_path, default={"symbols": {}})
    overview_index = _load(root / company_overview_path, default={"ticker_to_file": {}})
    assumption_rows = _load(root / valuation_assumptions_path, default=[])
    dcf_policy_payload = _load(root / dcf_policy_path)
    dcf_policy = dcf_policy_payload.get("dcf", {})
    if not all(isinstance(rows, list) for rows in (companies, securities, financials, estimates, explicit_estimates, assumption_rows)):
        raise FullMarketCoverageError("population and canonical layers must contain arrays")

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
        scoped_company_ids = {str(row.get("company_id")) for row in companies}
    if not eligible_security_ids:
        eligible_security_ids = {str(row.get("security_id")) for row in securities}
    securities_by_company: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in securities:
        if row.get("status") in (None, "active") and str(row.get("security_id")) in eligible_security_ids:
            securities_by_company[str(row.get("company_id") or "")].append(row)
    financial_by_company: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in financials:
        financial_by_company[str(row.get("company_id") or "")].append(row)
    quarterly_files = quarterly_payload.get("company_id_to_file") if isinstance(quarterly_payload, Mapping) else {}
    quarterly_files = quarterly_files if isinstance(quarterly_files, Mapping) else {}
    estimates_by_company: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in estimates:
        estimates_by_company[str(row.get("company_id") or "")].append(row)
    explicit_metric_map = {
        "diluted_eps": "forward_eps",
        "growth_estimate": "forward_eps_growth",
        "revenue": "forward_revenue",
    }
    explicit_estimates_by_symbol: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in explicit_estimates:
        if row.get("scenario") != "base":
            continue
        metric = explicit_metric_map.get(str(row.get("metric") or ""))
        symbol = str(row.get("company_id") or "").rsplit("-", 1)[-1].upper()
        if metric and symbol:
            explicit_estimates_by_symbol[symbol][metric] = row
    assumptions_by_company = {
        str(row.get("company_id")): row.get("assumptions") or {}
        for row in assumption_rows
        if row.get("company_id") and row.get("evidence_ids")
    }
    market_symbols = market_payload.get("symbols") if isinstance(market_payload, Mapping) else {}
    market_symbols = market_symbols if isinstance(market_symbols, Mapping) else {}
    snapshot_symbols = company_snapshot.get("symbols") if isinstance(company_snapshot, Mapping) else {}
    snapshot_symbols = snapshot_symbols if isinstance(snapshot_symbols, Mapping) else {}
    ai_company_ids: set[str] = set()
    overview_files = overview_index.get("ticker_to_file") if isinstance(overview_index, Mapping) else {}
    for overview_file in set(overview_files.values()) if isinstance(overview_files, Mapping) else set():
        overview = _load((root / company_overview_path).parent / "per-company" / str(overview_file), default={})
        theme_id = (((overview.get("path") or {}).get("theme") or {}).get("id")) if isinstance(overview, Mapping) else None
        if theme_id in {"theme:artificial_intelligence", "theme:ai_infrastructure"}:
            ai_company_ids.add(str(overview.get("company_id") or ""))

    cards: list[dict[str, Any]] = []
    ticker_index: dict[str, int] = {}
    model_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    for company in sorted(companies, key=lambda row: str(row.get("company_id") or "")):
        company_id = str(company.get("company_id") or "")
        if company_id not in scoped_company_ids:
            continue
        company_securities = securities_by_company.get(company_id, [])
        primary = next((row for row in company_securities if row.get("security_id") == company.get("primary_security_id")), None)
        primary = primary or next((row for row in company_securities if row.get("primary_listing") is True), None)
        primary = primary or (company_securities[0] if company_securities else {})
        ticker = str(primary.get("ticker") or "").upper()

        latest_fin = _latest(financial_by_company.get(company_id, []), "metric")
        fin = {name: _metric(latest_fin.get(name), source_id_field="financial_fact_id") for name in (
            "revenue", "net_income", "operating_cash_flow", "capital_expenditures", "cash_and_cash_equivalents", "total_debt", "diluted_shares_outstanding", "ebitda", "book_value_per_share",
        )}
        snapshot_row = snapshot_symbols.get(ticker) if ticker and company_id in ai_company_ids else None
        snapshot_row = snapshot_row if isinstance(snapshot_row, Mapping) else {}
        snapshot_currency = str(snapshot_row.get("currency") or primary.get("currency") or "") or None
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
                    currency=snapshot_currency if unit_kind == "currency" else None,
                )
        net_income = _number((latest_fin.get("net_income") or {}).get("value"))
        shares = _number(fin["diluted_shares_outstanding"].get("value"))
        eps_ids = [str((latest_fin.get("net_income") or {}).get("financial_fact_id"))] if (latest_fin.get("net_income") or {}).get("financial_fact_id") else []
        eps_ids.extend(str(value) for value in fin["diluted_shares_outstanding"].get("source_record_ids", []) if value not in eps_ids)
        fin["trailing_eps"] = _derived(net_income / shares if net_income is not None and shares and shares > 0 else None, "trailing_eps.v031.0", eps_ids, "EPS_INPUTS_UNAVAILABLE")
        ocf = latest_fin.get("operating_cash_flow") or {}
        capex = latest_fin.get("capital_expenditures") or {}
        same_period = bool(ocf and capex and ocf.get("fiscal_year") == capex.get("fiscal_year") and ocf.get("fiscal_period") == capex.get("fiscal_period"))
        ocf_value, capex_value = _number(ocf.get("value")), _number(capex.get("value"))
        fcf_ids = [str(row.get("financial_fact_id")) for row in (ocf, capex) if row.get("financial_fact_id")]
        fin["free_cash_flow"] = _derived(ocf_value - abs(capex_value) if same_period and ocf_value is not None and capex_value is not None else None, "free_cash_flow.v031.0", fcf_ids, "FCF_PERIOD_MISMATCH" if ocf and capex else "FCF_INPUTS_UNAVAILABLE")

        latest_est = _latest(estimates_by_company.get(company_id, []), "metric")
        latest_est.update(explicit_estimates_by_symbol.get(ticker, {}))
        est = {name: _metric(latest_est.get(name), source_id_field="estimate_id") for name in (
            "forward_eps", "forward_eps_growth", "forward_revenue", "forward_ebitda", "ebitda_ttm", "milestone_probability", "milestone_value",
        )}
        forward_revenue = _number(est["forward_revenue"].get("value"))
        trailing_revenue = _number(fin["revenue"].get("value"))
        if company_id in ai_company_ids and (forward_revenue is None or forward_revenue <= 0) and trailing_revenue is not None and trailing_revenue > 0:
            est["forward_revenue"] = {
                "status": "ready",
                "value": format(trailing_revenue, "f"),
                "unit": fin["revenue"].get("unit"),
                "currency": fin["revenue"].get("currency"),
                "as_of_date": fin["revenue"].get("as_of_date"),
                "reason_code": None,
                "source_record_ids": list(fin["revenue"].get("source_record_ids", [])),
                "provenance": "trailing_revenue_proxy_when_forward_consensus_unavailable",
                "is_proxy": True,
            }
        company_assumptions = assumptions_by_company.get(company_id, {})
        market_row = market_symbols.get(ticker) if ticker else None
        market = {
            "status": "ready" if isinstance(market_row, Mapping) and _number(market_row.get("close")) is not None else "unavailable",
            "current_price": str(market_row.get("close")) if isinstance(market_row, Mapping) and market_row.get("close") is not None else None,
            "currency": market_row.get("currency") if isinstance(market_row, Mapping) else primary.get("currency"),
            "as_of_date": market_row.get("session_date") if isinstance(market_row, Mapping) else None,
            "reason_code": None if isinstance(market_row, Mapping) else "CANONICAL_MARKET_NOT_POPULATED",
        }
        models = calculate_seven_models(
            fin,
            est,
            company_assumptions,
            dcf_policy=dcf_policy,
        )
        aggregate = _aggregate_models(models, fin, est)
        _apply_market_sanity_gate(aggregate, _number(market.get("current_price")))
        calculated_values = [Decimal(row["fair_value"]) for row in models.values() if row["status"] == "calculated"]
        calculated_count = len(calculated_values)
        model_counts.update(name for name, row in models.items() if row["status"] == "calculated")
        status = "ready" if calculated_count >= 2 else "partial" if calculated_count == 1 else "unavailable"
        status_counts[status] += 1
        card = {
            "schema_version": "full-market-valuation-card.v031.0",
            "company": {"company_id": company_id, "display_name": company.get("display_name"), "legal_name": company.get("legal_name"), "country": company.get("country"), "business_summary": None, "business_summary_reason_code": "CANONICAL_BUSINESS_SUMMARY_NOT_POPULATED"},
            "primary_security": {"security_id": primary.get("security_id"), "ticker": ticker or None, "exchange": primary.get("exchange"), "currency": primary.get("currency")},
            "securities": [{"security_id": row.get("security_id"), "ticker": row.get("ticker"), "exchange": row.get("exchange"), "primary_listing": row.get("primary_listing")} for row in company_securities],
            "status": status,
            "market": market,
            "financials": fin,
            "financial_history": _quarterly_history(
                _load((root / quarterly_financial_path).parent / str(quarterly_files[company_id]), default=[])
                if company_id in quarterly_files
                else []
            ),
            "estimates": est,
            "valuation": {"status": status, "calculated_model_count": calculated_count, "total_model_count": 7, "fair_value": aggregate["fair_value"], "aggregation_version": "archetype-primary-model-family.v031v.7", "reason_code": aggregate["reason_code"], "aggregation": aggregate["aggregation"], "model_diagnostics": aggregate["model_diagnostics"], "models": models},
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
        "summary": {"company_count": len(cards), "registry_company_count": len(companies), "excluded_non_company_instrument_count": len(companies) - len(cards), "security_count": len(securities), "valuation_security_count": len(eligible_security_ids), "status_counts": {name: status_counts[name] for name in ("ready", "partial", "unavailable")}, "model_calculated_counts": {name: model_counts[name] for name in MODELS}, "market_ready_company_count": sum(card["market"]["status"] == "ready" for card in cards), "financial_present_company_count": sum(bool(financial_by_company.get(card["company"]["company_id"])) for card in cards), "estimate_present_company_count": sum(bool(estimates_by_company.get(card["company"]["company_id"])) for card in cards)},
        "cards": cards,
        "indexes": {"ticker_to_position": ticker_index, "company_id_to_position": {card["company"]["company_id"]: index for index, card in enumerate(cards)}},
    }


def write_full_market_coverage(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    company_root = output.parent / "per-company"
    company_root.mkdir(parents=True, exist_ok=True)
    ticker_to_file: dict[str, str] = {}
    company_id_to_file: dict[str, str] = {}
    for card in report.get("cards") or []:
        company_id = str((card.get("company") or {}).get("company_id") or "")
        if not company_id:
            continue
        filename = quote(company_id, safe="._-") + ".json"
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
    def __init__(self, *, root: Path | None = None, snapshot_path: Path | None = None, coverage_service: CoveragePolicyService | None = None, publication_root: Path | None = None) -> None:
        self.root = root or Path.cwd()
        self.snapshot_path = snapshot_path or self.root / "data/generated/full_market_coverage/full_market_coverage.json"
        self.coverage_service = coverage_service or CoveragePolicyService(root=self.root)
        self.publication_root = publication_root or self.root / "data/generated/publication_gate"
        self._payload: Mapping[str, Any] | None = None
        self._catalog: Mapping[str, Any] | None = None

    def _get_payload(self) -> Mapping[str, Any]:
        if self._payload is None:
            self._payload = _load(self.snapshot_path) if self.snapshot_path.is_file() else build_full_market_coverage(self.root)
        return self._payload

    def list(self) -> dict[str, Any]:
        catalog_path = self.publication_root / "company_catalog.json"
        if catalog_path.is_file():
            if self._catalog is None:
                self._catalog = _load(catalog_path)
            if self._catalog.get("schema_version") == "publication-gate-catalog.v031f.2.1":
                companies = [
                    {"company_id": row["company_id"], "ticker": row["ticker"], "display_name": row.get("display_name"), "status": row.get("valuation_status")}
                    for row in self._catalog.get("companies") or []
                ]
                return {"schema_version": "published-company-list.v031f.2.1", "version": "V031F.2.1", "summary": {"company_count": len(companies), "publication_gate": "coverage-policy.v031f.2.1", "source": "compact_publication_catalog"}, "companies": companies}
        payload = self._get_payload()
        public_ids = self.coverage_service.public_company_ids()
        companies = [
            {"company_id": card["company"]["company_id"], "ticker": card["primary_security"]["ticker"], "display_name": card["company"]["display_name"], "status": card["status"]}
            for card in payload["cards"] if card["company"]["company_id"] in public_ids
        ]
        summary = {
            "company_count": len(companies),
            "source_company_count": payload["summary"].get("company_count"),
            "registry_company_count": payload["summary"].get("registry_company_count"),
            "publication_gate": "coverage-policy.v031f.1",
        }
        return {"schema_version": "published-company-list.v031f.2", "version": "V031F.2", "summary": summary, "companies": companies}

    def get(self, ticker: str) -> Mapping[str, Any]:
        symbol = str(ticker or "").strip().upper()
        coverage = self.coverage_service.require_public(symbol, capability="valuation_card")
        catalog_path = self.publication_root / "company_catalog.json"
        if catalog_path.is_file():
            if self._catalog is None:
                self._catalog = _load(catalog_path)
            filename = (self._catalog.get("indexes") or {}).get("ticker_to_file", {}).get(symbol)
            if filename:
                loose_projection = self.publication_root / "companies" / filename
                if loose_projection.is_file():
                    projection = _load(loose_projection)
                else:
                    archive = self.publication_root / "company_projections.zip"
                    try:
                        with ZipFile(archive) as bundle:
                            projection = json.loads(bundle.read(filename))
                    except (OSError, KeyError, BadZipFile, json.JSONDecodeError) as exc:
                        raise FullMarketCoverageError(f"cannot read company projection for {symbol}: {exc}") from exc
                card = projection.get("valuation_card")
                if isinstance(card, Mapping):
                    return {**card, "coverage_policy": {"product_scope": projection.get("product_scope"), "research_scope": projection.get("research_scope"), "scope_axes": projection.get("scope_axes") or {}, "reason_codes": (projection.get("coverage_policy") or {}).get("reason_codes") or []}}
        payload = self._get_payload()
        filename = payload.get("indexes", {}).get("ticker_to_file", {}).get(symbol)
        if filename:
            card_path = self.snapshot_path.parent / str(filename)
            if not card_path.is_file():
                raise FullMarketCoverageNotFound(
                    f"valuation artifact missing for ticker {symbol}: {card_path}"
                )
            card = _load(card_path)
            return {**card, "coverage_policy": {
                "publication_tier": coverage.get("publication_tier"),
                "reason_codes": coverage.get("reason_codes") or [],
            }}
        position = payload.get("indexes", {}).get("ticker_to_position", {}).get(symbol)
        if position is None:
            raise FullMarketCoverageNotFound(f"ticker not found in full-market population: {symbol}")
        return {**payload["cards"][position], "coverage_policy": {
            "publication_tier": coverage.get("publication_tier"),
            "reason_codes": coverage.get("reason_codes") or [],
        }}
