from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping


class ValuationEngineError(RuntimeError):
    pass


ENGINE_FORMULA_VERSIONS = {
    "forward_pe": "forward-pe-engine.v1",
    "trailing_pe": "trailing-pe-engine.v1",
    "price_to_sales": "price-to-sales-engine.v1",
    "ev_to_sales": "ev-to-sales-engine.v1",
    "ev_to_ebitda": "ev-to-ebitda-engine.v1",
    "fcf_yield": "fcf-yield-engine.v1",
    "dcf": "dcf-base-engine.v1",
}


def _load(path: Path) -> Any:
    if not path.exists():
        raise ValuationEngineError(f"valuation method inputs not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValuationEngineError(f"valuation method inputs is not valid JSON: {path}") from exc


def _number(value: Any) -> int | float | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return int(number) if number == number.to_integral_value() else float(number)


def _engine_metrics(method: str, derived: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "forward_pe": ("current_multiple",),
        "trailing_pe": ("current_multiple",),
        "price_to_sales": ("revenue_per_share", "current_multiple"),
        "ev_to_sales": ("current_multiple",),
        "ev_to_ebitda": ("current_multiple",),
        "fcf_yield": ("current_yield", "current_yield_percent"),
        "dcf": ("free_cash_flow_per_share", "revenue_per_share", "current_price"),
    }[method]
    return {name: _number(derived.get(name)) for name in expected}


def build_valuation_engine(
    repository_root: Path,
    *,
    input_path: str = "data/generated/valuation_method_inputs/valuation_method_inputs.json",
) -> dict[str, Any]:
    source = _load(repository_root / input_path)
    if not isinstance(source, Mapping) or not str(source.get("schema_version") or "").startswith("valuation-method-inputs."):
        raise ValuationEngineError("unsupported valuation method inputs schema")
    companies_source = source.get("companies")
    if not isinstance(companies_source, list) or not companies_source:
        raise ValuationEngineError("valuation method inputs must contain a non-empty companies array")

    companies: list[dict[str, Any]] = []
    counts = {name: {"calculated": 0, "blocked": 0, "invalid": 0} for name in ENGINE_FORMULA_VERSIONS}
    blocked_records: list[dict[str, Any]] = []
    invalid_records: list[dict[str, Any]] = []

    for company in companies_source:
        if not isinstance(company, Mapping) or not company.get("company_id"):
            raise ValuationEngineError("every company must have company_id")
        source_methods = company.get("methods") if isinstance(company.get("methods"), Mapping) else {}
        methods: dict[str, Any] = {}
        calculated_count = 0
        for method, engine_version in ENGINE_FORMULA_VERSIONS.items():
            source_method = source_methods.get(method)
            if not isinstance(source_method, Mapping):
                raise ValuationEngineError(f"missing method {method} for {company['company_id']}")
            status = source_method.get("status")
            if status == "blocked":
                counts[method]["blocked"] += 1
                methods[method] = {
                    "status": "blocked",
                    "confidence": "none",
                    "formula_version": engine_version,
                    "source_formula_version": source_method.get("formula_version"),
                    "reason": source_method.get("reason"),
                    "inputs": {},
                    "metrics": {},
                }
                blocked_records.append({
                    "company_id": company["company_id"],
                    "symbol": company.get("primary_symbol"),
                    "method": method,
                    "reason": source_method.get("reason"),
                })
                continue
            if status != "prepared":
                counts[method]["invalid"] += 1
                invalid_records.append({
                    "company_id": company["company_id"],
                    "symbol": company.get("primary_symbol"),
                    "method": method,
                    "reason": "source_method_not_prepared_or_blocked",
                })
                methods[method] = {
                    "status": "invalid", "confidence": "none", "formula_version": engine_version,
                    "source_formula_version": source_method.get("formula_version"),
                    "reason": "source_method_not_prepared_or_blocked", "inputs": {}, "metrics": {},
                }
                continue

            raw_inputs = source_method.get("raw_inputs") if isinstance(source_method.get("raw_inputs"), Mapping) else {}
            derived = source_method.get("derived_inputs") if isinstance(source_method.get("derived_inputs"), Mapping) else {}
            metrics = _engine_metrics(method, derived)
            if not raw_inputs or any(value is None for value in metrics.values()):
                counts[method]["invalid"] += 1
                invalid_records.append({
                    "company_id": company["company_id"], "symbol": company.get("primary_symbol"),
                    "method": method, "reason": "engine_payload_incomplete",
                })
                methods[method] = {
                    "status": "invalid", "confidence": "none", "formula_version": engine_version,
                    "source_formula_version": source_method.get("formula_version"),
                    "reason": "engine_payload_incomplete", "inputs": dict(raw_inputs), "metrics": metrics,
                }
                continue

            calculated_count += 1
            counts[method]["calculated"] += 1
            methods[method] = {
                "status": "calculated",
                "confidence": source_method.get("confidence"),
                "formula_version": engine_version,
                "source_formula_version": source_method.get("formula_version"),
                "reason": "prepared_inputs_promoted_to_engine_payload",
                "stale_inputs": source_method.get("stale_inputs", []),
                "inputs": dict(raw_inputs),
                "metrics": metrics,
            }

        total = len(ENGINE_FORMULA_VERSIONS)
        state = "fully_calculated" if calculated_count == total else "partially_calculated" if calculated_count else "not_calculated"
        companies.append({
            "company_id": company["company_id"], "cik": company.get("cik"),
            "primary_symbol": company.get("primary_symbol"), "display_name": company.get("display_name"),
            "engine_state": state, "calculated_method_count": calculated_count,
            "total_method_count": total, "methods": methods,
        })

    state_counts: dict[str, int] = {}
    for company in companies:
        state_counts[company["engine_state"]] = state_counts.get(company["engine_state"], 0) + 1
    return {
        "schema_version": "valuation-engine-snapshot.v030.13.0",
        "version": "V030.13.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of_date": source.get("as_of_date"),
        "sources": {"method_inputs_path": input_path, "method_inputs_schema_version": source.get("schema_version")},
        "summary": {
            "company_count": len(companies), "method_count": len(ENGINE_FORMULA_VERSIONS),
            "company_state_counts": dict(sorted(state_counts.items())), "method_engine_counts": counts,
            "calculated_method_record_count": sum(v["calculated"] for v in counts.values()),
            "blocked_method_record_count": len(blocked_records),
            "invalid_method_record_count": len(invalid_records),
        },
        "companies": companies,
        "indexes": {
            "company_id_to_position": {row["company_id"]: i for i, row in enumerate(companies)},
            "symbol_to_company_id": {row["primary_symbol"]: row["company_id"] for row in companies if row.get("primary_symbol")},
        },
        "diagnostic": {"blocked_methods": blocked_records, "invalid_methods": invalid_records},
    }


def write_valuation_engine(report: Mapping[str, Any], output: Path, diagnostic: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    diagnostic.parent.mkdir(parents=True, exist_ok=True)
    clean = dict(report)
    diag = clean.pop("diagnostic")
    output.write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    diagnostic.write_text(json.dumps({
        "schema_version": "valuation-engine-diagnostic.v030.13.0", "version": "V030.13.0",
        "generated_at": report.get("generated_at"), **diag,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
