from __future__ import annotations

import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


class ValuationStrategyError(RuntimeError):
    pass


def _read(path: Path, default: Any = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise ValuationStrategyError(f"required input not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValuationStrategyError(f"cannot read JSON: {path}") from exc


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _dec(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _latest(rows: list[dict[str, Any]], metric: str) -> dict[str, Any] | None:
    values = [row for row in rows if row.get("metric") == metric]
    if not values:
        return None
    return sorted(values, key=lambda row: (str(row.get("period_end") or row.get("observed_at") or row.get("trading_date") or ""), str(row.get("financial_fact_id") or row.get("estimate_id") or row.get("market_observation_id") or "")))[-1]


def _value(rows: list[dict[str, Any]], metric: str) -> Decimal | None:
    row = _latest(rows, metric)
    return _dec(row.get("value")) if row else None


def _source_id(row: dict[str, Any] | None) -> str | None:
    if not row:
        return None
    return str(row.get("financial_fact_id") or row.get("estimate_id") or row.get("market_observation_id") or "") or None


def _result(company_id: str, ticker: str, method: str, tier: str, confidence: int, fair_value: Decimal | None, reason: str | None, missing: list[str], source_ids: list[str], status: str = "selected") -> dict[str, Any]:
    return {
        "strategy_id": f"valuation_strategy:{company_id}:{method}",
        "company_id": company_id,
        "ticker": ticker,
        "status": status,
        "selected_strategy": method,
        "coverage_tier": tier,
        "confidence": confidence,
        "fair_value_per_share": str(fair_value.normalize()) if fair_value is not None else None,
        "fallback_reason": reason,
        "missing_inputs": missing,
        "source_record_ids": sorted(set(source_ids)),
    }


def _select(company_id: str, ticker: str, facts: list[dict[str, Any]], estimates: list[dict[str, Any]], market: list[dict[str, Any]]) -> dict[str, Any]:
    shares = _value(facts, "diluted_shares_outstanding") or _value(market, "shares_outstanding")
    price = _value(market, "current_price")
    cash = _value(facts, "cash_and_cash_equivalents") or Decimal("0")
    debt = _value(facts, "total_debt") or Decimal("0")
    ocf = _value(facts, "operating_cash_flow")
    capex = _value(facts, "capital_expenditures")
    revenue = _value(facts, "revenue")
    book_value = _value(facts, "stockholders_equity") or _value(facts, "total_equity")
    eps = _value(estimates, "diluted_eps")
    forward_revenue = _value(estimates, "revenue")
    forward_ebitda = _value(estimates, "ebitda")

    source_ids: list[str] = []
    for rows, metrics in ((facts, ("diluted_shares_outstanding","operating_cash_flow","capital_expenditures","revenue","cash_and_cash_equivalents","total_debt","stockholders_equity","total_equity")), (estimates, ("diluted_eps","revenue","ebitda")), (market, ("shares_outstanding","current_price"))):
        for metric in metrics:
            sid = _source_id(_latest(rows, metric))
            if sid:
                source_ids.append(sid)

    if shares and shares > 0 and eps and eps > 0:
        fair = eps * Decimal("18")
        return _result(company_id, ticker, "forward_pe", "A", 85, fair, None, [], source_ids)

    if shares and shares > 0 and forward_ebitda and forward_ebitda > 0:
        equity = forward_ebitda * Decimal("10") + cash - debt
        return _result(company_id, ticker, "forward_ev_ebitda", "A", 82, equity / shares, "missing_forward_eps", ["forward_eps"], source_ids)

    if shares and shares > 0 and ocf is not None and capex is not None:
        fcff = ocf - abs(capex)
        if fcff > 0:
            # Stable perpetuity proxy: explicit and conservative; not a full forecast DCF.
            enterprise = fcff * Decimal("12")
            fair = (enterprise + cash - debt) / shares
            return _result(company_id, ticker, "historical_fcff_multiple", "B", 68, fair, "missing_forward_estimates", ["forward_eps", "forward_ebitda"], source_ids)

    if shares and shares > 0 and (forward_revenue or revenue):
        base_revenue = forward_revenue or revenue
        fair = (base_revenue * Decimal("2.5") + cash - debt) / shares
        return _result(company_id, ticker, "revenue_multiple", "C", 55, fair, "cash_flow_inputs_unavailable", ["operating_cash_flow", "capital_expenditures"], source_ids)

    if shares and shares > 0 and book_value and book_value > 0:
        return _result(company_id, ticker, "book_value", "D", 42, book_value / shares, "income_and_cash_flow_inputs_unavailable", ["forward_estimates", "cash_flow", "revenue"], source_ids)

    missing = []
    if not shares or shares <= 0:
        missing.append("shares_outstanding")
    if price is None:
        missing.append("current_price")
    if not any((eps, forward_ebitda, ocf, revenue, forward_revenue, book_value)):
        missing.append("valuation_basis")
    return _result(company_id, ticker, "insufficient_data", "X", 0, None, "no_supported_strategy_inputs", missing, source_ids, status="unavailable")


def build_valuation_strategies(*, registry_dir: str | Path = "data/company_registry", financial_dir: str | Path = "data/financial_data", estimate_dir: str | Path = "data/estimate_data", market_dir: str | Path = "data/market_data", output_dir: str | Path = "data/valuation_strategy", company: str | None = None, write: bool = False) -> dict[str, Any]:
    registry = Path(registry_dir)
    companies = _read(registry / "companies.json")
    securities = _read(registry / "securities.json", [])
    facts = _read(Path(financial_dir) / "financial_facts.json", [])
    estimates = _read(Path(estimate_dir) / "estimates.json", [])
    market = _read(Path(market_dir) / "observations.json", [])
    for name, payload in (("companies", companies), ("securities", securities), ("financial facts", facts), ("estimates", estimates), ("market observations", market)):
        if not isinstance(payload, list):
            raise ValuationStrategyError(f"{name} must be a JSON array")

    tickers = {str(row.get("company_id")): str(row.get("ticker", "")).upper() for row in securities if row.get("company_id") and row.get("primary_listing", True)}
    grouped_facts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_estimates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in facts:
        grouped_facts[str(row.get("company_id"))].append(row)
    for row in estimates:
        grouped_estimates[str(row.get("company_id"))].append(row)
    for row in market:
        grouped_market[str(row.get("company_id"))].append(row)

    results = []
    for row in companies:
        company_id = str(row.get("company_id", ""))
        ticker = tickers.get(company_id, "")
        if company and company not in (company_id, ticker):
            continue
        results.append(_select(company_id, ticker, grouped_facts[company_id], grouped_estimates[company_id], grouped_market[company_id]))
    if company and not results:
        raise ValuationStrategyError(f"company not found: {company}")

    counts: dict[str, int] = defaultdict(int)
    for row in results:
        counts[row["coverage_tier"]] += 1
    generated_at = datetime.now(timezone.utc).isoformat()
    output = Path(output_dir)
    payload = {"schema_version": "1.0.0", "generated_at": generated_at, "strategies": results}
    diagnostics = [{"severity": "warning" if row["coverage_tier"] != "X" else "error", "company_id": row["company_id"], "ticker": row["ticker"], "code": "valuation_fallback_selected" if row["coverage_tier"] != "X" else "valuation_strategy_unavailable", "message": row["fallback_reason"], "missing_inputs": row["missing_inputs"]} for row in results if row["fallback_reason"]]
    manifest = {"schema_version": "1.0.0", "generated_at": generated_at, "company_count": len(results), "selected": sum(1 for row in results if row["status"] == "selected"), "unavailable": sum(1 for row in results if row["status"] == "unavailable"), "coverage_tiers": dict(sorted(counts.items())), "files": ["valuation_strategies.json", "diagnostics.json", "manifest.json"]}
    if write:
        _write(output / "valuation_strategies.json", payload)
        _write(output / "diagnostics.json", diagnostics)
        _write(output / "manifest.json", manifest)
    return {"valid": True, **manifest, "output_dir": str(output), "dry_run": not write}


def validate_valuation_strategies(*, output_dir: str | Path = "data/valuation_strategy") -> dict[str, Any]:
    output = Path(output_dir)
    errors: list[str] = []
    try:
        payload = _read(output / "valuation_strategies.json")
        manifest = _read(output / "manifest.json")
    except ValuationStrategyError as exc:
        return {"valid": False, "errors": [str(exc)], "output_dir": str(output)}
    rows = payload.get("strategies") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        errors.append("valuation_strategies.json strategies must be an array")
        rows = []
    required = {"strategy_id", "company_id", "status", "selected_strategy", "coverage_tier", "confidence", "missing_inputs"}
    ids: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"strategy[{index}] must be an object")
            continue
        missing = sorted(required - set(row))
        if missing:
            errors.append(f"strategy[{index}] missing: {', '.join(missing)}")
        sid = str(row.get("strategy_id", ""))
        if sid in ids:
            errors.append(f"duplicate strategy_id: {sid}")
        ids.add(sid)
        if row.get("coverage_tier") not in {"A", "B", "C", "D", "X"}:
            errors.append(f"invalid coverage_tier: {row.get('coverage_tier')}")
    if isinstance(manifest, dict) and manifest.get("company_count") != len(rows):
        errors.append("manifest company_count mismatch")
    return {"valid": not errors, "errors": errors, "output_dir": str(output), "company_count": len(rows)}
