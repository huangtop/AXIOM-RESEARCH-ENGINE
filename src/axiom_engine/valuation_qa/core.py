from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping


class ValuationQAError(RuntimeError):
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
        raise ValuationQAError(f"{label} not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValuationQAError(f"{label} is not valid JSON: {path}") from exc


def _number(value: Any) -> float | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return float(number)


def _close(actual: Any, expected: Any, tolerance: float) -> bool:
    a, e = _number(actual), _number(expected)
    if a is None or e is None:
        return False
    return math.isclose(a, e, rel_tol=tolerance, abs_tol=tolerance)


def _expected(method: str, raw: Mapping[str, Any]) -> dict[str, float | None]:
    values = {name: _number(payload.get("value")) if isinstance(payload, Mapping) else None for name, payload in raw.items()}

    def div(a: str, b: str) -> float | None:
        n, d = values.get(a), values.get(b)
        return None if n is None or d in (None, 0.0) else n / d

    if method == "forward_pe":
        return {"current_multiple": div("previous_close", "forward_eps")}
    if method == "trailing_pe":
        return {"current_multiple": div("previous_close", "trailing_eps")}
    if method == "price_to_sales":
        rps = div("revenue", "diluted_shares_outstanding")
        return {"revenue_per_share": rps, "current_multiple": None if rps in (None, 0.0) else values.get("previous_close") / rps}
    if method == "ev_to_sales":
        return {"current_multiple": div("enterprise_value", "revenue")}
    if method == "ev_to_ebitda":
        return {"current_multiple": div("enterprise_value", "ebitda")}
    if method == "fcf_yield":
        value = div("free_cash_flow", "market_cap")
        return {"current_yield": value, "current_yield_percent": None if value is None else value * 100.0}
    if method == "dcf":
        return {
            "free_cash_flow_per_share": div("free_cash_flow", "diluted_shares_outstanding"),
            "revenue_per_share": div("revenue", "diluted_shares_outstanding"),
            "current_price": values.get("previous_close"),
        }
    raise ValuationQAError(f"unsupported method: {method}")


def run_valuation_qa(
    repository_root: Path,
    *,
    eligibility_path: str = "data/generated/valuation_eligibility/valuation_method_eligibility.json",
    method_inputs_path: str = "data/generated/valuation_method_inputs/valuation_method_inputs.json",
    tolerance: float = 1e-8,
) -> dict[str, Any]:
    eligibility = _load(repository_root / eligibility_path, "valuation method eligibility")
    inputs = _load(repository_root / method_inputs_path, "valuation method inputs")
    if not isinstance(eligibility, Mapping) or not str(eligibility.get("schema_version") or "").startswith("valuation-method-eligibility."):
        raise ValuationQAError("unsupported valuation eligibility schema")
    if not isinstance(inputs, Mapping) or not str(inputs.get("schema_version") or "").startswith("valuation-method-inputs."):
        raise ValuationQAError("unsupported valuation method inputs schema")
    if not isinstance(eligibility.get("companies"), list) or not isinstance(inputs.get("companies"), list):
        raise ValuationQAError("both source snapshots must contain companies arrays")

    elig_by_id = {str(row.get("company_id")): row for row in eligibility["companies"] if isinstance(row, Mapping)}
    inputs_by_id = {str(row.get("company_id")): row for row in inputs["companies"] if isinstance(row, Mapping)}
    if set(elig_by_id) != set(inputs_by_id):
        raise ValuationQAError("eligibility and method input company_id sets do not match")

    issues: list[dict[str, Any]] = []
    checks = {"company": 0, "method": 0, "prepared_method": 0, "blocked_method": 0, "raw_input": 0, "derived_value": 0}

    def issue(gate: str, code: str, company_id: str, method: str | None = None, **detail: Any) -> None:
        row = {"severity": "critical", "gate": gate, "code": code, "company_id": company_id}
        if method is not None:
            row["method"] = method
        row.update(detail)
        issues.append(row)

    for company_id in sorted(elig_by_id):
        checks["company"] += 1
        e_company, i_company = elig_by_id[company_id], inputs_by_id[company_id]
        e_methods = e_company.get("methods") if isinstance(e_company.get("methods"), Mapping) else {}
        i_methods = i_company.get("methods") if isinstance(i_company.get("methods"), Mapping) else {}
        for method, formula_version in FORMULA_VERSIONS.items():
            checks["method"] += 1
            e = e_methods.get(method) if isinstance(e_methods.get(method), Mapping) else None
            i = i_methods.get(method) if isinstance(i_methods.get(method), Mapping) else None
            if e is None or i is None:
                issue("eligibility_consistency", "missing_method_record", company_id, method)
                continue
            expected_status = "prepared" if e.get("status") == "eligible" else "blocked"
            if i.get("status") != expected_status:
                issue("eligibility_consistency", "status_mismatch", company_id, method, expected=expected_status, actual=i.get("status"))
            if i.get("formula_version") != formula_version:
                issue("formula_integrity", "invalid_formula_version", company_id, method, expected=formula_version, actual=i.get("formula_version"))

            if expected_status == "blocked":
                checks["blocked_method"] += 1
                if i.get("raw_inputs") not in ({}, None) or i.get("derived_inputs") not in ({}, None):
                    issue("blocked_method_safety", "blocked_method_has_calculation", company_id, method)
                continue

            checks["prepared_method"] += 1
            if i.get("confidence") != e.get("confidence"):
                issue("confidence_propagation", "confidence_mismatch", company_id, method, expected=e.get("confidence"), actual=i.get("confidence"))
            raw = i.get("raw_inputs") if isinstance(i.get("raw_inputs"), Mapping) else {}
            derived = i.get("derived_inputs") if isinstance(i.get("derived_inputs"), Mapping) else {}
            for name, payload in raw.items():
                checks["raw_input"] += 1
                if not isinstance(payload, Mapping):
                    issue("provider_provenance", "invalid_raw_input", company_id, method, input=name)
                    continue
                for field in ("value", "provider", "confidence"):
                    if payload.get(field) is None:
                        issue("provider_provenance", "missing_provenance_field", company_id, method, input=name, field=field)
                provider = payload.get("provider")
                if provider not in {"sec_companyfacts", "yahoo_finance"}:
                    issue("provider_provenance", "invalid_provider", company_id, method, input=name, provider=provider)
                if provider == "sec_companyfacts" and not payload.get("source_fact_ids"):
                    issue("provider_provenance", "missing_sec_source_fact_ids", company_id, method, input=name)
                if provider == "yahoo_finance" and name != "previous_close" and not payload.get("source_field"):
                    issue("provider_provenance", "missing_yahoo_source_field", company_id, method, input=name)
            expected = _expected(method, raw)
            for name, value in expected.items():
                checks["derived_value"] += 1
                if value is None or not _close(derived.get(name), value, tolerance):
                    issue("derived_calculation", "derived_value_mismatch", company_id, method, field=name, expected=value, actual=derived.get(name))

    gates = {}
    for gate in ("eligibility_consistency", "formula_integrity", "derived_calculation", "provider_provenance", "confidence_propagation", "blocked_method_safety"):
        gates[gate] = "fail" if any(row["gate"] == gate for row in issues) else "pass"
    method_summary = inputs.get("summary") if isinstance(inputs.get("summary"), Mapping) else {}
    critical = len(issues)
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "valuation-qa-report.v030.12.3",
        "version": "V030.12.3",
        "generated_at": generated_at,
        "as_of_date": inputs.get("as_of_date"),
        "sources": {
            "eligibility_path": eligibility_path,
            "eligibility_schema_version": eligibility.get("schema_version"),
            "method_inputs_path": method_inputs_path,
            "method_inputs_schema_version": inputs.get("schema_version"),
        },
        "summary": {
            "status": "fail" if critical else "pass",
            "critical_issue_count": critical,
            "warning_issue_count": 0,
            "company_count": len(inputs_by_id),
            "method_count": len(FORMULA_VERSIONS),
            "method_record_count": checks["method"],
            "prepared_method_count": int(method_summary.get("prepared_method_record_count") or checks["prepared_method"]),
            "blocked_method_count": int(method_summary.get("blocked_method_record_count") or checks["blocked_method"]),
            "invalid_method_count": int(method_summary.get("invalid_method_record_count") or 0),
            "check_counts": checks,
            "issue_code_counts": {code: sum(1 for row in issues if row["code"] == code) for code in sorted({row["code"] for row in issues})},
        },
        "gates": gates,
        "issues": issues,
    }


def write_valuation_qa(report: Mapping[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
