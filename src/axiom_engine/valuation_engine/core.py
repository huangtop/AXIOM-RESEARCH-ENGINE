from __future__ import annotations

import json
import os
import tempfile
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


class ValuationEngineError(RuntimeError):
    pass


def _read_json(path: Path, *, default: Any = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise ValuationEngineError(f"required canonical input not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValuationEngineError(f"cannot read JSON: {path}") from exc


def _decimal(value: Any, label: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValuationEngineError(f"invalid decimal for {label}: {value}") from exc


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _write_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(_plain(payload), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _latest(rows: Iterable[dict[str, Any]], date_keys: tuple[str, ...]) -> dict[str, Any] | None:
    values = list(rows)
    if not values:
        return None
    def key(row: dict[str, Any]) -> tuple[str, str]:
        date_value = next((str(row.get(name, "")) for name in date_keys if row.get(name)), "")
        record_id = str(row.get("financial_fact_id") or row.get("estimate_id") or row.get("market_observation_id") or "")
        return date_value, record_id
    return sorted(values, key=key)[-1]


def _index(rows: list[dict[str, Any]], metric_key: str = "metric") -> dict[str, dict[str, list[dict[str, Any]]]]:
    result: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        company_id = str(row.get("company_id", ""))
        metric = str(row.get(metric_key, ""))
        if company_id and metric:
            result[company_id][metric].append(row)
    return result


def _load_assumptions(path: str | Path) -> dict[str, Any]:
    payload = _read_json(Path(path))
    if not isinstance(payload, dict):
        raise ValuationEngineError("valuation assumption profile must be a JSON object")
    defaults = payload.get("defaults", {})
    companies = payload.get("companies", {})
    if not isinstance(defaults, dict) or not isinstance(companies, dict):
        raise ValuationEngineError("assumption profile defaults and companies must be objects")
    return payload


def _company_assumptions(profile: dict[str, Any], company_id: str, ticker: str | None) -> dict[str, Any]:
    values = dict(profile.get("defaults", {}))
    company_values = profile.get("companies", {}).get(company_id)
    if company_values is None and ticker:
        company_values = profile.get("companies", {}).get(ticker.upper())
    if isinstance(company_values, dict):
        values.update(company_values)
    return values


def _scenario_assumptions(base: dict[str, Any], scenario: str) -> dict[str, Decimal]:
    required = ("fcff_growth_rate", "discount_rate", "terminal_growth_rate", "target_forward_pe", "target_forward_ps")
    missing = [name for name in required if base.get(name) in (None, "")]
    if missing:
        raise ValuationEngineError("missing valuation assumptions: " + ", ".join(missing))
    values = {name: _decimal(base[name], name) for name in required}
    values["target_ev_ebitda"] = _decimal(base.get("target_ev_ebitda", "0"), "target_ev_ebitda")
    adjustments = base.get("scenarios", {}).get(scenario, {}) if isinstance(base.get("scenarios"), dict) else {}
    for name, delta in adjustments.items():
        if name in values:
            values[name] += _decimal(delta, f"scenario.{scenario}.{name}")
    return values


def _record_value(index: dict[str, list[dict[str, Any]]], metric: str, date_keys: tuple[str, ...]) -> tuple[Decimal, dict[str, Any]] | None:
    row = _latest(index.get(metric, []), date_keys)
    if row is None:
        return None
    return _decimal(row.get("value"), metric), row


def _dcf(facts: dict[str, list[dict[str, Any]]], assumptions: dict[str, Decimal], years: int) -> dict[str, Any]:
    ocf = _record_value(facts, "operating_cash_flow", ("period_end",))
    capex = _record_value(facts, "capital_expenditures", ("period_end",))
    cash = _record_value(facts, "cash_and_cash_equivalents", ("period_end",))
    debt = _record_value(facts, "total_debt", ("period_end",))
    shares = _record_value(facts, "diluted_shares_outstanding", ("period_end",))
    missing = [name for name, item in (("operating_cash_flow", ocf), ("capital_expenditures", capex), ("cash_and_cash_equivalents", cash), ("total_debt", debt), ("diluted_shares_outstanding", shares)) if item is None]
    if missing:
        return {"method": "discounted_cash_flow", "status": "unavailable", "diagnostics": ["missing financial facts: " + ", ".join(missing)]}
    assert ocf and capex and cash and debt and shares
    base_fcff = ocf[0] - abs(capex[0])
    discount = assumptions["discount_rate"]
    terminal_growth = assumptions["terminal_growth_rate"]
    growth = assumptions["fcff_growth_rate"]
    if base_fcff <= 0:
        return {"method": "discounted_cash_flow", "status": "unavailable", "diagnostics": ["non-positive FCFF proxy"]}
    if shares[0] <= 0:
        return {"method": "discounted_cash_flow", "status": "unavailable", "diagnostics": ["shares outstanding must be positive"]}
    if discount <= terminal_growth or discount <= 0:
        return {"method": "discounted_cash_flow", "status": "unavailable", "diagnostics": ["discount rate must exceed terminal growth rate"]}
    projected = base_fcff
    pv_fcff = Decimal("0")
    forecast: list[dict[str, Any]] = []
    for year in range(1, years + 1):
        projected *= Decimal("1") + growth
        discounted = projected / ((Decimal("1") + discount) ** year)
        pv_fcff += discounted
        forecast.append({"year": year, "fcff": projected, "present_value": discounted})
    terminal_value = projected * (Decimal("1") + terminal_growth) / (discount - terminal_growth)
    pv_terminal = terminal_value / ((Decimal("1") + discount) ** years)
    enterprise_value = pv_fcff + pv_terminal
    equity_value = enterprise_value + cash[0] - debt[0]
    fair_value = equity_value / shares[0]
    source_ids = [item[1].get("financial_fact_id") for item in (ocf, capex, cash, debt, shares)]
    return {
        "method": "discounted_cash_flow",
        "status": "completed",
        "fair_value_per_share": fair_value,
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "inputs": {"base_fcff_proxy": base_fcff, "fcff_growth_rate": growth, "discount_rate": discount, "terminal_growth_rate": terminal_growth, "forecast_years": years},
        "forecast": forecast,
        "source_record_ids": [item for item in source_ids if item],
        "diagnostics": ["FCFF proxy calculated as operating cash flow minus absolute capital expenditures"],
    }


def _multiples(facts: dict[str, list[dict[str, Any]]], estimates: dict[str, list[dict[str, Any]]], market: dict[str, list[dict[str, Any]]], assumptions: dict[str, Decimal]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    shares = _record_value(market, "shares_outstanding", ("observed_at", "trading_date")) or _record_value(facts, "diluted_shares_outstanding", ("period_end",))
    eps = _record_value(estimates, "diluted_eps", ("period_end",)) or _record_value(estimates, "eps_diluted", ("period_end",))
    if eps and eps[0] > 0 and assumptions["target_forward_pe"] > 0:
        results.append({"method": "forward_pe", "status": "completed", "fair_value_per_share": eps[0] * assumptions["target_forward_pe"], "inputs": {"forward_eps": eps[0], "target_forward_pe": assumptions["target_forward_pe"]}, "source_record_ids": [eps[1].get("estimate_id")]})
    else:
        results.append({"method": "forward_pe", "status": "unavailable", "diagnostics": ["positive diluted EPS estimate is required"]})
    revenue = _record_value(estimates, "revenue", ("period_end",))
    if revenue and shares and shares[0] > 0 and assumptions["target_forward_ps"] > 0:
        results.append({"method": "forward_ps", "status": "completed", "fair_value_per_share": (revenue[0] * assumptions["target_forward_ps"]) / shares[0], "inputs": {"forward_revenue": revenue[0], "shares_outstanding": shares[0], "target_forward_ps": assumptions["target_forward_ps"]}, "source_record_ids": [revenue[1].get("estimate_id"), shares[1].get("market_observation_id") or shares[1].get("financial_fact_id")]})
    else:
        results.append({"method": "forward_ps", "status": "unavailable", "diagnostics": ["forward revenue and positive shares outstanding are required"]})
    ebitda = _record_value(estimates, "ebitda", ("period_end",))
    cash = _record_value(facts, "cash_and_cash_equivalents", ("period_end",))
    debt = _record_value(facts, "total_debt", ("period_end",))
    if ebitda and shares and cash and debt and shares[0] > 0 and assumptions["target_ev_ebitda"] > 0:
        equity = ebitda[0] * assumptions["target_ev_ebitda"] + cash[0] - debt[0]
        results.append({"method": "forward_ev_ebitda", "status": "completed", "fair_value_per_share": equity / shares[0], "inputs": {"forward_ebitda": ebitda[0], "target_ev_ebitda": assumptions["target_ev_ebitda"]}, "source_record_ids": [ebitda[1].get("estimate_id")]})
    else:
        results.append({"method": "forward_ev_ebitda", "status": "unavailable", "diagnostics": ["forward EBITDA, cash, debt, and positive shares are required"]})
    return results


def _confidence(methods: list[dict[str, Any]], market_rows: dict[str, list[dict[str, Any]]], assumptions: dict[str, Any]) -> dict[str, Any]:
    completed = sum(1 for item in methods if item.get("status") == "completed")
    method_score = round(70 * completed / max(len(methods), 1))
    market_score = 15 if "current_price" in market_rows else 0
    assumption_score = 15 if assumptions.get("source") and assumptions.get("as_of_date") else 8
    score = min(100, method_score + market_score + assumption_score)
    return {"score": score, "components": {"method_completion": method_score, "market_freshness": market_score, "assumption_provenance": assumption_score}}


def _ticker_map(registry_dir: str | Path) -> tuple[dict[str, str], dict[str, str]]:
    root = Path(registry_dir)
    companies = _read_json(root / "companies.json", default=[])
    securities = _read_json(root / "securities.json", default=[])
    names = {str(row.get("company_id")): str(row.get("display_name") or row.get("legal_name") or row.get("company_id")) for row in companies}
    tickers = {str(row.get("company_id")): str(row.get("ticker", "")).upper() for row in securities if row.get("primary_listing", True)}
    return names, tickers


def build_valuations(
    *,
    financial_dir: str | Path = "data/financial_data",
    estimate_dir: str | Path = "data/estimate_data",
    market_dir: str | Path = "data/market_data",
    registry_dir: str | Path = "data/company_registry",
    assumptions_file: str | Path = "data/valuation_assumptions.json",
    output_dir: str | Path = "data/valuation_data",
    company: str | None = None,
    scenarios: tuple[str, ...] = ("bear", "base", "bull"),
    forecast_years: int = 5,
    write: bool = False,
    compact: bool = False,
) -> dict[str, Any]:
    if forecast_years < 1 or forecast_years > 20:
        raise ValuationEngineError("forecast_years must be between 1 and 20")
    facts = _read_json(Path(financial_dir) / "financial_facts.json")
    estimates = _read_json(Path(estimate_dir) / "estimates.json")
    market = _read_json(Path(market_dir) / "observations.json", default=[])
    if not isinstance(facts, list) or not isinstance(estimates, list) or not isinstance(market, list):
        raise ValuationEngineError("canonical financial, estimate, and market inputs must be JSON arrays")
    profile = _load_assumptions(assumptions_file)
    names, tickers = _ticker_map(registry_dir)
    fact_index, estimate_index, market_index = _index(facts), _index(estimates), _index(market)
    company_ids = sorted(set(fact_index) | set(estimate_index))
    if company:
        token = company.strip()
        matches = [cid for cid in company_ids if cid == token or tickers.get(cid, "").upper() == token.upper()]
        if not matches:
            raise ValuationEngineError(f"company not found in canonical inputs: {company}")
        company_ids = matches
    valuations: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    as_of = str(profile.get("as_of_date") or date.today().isoformat())
    for company_id in company_ids:
        ticker = tickers.get(company_id)
        base_assumptions = _company_assumptions(profile, company_id, ticker)
        for scenario in scenarios:
            try:
                scenario_values = _scenario_assumptions(base_assumptions, scenario)
            except ValuationEngineError as exc:
                diagnostics.append({"company_id": company_id, "scenario": scenario, "severity": "error", "code": "missing_assumptions", "message": str(exc)})
                continue
            methods = [_dcf(fact_index[company_id], scenario_values, forecast_years), *_multiples(fact_index[company_id], estimate_index[company_id], market_index[company_id], scenario_values)]
            completed = [item for item in methods if item.get("status") == "completed" and item.get("fair_value_per_share") is not None]
            weights = base_assumptions.get("method_weights", {"discounted_cash_flow": "0.5", "forward_pe": "0.3", "forward_ps": "0.2", "forward_ev_ebitda": "0"})
            weighted: list[tuple[Decimal, Decimal]] = []
            for method in completed:
                weight = _decimal(weights.get(method["method"], "0"), f"weight.{method['method']}")
                if weight > 0:
                    weighted.append((_decimal(method["fair_value_per_share"], method["method"]), weight))
            total_weight = sum((weight for _, weight in weighted), Decimal("0"))
            blended = sum((value * weight for value, weight in weighted), Decimal("0")) / total_weight if total_weight else None
            current = _record_value(market_index[company_id], "current_price", ("observed_at", "trading_date"))
            upside = ((blended / current[0]) - Decimal("1")) if blended is not None and current and current[0] > 0 else None
            confidence = _confidence(methods, market_index[company_id], base_assumptions)
            status = "completed" if len(completed) == len(methods) else "partial" if completed else "unavailable"
            valuation_id = f"valuation:{company_id.removeprefix('company:')}:{as_of}:{scenario}"
            valuations.append({
                "valuation_id": valuation_id,
                "company_id": company_id,
                "company_name": names.get(company_id, company_id),
                "ticker": ticker,
                "as_of_date": as_of,
                "scenario": scenario,
                "currency": next((row.get("currency") for rows in fact_index[company_id].values() for row in rows if row.get("currency")), "USD"),
                "status": status,
                "blended_fair_value_per_share": blended,
                "current_price": current[0] if current else None,
                "upside_downside": upside,
                "confidence": confidence,
                "methods": methods,
                "assumptions": scenario_values,
            })
            for method in methods:
                for message in method.get("diagnostics", []):
                    diagnostics.append({"company_id": company_id, "scenario": scenario, "method": method["method"], "severity": "warning" if method.get("status") == "completed" else "error", "code": "method_diagnostic", "message": message})
        provenance.append({"company_id": company_id, "assumption_source": base_assumptions.get("source") or profile.get("source"), "assumption_as_of_date": base_assumptions.get("as_of_date") or as_of, "assumptions_file": str(assumptions_file)})
    completed_count = sum(1 for row in valuations if row["status"] == "completed")
    partial_count = sum(1 for row in valuations if row["status"] == "partial")
    unavailable_count = sum(1 for row in valuations if row["status"] == "unavailable")
    report = {
        "companies_requested": len(company_ids),
        "valuations_built": len(valuations),
        "valuations_completed": completed_count,
        "valuations_partial": partial_count,
        "valuations_unavailable": unavailable_count,
        "scenarios": list(scenarios),
        "forecast_years": forecast_years,
        "output_directory": str(output_dir),
        "dry_run": not write,
        "acceptance_passed": bool(valuations) and completed_count + partial_count == len(valuations),
    }
    if not compact:
        report["diagnostics"] = diagnostics
    else:
        report["diagnostic_summary"] = {"errors": sum(1 for row in diagnostics if row["severity"] == "error"), "warnings": sum(1 for row in diagnostics if row["severity"] == "warning")}
    if write:
        root = Path(output_dir)
        manifest = {"schema_version": "1.0.0", "generated_at": datetime.now(timezone.utc).isoformat(), **{key: value for key, value in report.items() if key != "diagnostics"}, "files": ["valuations.json", "diagnostics.json", "provenance.json", "manifest.json"]}
        _write_atomic(root / "valuations.json", valuations)
        _write_atomic(root / "diagnostics.json", diagnostics)
        _write_atomic(root / "provenance.json", provenance)
        _write_atomic(root / "manifest.json", manifest)
    return _plain(report)


def validate_valuations(output_dir: str | Path = "data/valuation_data") -> dict[str, Any]:
    root = Path(output_dir)
    valuations = _read_json(root / "valuations.json")
    diagnostics = _read_json(root / "diagnostics.json")
    provenance = _read_json(root / "provenance.json")
    manifest = _read_json(root / "manifest.json")
    errors: list[str] = []
    if not isinstance(valuations, list): errors.append("valuations.json must be an array")
    if not isinstance(diagnostics, list): errors.append("diagnostics.json must be an array")
    if not isinstance(provenance, list): errors.append("provenance.json must be an array")
    if not isinstance(manifest, dict): errors.append("manifest.json must be an object")
    ids = [row.get("valuation_id") for row in valuations if isinstance(row, dict)] if isinstance(valuations, list) else []
    if len(ids) != len(set(ids)): errors.append("duplicate valuation_id")
    required = {"valuation_id", "company_id", "as_of_date", "scenario", "status", "methods", "confidence"}
    for index, row in enumerate(valuations if isinstance(valuations, list) else []):
        missing = required - set(row)
        if missing: errors.append(f"valuation[{index}] missing: {sorted(missing)}")
    return {"output_directory": str(root), "valuations": len(valuations) if isinstance(valuations, list) else 0, "diagnostics": len(diagnostics) if isinstance(diagnostics, list) else 0, "valid": not errors, "errors": errors}
