from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


class FinancialBridgeError(RuntimeError):
    """Raised when canonical financial bridge input is structurally invalid."""


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not number.is_finite():
        return None
    if number == number.to_integral_value():
        return int(number)
    result = float(number)
    return result if math.isfinite(result) else None


def _identity_indexes(payload: Any) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    if not isinstance(payload, dict):
        return {}, {}
    records = payload.get("records") or []
    by_company = {
        str(row["company_id"]): row
        for row in records
        if isinstance(row, dict) and row.get("company_id")
    }
    cik_index = {
        str(k): str(v)
        for k, v in ((payload.get("indexes") or {}).get("cik_to_company_id") or {}).items()
    }
    return by_company, cik_index


def _fact_sort_key(row: dict[str, Any]) -> tuple[str, int, int, str]:
    form_priority = {"10-K": 3, "10-K/A": 2, "10-Q": 1}.get(str(row.get("form_type") or ""), 0)
    return (
        str(row.get("period_end") or ""),
        int(row.get("fiscal_year") or 0),
        1 if row.get("audited") is True else 0,
        f"{form_priority}:{row.get('accession_number') or ''}",
    )


def build_financial_bridge(
    repository_root: Path,
    *,
    financial_facts_path: str = "data/financial_data/financial_facts.json",
    identity_map_path: str = "data/generated/identity/company_identity_map.json",
) -> dict[str, Any]:
    facts = _load(repository_root / financial_facts_path, [])
    identity = _load(repository_root / identity_map_path, {})
    if not isinstance(facts, list):
        raise FinancialBridgeError("financial facts input must be a JSON array")
    identity_by_company, cik_to_company = _identity_indexes(identity)
    if not identity_by_company:
        raise FinancialBridgeError(
            "canonical identity map is missing or empty; run scripts/build_identity_mapping.py --write --strict"
        )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    invalid_rows: list[dict[str, Any]] = []
    unmapped_company_ids: set[str] = set()
    duplicate_fact_ids: list[str] = []
    seen_fact_ids: set[str] = set()

    for index, raw in enumerate(facts):
        if not isinstance(raw, dict):
            invalid_rows.append({"index": index, "reason": "not_object"})
            continue
        fact_id = str(raw.get("financial_fact_id") or "").strip()
        company_id = str(raw.get("company_id") or "").strip()
        metric = str(raw.get("metric") or "").strip()
        value = _number(raw.get("value"))
        if not fact_id or not company_id or not metric or value is None:
            invalid_rows.append({
                "index": index,
                "financial_fact_id": fact_id or None,
                "reason": "missing_required_field_or_invalid_value",
            })
            continue
        if fact_id in seen_fact_ids:
            duplicate_fact_ids.append(fact_id)
            continue
        seen_fact_ids.add(fact_id)

        identity_record = identity_by_company.get(company_id)
        if identity_record is None:
            metadata = raw.get("metadata") or {}
            cik = str(metadata.get("financial_facts_cik") or metadata.get("registry_cik") or "").zfill(10)
            mapped = cik_to_company.get(cik)
            if mapped:
                company_id = mapped
                identity_record = identity_by_company.get(company_id)
        if identity_record is None:
            unmapped_company_ids.add(company_id)
            continue

        grouped[company_id].append({
            "financial_fact_id": fact_id,
            "metric": metric,
            "value": value,
            "unit": raw.get("unit"),
            "currency": raw.get("currency"),
            "period_type": raw.get("period_type"),
            "period_start": raw.get("period_start"),
            "period_end": raw.get("period_end"),
            "fiscal_year": raw.get("fiscal_year"),
            "fiscal_period": raw.get("fiscal_period"),
            "statement": raw.get("statement"),
            "form_type": raw.get("form_type"),
            "accession_number": raw.get("accession_number"),
            "audited": bool(raw.get("audited")),
            "provenance_ids": list(raw.get("provenance_ids") or []),
            "source": {
                "provider": "sec_companyfacts",
                "source_type": "regulator_filing",
                "xbrl_tag": (raw.get("metadata") or {}).get("xbrl_tag"),
            },
        })

    companies: list[dict[str, Any]] = []
    metric_counts: Counter[str] = Counter()
    for company_id, company_facts in sorted(grouped.items()):
        identity_record = identity_by_company[company_id]
        by_metric: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for fact in company_facts:
            by_metric[fact["metric"]].append(fact)
            metric_counts[fact["metric"]] += 1
        latest_metrics = {
            metric: max(rows, key=_fact_sort_key)
            for metric, rows in sorted(by_metric.items())
        }
        periods = sorted({str(row.get("period_end")) for row in company_facts if row.get("period_end")})
        currencies = sorted({str(row.get("currency")) for row in company_facts if row.get("currency")})
        companies.append({
            "company_id": company_id,
            "cik": identity_record.get("cik"),
            "primary_symbol": identity_record.get("primary_symbol"),
            "display_name": identity_record.get("display_name"),
            "identity_state": identity_record.get("identity_state"),
            "currency": currencies[0] if len(currencies) == 1 else None,
            "currencies": currencies,
            "latest_period_end": periods[-1] if periods else None,
            "fact_count": len(company_facts),
            "metric_count": len(by_metric),
            "metrics": latest_metrics,
            "facts": sorted(company_facts, key=lambda row: (str(row.get("period_end") or ""), row["metric"], row["financial_fact_id"])),
            "bridge_state": "canonical",
        })

    generated_at = datetime.now(timezone.utc).isoformat()
    source_company_count = len({str(row.get("company_id")) for row in facts if isinstance(row, dict) and row.get("company_id")})
    output_fact_count = sum(row["fact_count"] for row in companies)
    return {
        "schema_version": "canonical-financial-snapshot.v030.11.0",
        "version": "V030.11.0",
        "generated_at": generated_at,
        "source": {
            "provider": "sec_companyfacts",
            "input_path": financial_facts_path,
            "identity_map_path": identity_map_path,
        },
        "summary": {
            "source_fact_count": len(facts),
            "canonical_fact_count": output_fact_count,
            "source_company_count": source_company_count,
            "canonical_company_count": len(companies),
            "unmapped_company_count": len(unmapped_company_ids),
            "unmapped_fact_count": len(facts) - output_fact_count - len(invalid_rows) - len(set(duplicate_fact_ids)),
            "invalid_row_count": len(invalid_rows),
            "duplicate_fact_id_count": len(set(duplicate_fact_ids)),
            "metric_counts": dict(sorted(metric_counts.items())),
        },
        "companies": companies,
        "indexes": {
            "company_id_to_position": {row["company_id"]: i for i, row in enumerate(companies)},
            "symbol_to_company_id": {
                row["primary_symbol"]: row["company_id"]
                for row in companies if row.get("primary_symbol")
            },
        },
        "diagnostics": {
            "unmapped_company_ids": sorted(unmapped_company_ids),
            "invalid_rows": invalid_rows,
            "duplicate_fact_ids": sorted(set(duplicate_fact_ids)),
        },
    }


def write_financial_bridge(report: dict[str, Any], output_path: Path, diagnostic_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    diagnostic_path.write_text(json.dumps({
        "schema_version": "financial-bridge-diagnostic.v030.11.0",
        "version": report["version"],
        "generated_at": report["generated_at"],
        "summary": report["summary"],
        **report["diagnostics"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
