from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping


class ValuationInputError(RuntimeError):
    pass


def _load(path: Path, label: str) -> Any:
    if not path.exists():
        raise ValuationInputError(f"{label} not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValuationInputError(f"{label} is not valid JSON: {path}") from exc


def _number(value: Any) -> int | float | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return int(number) if number == number.to_integral_value() else float(number)


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _market_payload(row: Mapping[str, Any], *, as_of: date) -> dict[str, Any] | None:
    close = _number(row.get("close"))
    session_date = _parse_date(row.get("session_date"))
    if close is None or close <= 0 or session_date is None:
        return None
    age_days = (as_of - session_date).days
    freshness = "future" if age_days < 0 else "fresh" if age_days <= 7 else "stale"
    confidence = "high" if freshness == "fresh" else "low"
    return {
        "value": close,
        "currency": row.get("currency"),
        "session_date": session_date.isoformat(),
        "age_days": age_days,
        "freshness_state": freshness,
        "provider": row.get("provider") or "yahoo_finance",
        "confidence": confidence,
        "source_state": "completed_session_close",
        "exchange_timezone": row.get("exchange_timezone"),
    }


def _resolve_market_path(repository_root: Path, configured_path: str) -> tuple[Path | None, str | None]:
    candidates = [
        configured_path,
        "data/generated/market/previous_close_cache.json",
        "data/cache/previous_closes.json",
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        path = repository_root / candidate
        if path.exists():
            return path, candidate
    return None, None


def build_valuation_input_snapshot(
    repository_root: Path,
    *,
    router_path: str = "data/generated/source_router/financial_source_snapshot.json",
    qa_path: str = "data/generated/bridge_qa/bridge_qa_report.json",
    market_path: str = "data/generated/market/previous_close_cache.json",
    as_of: date | None = None,
) -> dict[str, Any]:
    as_of = as_of or datetime.now(timezone.utc).date()
    router = _load(repository_root / router_path, "financial source snapshot")
    qa = _load(repository_root / qa_path, "bridge QA report")
    if not isinstance(router, Mapping) or not isinstance(router.get("companies"), list):
        raise ValuationInputError("financial source snapshot must contain companies array")
    if not isinstance(qa, Mapping) or qa.get("status") != "pass":
        raise ValuationInputError("bridge QA must exist and have status=pass")

    resolved_market_path, market_source_path = _resolve_market_path(repository_root, market_path)
    market = _load(resolved_market_path, "previous close cache") if resolved_market_path else {"symbols": {}}
    symbols = market.get("symbols") if isinstance(market, Mapping) else {}
    if not isinstance(symbols, Mapping):
        symbols = {}

    companies: list[dict[str, Any]] = []
    missing_market: list[dict[str, Any]] = []
    invalid_market: list[dict[str, Any]] = []
    state_counts: dict[str, int] = {}
    market_freshness_counts: dict[str, int] = {}
    provider_metric_counts = {"sec_companyfacts": 0, "yahoo_finance": 0}
    market_matched = 0
    valuation_ready = 0

    for company in router["companies"]:
        if not isinstance(company, Mapping):
            continue
        company_id = str(company.get("company_id") or "")
        symbol = str(company.get("primary_symbol") or "").strip().upper()
        financial_metrics = company.get("metrics") if isinstance(company.get("metrics"), Mapping) else {}
        normalized_metrics = dict(sorted((str(k), v) for k, v in financial_metrics.items() if isinstance(v, Mapping)))
        for metric in normalized_metrics.values():
            provider = metric.get("provider")
            if provider in provider_metric_counts:
                provider_metric_counts[provider] += 1

        raw_market = symbols.get(symbol) if symbol else None
        market_payload = _market_payload(raw_market, as_of=as_of) if isinstance(raw_market, Mapping) else None
        if market_payload:
            market_matched += 1
            freshness = market_payload["freshness_state"]
            market_freshness_counts[freshness] = market_freshness_counts.get(freshness, 0) + 1
        elif isinstance(raw_market, Mapping):
            invalid_market.append({"company_id": company_id, "symbol": symbol, "reason": "invalid_previous_close"})
        else:
            missing_market.append({"company_id": company_id, "symbol": symbol, "reason": "previous_close_not_found"})

        has_financials = bool(normalized_metrics)
        has_usable_market = bool(market_payload and market_payload["freshness_state"] != "future")
        if has_financials and has_usable_market:
            input_state = "ready"
            valuation_ready += 1
        elif has_financials:
            input_state = "financial_only"
        elif has_usable_market:
            input_state = "market_only"
        else:
            input_state = "insufficient"
        state_counts[input_state] = state_counts.get(input_state, 0) + 1

        companies.append({
            "company_id": company_id,
            "cik": company.get("cik"),
            "primary_symbol": symbol,
            "display_name": company.get("display_name"),
            "input_state": input_state,
            "routing_state": company.get("routing_state"),
            "financial_freshness_state": company.get("freshness_state"),
            "market": {"previous_close": market_payload} if market_payload else {},
            "financial_metrics": normalized_metrics,
            "capabilities": {
                "has_previous_close": market_payload is not None,
                "has_trailing_eps": "trailing_eps" in normalized_metrics,
                "has_forward_eps": "forward_eps" in normalized_metrics,
                "has_revenue": "revenue" in normalized_metrics,
                "has_net_income": "net_income" in normalized_metrics,
                "has_free_cash_flow": "free_cash_flow" in normalized_metrics,
                "has_enterprise_value": "enterprise_value" in normalized_metrics,
            },
        })

    companies.sort(key=lambda row: row["company_id"])
    generated_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "company_count": len(companies),
        "valuation_ready_company_count": valuation_ready,
        "market_cached_symbol_count": len(symbols),
        "market_matched_company_count": market_matched,
        "missing_market_company_count": len(missing_market),
        "invalid_market_company_count": len(invalid_market),
        "input_state_counts": dict(sorted(state_counts.items())),
        "market_freshness_counts": dict(sorted(market_freshness_counts.items())),
        "provider_metric_counts": provider_metric_counts,
    }
    return {
        "schema_version": "valuation-input-snapshot.v030.12.0",
        "version": "V030.12.0",
        "generated_at": generated_at,
        "as_of_date": as_of.isoformat(),
        "sources": {
            "router_path": router_path,
            "router_schema_version": router.get("schema_version"),
            "bridge_qa_path": qa_path,
            "bridge_qa_schema_version": qa.get("schema_version"),
            "bridge_qa_status": qa.get("status"),
            "market_path": market_source_path or market_path,
            "market_schema_version": market.get("schema_version") if isinstance(market, Mapping) else None,
        },
        "summary": summary,
        "companies": companies,
        "indexes": {
            "company_id_to_position": {company["company_id"]: index for index, company in enumerate(companies)},
            "symbol_to_company_id": {company["primary_symbol"]: company["company_id"] for company in companies if company["primary_symbol"]},
        },
        "diagnostics": {"missing_market": missing_market, "invalid_market": invalid_market},
    }


def write_valuation_input_snapshot(report: Mapping[str, Any], output_path: Path, diagnostic_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    diagnostic = {
        "schema_version": "valuation-input-diagnostic.v030.12.0",
        "version": report["version"],
        "generated_at": report["generated_at"],
        "as_of_date": report["as_of_date"],
        "summary": report["summary"],
        **report["diagnostics"],
    }
    diagnostic_path.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
