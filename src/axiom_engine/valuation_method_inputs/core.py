from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping


class ValuationMethodInputsError(RuntimeError):
    pass


FORMULA_VERSIONS = {
    "forward_pe": "forward-pe-inputs.v1",
    "trailing_pe": "trailing-pe-inputs.v1",
    "price_to_sales": "price-to-sales-inputs.v1",
    "ev_to_sales": "ev-to-sales-inputs.v1",
    "ev_to_ebitda": "ev-to-ebitda-inputs.v1",
    "fcf_yield": "fcf-yield-inputs.v1",
    "dcf": "dcf-base-inputs.v1",
}


def _load(path: Path, label: str) -> Any:
    if not path.exists():
        raise ValuationMethodInputsError(f"{label} not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValuationMethodInputsError(f"{label} is not valid JSON: {path}") from exc


def _number(value: Any) -> int | float | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return int(number) if number == number.to_integral_value() else float(number)


def _divide(numerator: Any, denominator: Any) -> float | None:
    n = _number(numerator)
    d = _number(denominator)
    if n is None or d in (None, 0):
        return None
    return float(Decimal(str(n)) / Decimal(str(d)))


def _input_value(company: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    if name == "previous_close":
        market = company.get("market") if isinstance(company.get("market"), Mapping) else {}
        value = market.get("previous_close")
    else:
        metrics = company.get("financial_metrics") if isinstance(company.get("financial_metrics"), Mapping) else {}
        value = metrics.get(name)
    return value if isinstance(value, Mapping) else None


def _source(payload: Mapping[str, Any] | None, *, financial_freshness: Any = None) -> dict[str, Any] | None:
    if payload is None:
        return None
    result = {
        "value": _number(payload.get("value")),
        "provider": payload.get("provider"),
        "confidence": payload.get("confidence"),
        "source_state": payload.get("source_state"),
        "period_end": payload.get("period_end"),
        "fallback_reason": payload.get("fallback_reason"),
        "source_field": payload.get("source_field"),
        "source_fact_ids": payload.get("source_fact_ids"),
    }
    if payload.get("freshness_state") is not None:
        result["freshness_state"] = payload.get("freshness_state")
    elif financial_freshness is not None:
        result["freshness_state"] = financial_freshness
    return result


def _calculation(method: str, company: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    financial_freshness = company.get("financial_freshness_state")
    names_by_method = {
        "forward_pe": ["previous_close", "forward_eps"],
        "trailing_pe": ["previous_close", "trailing_eps"],
        "price_to_sales": ["previous_close", "revenue", "diluted_shares_outstanding"],
        "ev_to_sales": ["enterprise_value", "revenue"],
        "ev_to_ebitda": ["enterprise_value", "ebitda"],
        "fcf_yield": ["market_cap", "free_cash_flow"],
        "dcf": ["previous_close", "free_cash_flow", "revenue", "diluted_shares_outstanding"],
    }
    raw = {
        name: _source(_input_value(company, name), financial_freshness=financial_freshness)
        for name in names_by_method[method]
    }
    values = {name: payload["value"] if payload else None for name, payload in raw.items()}

    if method == "forward_pe":
        derived = {"current_multiple": _divide(values["previous_close"], values["forward_eps"])}
    elif method == "trailing_pe":
        derived = {"current_multiple": _divide(values["previous_close"], values["trailing_eps"])}
    elif method == "price_to_sales":
        revenue_per_share = _divide(values["revenue"], values["diluted_shares_outstanding"])
        derived = {
            "revenue_per_share": revenue_per_share,
            "current_multiple": _divide(values["previous_close"], revenue_per_share),
        }
    elif method == "ev_to_sales":
        derived = {"current_multiple": _divide(values["enterprise_value"], values["revenue"])}
    elif method == "ev_to_ebitda":
        derived = {"current_multiple": _divide(values["enterprise_value"], values["ebitda"])}
    elif method == "fcf_yield":
        derived = {
            "current_yield": _divide(values["free_cash_flow"], values["market_cap"]),
            "current_yield_percent": (_divide(values["free_cash_flow"], values["market_cap"]) or 0.0) * 100,
        }
    elif method == "dcf":
        derived = {
            "free_cash_flow_per_share": _divide(values["free_cash_flow"], values["diluted_shares_outstanding"]),
            "revenue_per_share": _divide(values["revenue"], values["diluted_shares_outstanding"]),
            "current_price": _number(values["previous_close"]),
        }
    else:
        raise ValuationMethodInputsError(f"unsupported method: {method}")
    return raw, derived


def build_valuation_method_inputs(
    repository_root: Path,
    *,
    input_path: str = "data/generated/valuation_input/valuation_input_snapshot.json",
    eligibility_path: str = "data/generated/valuation_eligibility/valuation_method_eligibility.json",
) -> dict[str, Any]:
    snapshot = _load(repository_root / input_path, "valuation input snapshot")
    eligibility = _load(repository_root / eligibility_path, "valuation method eligibility")
    if not isinstance(snapshot, Mapping) or not str(snapshot.get("schema_version") or "").startswith("valuation-input-snapshot."):
        raise ValuationMethodInputsError("unsupported valuation input snapshot schema")
    if not isinstance(eligibility, Mapping) or not str(eligibility.get("schema_version") or "").startswith("valuation-method-eligibility."):
        raise ValuationMethodInputsError("unsupported valuation eligibility schema")
    if not isinstance(snapshot.get("companies"), list) or not isinstance(eligibility.get("companies"), list):
        raise ValuationMethodInputsError("both source snapshots must contain companies arrays")

    input_by_id = {str(row.get("company_id")): row for row in snapshot["companies"] if isinstance(row, Mapping)}
    eligibility_by_id = {str(row.get("company_id")): row for row in eligibility["companies"] if isinstance(row, Mapping)}
    if set(input_by_id) != set(eligibility_by_id):
        raise ValuationMethodInputsError("valuation input and eligibility company_id sets do not match")

    companies: list[dict[str, Any]] = []
    method_counts = {name: {"prepared": 0, "blocked": 0} for name in FORMULA_VERSIONS}
    blocked_records: list[dict[str, Any]] = []
    invalid_records: list[dict[str, Any]] = []

    for company_id in sorted(input_by_id):
        company = input_by_id[company_id]
        eligibility_company = eligibility_by_id[company_id]
        methods = eligibility_company.get("methods") if isinstance(eligibility_company.get("methods"), Mapping) else {}
        outputs: dict[str, Any] = {}
        prepared_count = 0
        for method, formula_version in FORMULA_VERSIONS.items():
            eligibility_method = methods.get(method) if isinstance(methods.get(method), Mapping) else None
            if eligibility_method is None:
                raise ValuationMethodInputsError(f"missing eligibility method {method} for {company_id}")
            if eligibility_method.get("status") != "eligible":
                method_counts[method]["blocked"] += 1
                outputs[method] = {
                    "status": "blocked",
                    "confidence": "none",
                    "formula_version": formula_version,
                    "reason": eligibility_method.get("reason"),
                    "missing_inputs": eligibility_method.get("missing_inputs", []),
                    "invalid_inputs": eligibility_method.get("invalid_inputs", []),
                    "stale_inputs": eligibility_method.get("stale_inputs", []),
                    "raw_inputs": {},
                    "derived_inputs": {},
                }
                blocked_records.append({
                    "company_id": company_id,
                    "symbol": company.get("primary_symbol"),
                    "method": method,
                    "reason": eligibility_method.get("reason"),
                })
                continue

            raw_inputs, derived_inputs = _calculation(method, company)
            if any(value is None for value in derived_inputs.values()):
                invalid_records.append({
                    "company_id": company_id,
                    "symbol": company.get("primary_symbol"),
                    "method": method,
                    "reason": "derived_input_calculation_failed",
                })
                outputs[method] = {
                    "status": "invalid",
                    "confidence": "none",
                    "formula_version": formula_version,
                    "reason": "derived_input_calculation_failed",
                    "raw_inputs": raw_inputs,
                    "derived_inputs": derived_inputs,
                }
                continue
            prepared_count += 1
            method_counts[method]["prepared"] += 1
            outputs[method] = {
                "status": "prepared",
                "confidence": eligibility_method.get("confidence"),
                "formula_version": formula_version,
                "reason": "eligible_inputs_normalized",
                "stale_inputs": eligibility_method.get("stale_inputs", []),
                "raw_inputs": raw_inputs,
                "derived_inputs": derived_inputs,
            }

        if prepared_count == len(FORMULA_VERSIONS):
            state = "fully_prepared"
        elif prepared_count:
            state = "partially_prepared"
        else:
            state = "not_prepared"
        companies.append({
            "company_id": company_id,
            "cik": company.get("cik"),
            "primary_symbol": company.get("primary_symbol"),
            "display_name": company.get("display_name"),
            "input_state": company.get("input_state"),
            "method_input_state": state,
            "prepared_method_count": prepared_count,
            "total_method_count": len(FORMULA_VERSIONS),
            "methods": outputs,
        })

    state_counts: dict[str, int] = {}
    for row in companies:
        state_counts[row["method_input_state"]] = state_counts.get(row["method_input_state"], 0) + 1
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "valuation-method-inputs.v030.12.2",
        "version": "V030.12.2",
        "generated_at": generated_at,
        "as_of_date": snapshot.get("as_of_date"),
        "sources": {
            "valuation_input_path": input_path,
            "valuation_input_schema_version": snapshot.get("schema_version"),
            "eligibility_path": eligibility_path,
            "eligibility_schema_version": eligibility.get("schema_version"),
        },
        "summary": {
            "company_count": len(companies),
            "method_count": len(FORMULA_VERSIONS),
            "company_state_counts": dict(sorted(state_counts.items())),
            "method_input_counts": method_counts,
            "prepared_method_record_count": sum(v["prepared"] for v in method_counts.values()),
            "blocked_method_record_count": len(blocked_records),
            "invalid_method_record_count": len(invalid_records),
        },
        "companies": companies,
        "indexes": {
            "company_id_to_position": {row["company_id"]: i for i, row in enumerate(companies)},
            "symbol_to_company_id": {row["primary_symbol"]: row["company_id"] for row in companies if row.get("primary_symbol")},
        },
        "diagnostics": {"blocked_methods": blocked_records, "invalid_methods": invalid_records},
    }


def write_valuation_method_inputs(report: Mapping[str, Any], output_path: Path, diagnostic_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    diagnostic = {
        "schema_version": "valuation-method-inputs-diagnostic.v030.12.2",
        "version": report["version"],
        "generated_at": report["generated_at"],
        "as_of_date": report.get("as_of_date"),
        "summary": report["summary"],
        **report["diagnostics"],
    }
    diagnostic_path.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
