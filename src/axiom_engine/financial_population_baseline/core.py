from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


class FinancialPopulationBaselineError(ValueError):
    pass


_ALLOWED_PERIODS = {"FY", "Q1", "Q2", "Q3", "Q4", "TTM"}
_STATEMENT_ALIASES = {
    "income": "income",
    "income_statement": "income",
    "income statement": "income",
    "profit_and_loss": "income",
    "balance": "balance",
    "balance_sheet": "balance",
    "balance sheet": "balance",
    "cash_flow": "cash_flow",
    "cashflow": "cash_flow",
    "cash_flow_statement": "cash_flow",
    "cash flow": "cash_flow",
    "per_share": "per_share",
    "per share": "per_share",
    "supplemental": "supplemental",
    "other": "supplemental",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FinancialPopulationBaselineError(f"cannot read {path}: {exc}") from exc


def _list(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in keys:
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def _registry_root(population_dir: Path) -> Path:
    for candidate in (population_dir / "registry", population_dir / "registry_source", population_dir):
        if (candidate / "companies.json").exists():
            return candidate
    raise FinancialPopulationBaselineError(f"registry companies.json not found under {population_dir}")


def _diag(severity: str, code: str, row: int, **details: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "row": row, **details}


def _decimal(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return format(number, "f")


def _iso_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if len(text) >= 10:
        text = text[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _fiscal_year(raw: dict[str, Any], period_end: str | None, filed_at: str | None) -> int | None:
    value = raw.get("fiscal_year")
    try:
        year = int(value)
        if 1800 <= year <= 2200:
            return year
    except (TypeError, ValueError):
        pass
    for candidate in (period_end, filed_at):
        if candidate:
            return int(candidate[:4])
    return None


def _period(raw: dict[str, Any]) -> str:
    value = str(raw.get("fiscal_period") or raw.get("period_type") or raw.get("fp") or "FY").strip().upper()
    aliases = {"ANNUAL": "FY", "YEAR": "FY", "YEARLY": "FY", "QUARTER": "Q1", "QUARTERLY": "Q1"}
    return aliases.get(value, value) if aliases.get(value, value) in _ALLOWED_PERIODS else "FY"


def _statement(raw: dict[str, Any]) -> str:
    value = str(raw.get("statement") or raw.get("statement_type") or "supplemental").strip().lower()
    return _STATEMENT_ALIASES.get(value, "supplemental")


def _unit_currency(raw: dict[str, Any]) -> tuple[str, str | None]:
    unit = str(raw.get("unit") or "NUMBER").strip().upper()
    currency = str(raw.get("currency") or "").strip().upper() or None
    if unit in {"USD", "EUR", "JPY", "GBP", "CAD", "AUD", "TWD", "CNY", "HKD"}:
        return "CURRENCY", unit
    if unit in {"DOLLAR", "DOLLARS", "MONETARY"}:
        return "CURRENCY", currency or "USD"
    if unit == "CURRENCY":
        return unit, currency or "USD"
    if unit in {"SHARE", "SHARES"}:
        return "SHARES", currency
    if unit in {"PURE", "RATIO", "PERCENT", "PERCENTAGE", "NUMBER", "COUNT"}:
        return "NUMBER", currency
    return unit or "NUMBER", currency


def _source_provenance(path: str) -> dict[str, Any]:
    pid = "provenance:financial_population:" + hashlib.sha256(path.encode("utf-8")).hexdigest()[:20]
    return {
        "provenance_id": pid,
        "provider": "existing_financial_source",
        "source_type": "repository_json",
        "source_path": path,
        "retrieved_at": _now(),
        "metadata": {"population_version": "V030.1-hotfix1"},
    }


def _normalize_fact(
    raw: dict[str, Any], company_ids: set[str], idx: int, provenance_id: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    diagnostics: list[dict[str, Any]] = []
    company_id = str(raw.get("company_id") or "").strip()
    if not company_id or company_id not in company_ids:
        return None, [_diag("warning", "rejected_invalid_company_link", idx, company_id=company_id or None)]

    concept = str(raw.get("concept") or raw.get("metric") or raw.get("canonical_metric") or "").strip()
    if not concept:
        return None, [_diag("warning", "rejected_missing_concept", idx, company_id=company_id)]

    value = _decimal(raw.get("value"))
    if value is None:
        return None, [_diag("warning", "rejected_invalid_numeric_value", idx, company_id=company_id, concept=concept)]

    period_start = _iso_date(raw.get("period_start") or raw.get("start"))
    period_end = _iso_date(raw.get("period_end") or raw.get("end") or raw.get("as_of"))
    filed_at = _iso_date(raw.get("filed_at") or raw.get("filed") or raw.get("filing_date"))
    fiscal_year = _fiscal_year(raw, period_end, filed_at)
    if fiscal_year is None:
        return None, [_diag("warning", "rejected_missing_fiscal_year", idx, company_id=company_id, concept=concept)]
    if period_start and period_end and period_start > period_end:
        diagnostics.append(_diag("warning", "period_start_removed_after_end", idx, company_id=company_id, concept=concept))
        period_start = None

    fiscal_period = _period(raw)
    statement = _statement(raw)
    unit, currency = _unit_currency(raw)
    natural_identity = "|".join(
        map(str, [company_id, concept, fiscal_year, fiscal_period, period_end, unit, currency])
    )
    fact = {
        "fact_id": "financial_fact:" + hashlib.sha256(natural_identity.encode("utf-8")).hexdigest()[:24],
        "company_id": company_id,
        "statement": statement,
        "concept": concept,
        "value": value,
        "unit": unit,
        "currency": currency,
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "period_start": period_start,
        "period_end": period_end,
        "filed_at": filed_at,
        "taxonomy": str(raw.get("taxonomy") or "").strip() or None,
        "source_concept": str(raw.get("source_concept") or raw.get("metric") or "").strip() or None,
        "form": raw.get("form"),
        "audited": bool(raw.get("audited", False)),
        "provenance_ids": [provenance_id],
        "metadata": {**(raw.get("metadata") or {}), "population_normalized": True},
    }
    return fact, diagnostics


def build_financial_population_baseline(
    *,
    population_dir: str | Path = "data/universe",
    source_dir: str | Path = "data/onboarding/generated",
    output_dir: str | Path = "data/financial_population_baseline",
    write: bool = False,
    strict: bool = False,
) -> dict[str, Any]:
    population = Path(population_dir)
    source = Path(source_dir)
    output = Path(output_dir)
    registry = _registry_root(population)
    companies = _list(_load(registry / "companies.json"), ("companies",))
    company_ids = {str(row.get("company_id")) for row in companies if row.get("company_id")}
    if not company_ids:
        raise FinancialPopulationBaselineError("population registry contains no companies")
    if not source.exists():
        raise FinancialPopulationBaselineError(f"source directory not found: {source}")

    inputs: list[tuple[dict[str, Any], str, str]] = []
    provenance_by_id: dict[str, dict[str, Any]] = {}
    for path in sorted(source.rglob("*.json")):
        try:
            payload = _load(path)
        except FinancialPopulationBaselineError:
            continue
        rows = _list(payload, ("financial_facts", "facts", "data"))
        if not rows or not any(
            "company_id" in row and ("concept" in row or "metric" in row or "canonical_metric" in row)
            for row in rows
        ):
            continue
        provenance = _source_provenance(str(path))
        provenance_by_id[provenance["provenance_id"]] = provenance
        inputs.extend((row, str(path), provenance["provenance_id"]) for row in rows)

    diagnostics: list[dict[str, Any]] = []
    by_natural_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for index, (raw, path, provenance_id) in enumerate(inputs):
        fact, row_diagnostics = _normalize_fact(raw, company_ids, index, provenance_id)
        for item in row_diagnostics:
            item["source"] = path
        diagnostics.extend(row_diagnostics)
        if fact is None:
            continue
        key = (
            fact["company_id"], fact["concept"], fact["fiscal_year"], fact["fiscal_period"],
            fact["period_end"], fact["unit"], fact["currency"],
        )
        existing = by_natural_key.get(key)
        if existing is not None:
            diagnostics.append(_diag("warning", "duplicate_financial_period_skipped", index, source=path, fact_id=fact["fact_id"]))
            continue
        by_natural_key[key] = fact

    facts = sorted(
        by_natural_key.values(),
        key=lambda row: (row["company_id"], row["concept"], -row["fiscal_year"], row["fiscal_period"], str(row["period_end"])),
    )
    covered = {row["company_id"] for row in facts}
    missing = sorted(company_ids - covered)
    per_company = {
        company_id: {
            "company_id": company_id,
            "fact_count": 0,
            "concept_count": 0,
            "fiscal_year_min": None,
            "fiscal_year_max": None,
            "covered": False,
        }
        for company_id in company_ids
    }
    concepts: dict[str, set[str]] = {}
    years: dict[str, set[int]] = {}
    for fact in facts:
        company_id = fact["company_id"]
        per_company[company_id]["fact_count"] += 1
        concepts.setdefault(company_id, set()).add(fact["concept"])
        years.setdefault(company_id, set()).add(fact["fiscal_year"])
    for company_id in company_ids:
        company_years = sorted(years.get(company_id, set()))
        per_company[company_id]["concept_count"] = len(concepts.get(company_id, set()))
        per_company[company_id]["fiscal_year_min"] = company_years[0] if company_years else None
        per_company[company_id]["fiscal_year_max"] = company_years[-1] if company_years else None
        per_company[company_id]["covered"] = company_id in covered

    errors = sum(item["severity"] == "error" for item in diagnostics)
    warnings = sum(item["severity"] == "warning" for item in diagnostics)
    rejected = sum(str(item.get("code", "")).startswith("rejected_") for item in diagnostics)
    valid = errors == 0
    if strict and not valid:
        raise FinancialPopulationBaselineError(f"financial population baseline has {errors} errors")

    manifest = {
        "schema_version": "1.0.0",
        "financial_population_version": "V030.1-hotfix1",
        "generated_at": _now(),
        "population_dir": str(population),
        "source_dir": str(source),
        "universe_company_count": len(company_ids),
        "covered_company_count": len(covered),
        "missing_company_count": len(missing),
        "coverage_pct": round(len(covered) * 100 / len(company_ids), 4),
        "fact_count": len(facts),
        "rejected_fact_count": rejected,
        "errors": errors,
        "warnings": warnings,
        "valid": valid,
        "production_financial_compatible": True,
        "files": [
            "financial_source/financial_facts.json", "financial_source/provenance.json",
            "financial_coverage.json", "missing_companies.json",
            "financial_population_diagnostics.json", "financial_population_manifest.json",
        ],
    }
    if write:
        (output / "financial_source").mkdir(parents=True, exist_ok=True)
        payloads = {
            "financial_source/financial_facts.json": facts,
            "financial_source/provenance.json": sorted(provenance_by_id.values(), key=lambda row: row["provenance_id"]),
            "financial_coverage.json": sorted(per_company.values(), key=lambda row: row["company_id"]),
            "missing_companies.json": [{"company_id": company_id} for company_id in missing],
            "financial_population_diagnostics.json": diagnostics,
            "financial_population_manifest.json": manifest,
        }
        for name, payload in payloads.items():
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**manifest, "output_dir": str(output), "dry_run": not write}


def validate_financial_population_baseline(
    *, output_dir: str | Path = "data/financial_population_baseline",
    population_dir: str | Path | None = "data/universe",
) -> dict[str, Any]:
    root = Path(output_dir)
    required = [
        "financial_source/financial_facts.json", "financial_source/provenance.json",
        "financial_coverage.json", "missing_companies.json", "financial_population_manifest.json",
    ]
    errors = [f"missing file: {name}" for name in required if not (root / name).exists()]
    if errors:
        return {"valid": False, "errors": errors, "output_dir": str(root)}
    facts = _list(_load(root / "financial_source/financial_facts.json"), ("financial_facts",))
    provenance = _list(_load(root / "financial_source/provenance.json"), ("provenance",))
    coverage = _list(_load(root / "financial_coverage.json"), ("coverage",))
    missing = _list(_load(root / "missing_companies.json"), ("missing_companies",))
    manifest = _load(root / "financial_population_manifest.json")
    coverage_ids = {row.get("company_id") for row in coverage}
    fact_company_ids = {row.get("company_id") for row in facts}
    missing_ids = {row.get("company_id") for row in missing}
    provenance_ids = {row.get("provenance_id") for row in provenance}
    if fact_company_ids & missing_ids:
        errors.append("covered and missing company sets overlap")
    if len(coverage) != manifest.get("universe_company_count"):
        errors.append("coverage row count does not match manifest")
    if len(fact_company_ids) != manifest.get("covered_company_count"):
        errors.append("covered company count does not match manifest")
    if len(missing_ids) != manifest.get("missing_company_count"):
        errors.append("missing company count does not match manifest")
    if any(not set(row.get("provenance_ids") or []).issubset(provenance_ids) for row in facts):
        errors.append("financial facts contain invalid provenance links")
    natural_keys = [
        (row.get("company_id"), row.get("concept"), row.get("fiscal_year"), row.get("fiscal_period"), row.get("period_end"), row.get("unit"), row.get("currency"))
        for row in facts
    ]
    if len(natural_keys) != len(set(natural_keys)):
        errors.append("duplicate canonical financial period keys")
    if population_dir is not None:
        population_ids = {
            row.get("company_id")
            for row in _list(_load(_registry_root(Path(population_dir)) / "companies.json"), ("companies",))
        }
        if coverage_ids != population_ids:
            errors.append("coverage company set does not match population registry")
    return {
        "valid": not errors,
        "errors": errors,
        "universe_company_count": len(coverage),
        "covered_company_count": len(fact_company_ids),
        "missing_company_count": len(missing_ids),
        "fact_count": len(facts),
        "output_dir": str(root),
    }
