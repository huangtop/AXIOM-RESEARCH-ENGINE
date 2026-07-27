from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping


class ValuationEligibilityError(RuntimeError):
    pass


DEFAULT_METHODS: dict[str, dict[str, Any]] = {
    "forward_pe": {
        "required": ["previous_close", "forward_eps"],
        "positive": ["previous_close", "forward_eps"],
    },
    "trailing_pe": {
        "required": ["previous_close", "trailing_eps"],
        "positive": ["previous_close", "trailing_eps"],
    },
    "price_to_sales": {
        "required": ["previous_close", "revenue", "diluted_shares_outstanding"],
        "positive": ["previous_close", "revenue", "diluted_shares_outstanding"],
    },
    "ev_to_sales": {
        "required": ["enterprise_value", "revenue"],
        "positive": ["enterprise_value", "revenue"],
    },
    "ev_to_ebitda": {
        "required": ["enterprise_value", "ebitda"],
        "positive": ["enterprise_value", "ebitda"],
    },
    "fcf_yield": {
        "required": ["market_cap", "free_cash_flow"],
        "positive": ["market_cap"],
    },
    "dcf": {
        "required": ["previous_close", "free_cash_flow", "revenue", "diluted_shares_outstanding"],
        "positive": ["previous_close", "free_cash_flow", "revenue", "diluted_shares_outstanding"],
    },
}

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def _load(path: Path, label: str) -> Any:
    if not path.exists():
        raise ValuationEligibilityError(f"{label} not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValuationEligibilityError(f"{label} is not valid JSON: {path}") from exc


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


def _input(company: Mapping[str, Any], name: str) -> tuple[Any, Mapping[str, Any] | None]:
    if name == "previous_close":
        market = company.get("market") if isinstance(company.get("market"), Mapping) else {}
        payload = market.get("previous_close") if isinstance(market.get("previous_close"), Mapping) else None
    else:
        metrics = company.get("financial_metrics") if isinstance(company.get("financial_metrics"), Mapping) else {}
        payload = metrics.get(name) if isinstance(metrics.get(name), Mapping) else None
    return (_number(payload.get("value")) if payload else None), payload


def _confidence(payloads: list[Mapping[str, Any]], stale_inputs: list[str]) -> str:
    ranks = [_CONFIDENCE_RANK.get(str(payload.get("confidence") or "low"), 0) for payload in payloads]
    rank = min(ranks) if ranks else 0
    if stale_inputs:
        rank = max(0, rank - 1)
    return {0: "low", 1: "medium", 2: "high"}[rank]


def _evaluate_method(company: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    required = [str(name) for name in spec.get("required", [])]
    positive = set(str(name) for name in spec.get("positive", []))
    missing: list[str] = []
    invalid: list[str] = []
    stale: list[str] = []
    payloads: list[Mapping[str, Any]] = []
    selected_inputs: dict[str, dict[str, Any]] = {}

    for name in required:
        value, payload = _input(company, name)
        if payload is None or value is None:
            missing.append(name)
            continue
        if name in positive and value <= 0:
            invalid.append(name)
            continue
        payloads.append(payload)
        freshness = str(payload.get("freshness_state") or "")
        if name == "previous_close" and freshness in {"stale", "future"}:
            stale.append(name)
        elif name != "previous_close" and str(company.get("financial_freshness_state") or "") == "stale":
            stale.append(name)
        selected_inputs[name] = {
            "value": value,
            "provider": payload.get("provider"),
            "confidence": payload.get("confidence"),
            "freshness_state": payload.get("freshness_state") if name == "previous_close" else company.get("financial_freshness_state"),
        }

    blocked = bool(missing or invalid)
    confidence = "none" if blocked else _confidence(payloads, sorted(set(stale)))
    if missing:
        reason = "missing_required_inputs"
    elif invalid:
        reason = "non_positive_required_inputs"
    elif stale:
        reason = "eligible_with_stale_inputs"
    else:
        reason = "all_required_inputs_available"
    return {
        "status": "blocked" if blocked else "eligible",
        "confidence": confidence,
        "reason": reason,
        "missing_inputs": sorted(missing),
        "invalid_inputs": sorted(invalid),
        "stale_inputs": sorted(set(stale)),
        "inputs": selected_inputs,
    }


def build_valuation_method_eligibility(
    repository_root: Path,
    *,
    input_path: str = "data/generated/valuation_input/valuation_input_snapshot.json",
    methods: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    snapshot = _load(repository_root / input_path, "valuation input snapshot")
    if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("companies"), list):
        raise ValuationEligibilityError("valuation input snapshot must contain companies array")
    schema_version = str(snapshot.get("schema_version") or "")
    if not schema_version.startswith("valuation-input-snapshot."):
        raise ValuationEligibilityError("unsupported valuation input snapshot schema")

    method_specs = dict(methods or DEFAULT_METHODS)
    companies: list[dict[str, Any]] = []
    method_counts = {name: {"eligible": 0, "blocked": 0} for name in method_specs}
    company_state_counts: dict[str, int] = {}
    issue_records: list[dict[str, Any]] = []

    for company in snapshot["companies"]:
        if not isinstance(company, Mapping):
            continue
        results: dict[str, Any] = {}
        eligible_count = 0
        for method, spec in method_specs.items():
            result = _evaluate_method(company, spec)
            results[method] = result
            method_counts[method][result["status"]] += 1
            if result["status"] == "eligible":
                eligible_count += 1
            else:
                issue_records.append({
                    "company_id": company.get("company_id"),
                    "symbol": company.get("primary_symbol"),
                    "method": method,
                    "reason": result["reason"],
                    "missing_inputs": result["missing_inputs"],
                    "invalid_inputs": result["invalid_inputs"],
                })
        if eligible_count == len(method_specs):
            state = "fully_eligible"
        elif eligible_count:
            state = "partially_eligible"
        else:
            state = "ineligible"
        company_state_counts[state] = company_state_counts.get(state, 0) + 1
        companies.append({
            "company_id": company.get("company_id"),
            "cik": company.get("cik"),
            "primary_symbol": company.get("primary_symbol"),
            "display_name": company.get("display_name"),
            "input_state": company.get("input_state"),
            "eligibility_state": state,
            "eligible_method_count": eligible_count,
            "total_method_count": len(method_specs),
            "methods": results,
        })

    companies.sort(key=lambda row: str(row.get("company_id") or ""))
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "valuation-method-eligibility.v030.12.1",
        "version": "V030.12.1",
        "generated_at": generated_at,
        "as_of_date": snapshot.get("as_of_date"),
        "sources": {
            "valuation_input_path": input_path,
            "valuation_input_schema_version": snapshot.get("schema_version"),
        },
        "summary": {
            "company_count": len(companies),
            "method_count": len(method_specs),
            "company_state_counts": dict(sorted(company_state_counts.items())),
            "method_eligibility_counts": method_counts,
            "blocked_method_record_count": len(issue_records),
        },
        "companies": companies,
        "indexes": {
            "company_id_to_position": {row["company_id"]: i for i, row in enumerate(companies)},
            "symbol_to_company_id": {row["primary_symbol"]: row["company_id"] for row in companies if row.get("primary_symbol")},
        },
        "diagnostics": {"blocked_methods": issue_records},
    }


def write_valuation_method_eligibility(report: Mapping[str, Any], output_path: Path, diagnostic_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    diagnostic = {
        "schema_version": "valuation-method-eligibility-diagnostic.v030.12.1",
        "version": report["version"],
        "generated_at": report["generated_at"],
        "as_of_date": report.get("as_of_date"),
        "summary": report["summary"],
        **report["diagnostics"],
    }
    diagnostic_path.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
