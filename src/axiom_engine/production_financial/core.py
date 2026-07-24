from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


class ProductionFinancialError(ValueError):
    """Raised when production financial input cannot be imported safely."""


_ALLOWED_PERIODS = {"FY", "Q1", "Q2", "Q3", "Q4", "TTM"}
_ALLOWED_STATEMENTS = {"income", "balance", "cash_flow", "per_share", "supplemental"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionFinancialError(f"cannot read JSON source {path}: {exc}") from exc


def _rows(source_dir: Path, name: str) -> list[dict[str, Any]]:
    path = source_dir / name
    key = name.removesuffix(".json")
    candidates = [path] if path.exists() else sorted(source_dir.glob("*.json"))
    for candidate in candidates:
        payload = _load(candidate)
        if candidate == path and isinstance(payload, list):
            return payload
        rows = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(rows, list):
            return rows
    return []


def _diag(severity: str, code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, "details": details}


def _decimal(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProductionFinancialError(f"invalid numeric value: {value!r}") from exc
    if not number.is_finite():
        raise ProductionFinancialError(f"non-finite numeric value: {value!r}")
    return format(number, "f")


def _iso_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ProductionFinancialError(f"invalid ISO date: {value!r}") from exc


def _fact_id(row: dict[str, Any]) -> str:
    existing = str(row.get("fact_id") or "").strip()
    if existing:
        return existing
    identity = "|".join(
        str(row.get(key) or "")
        for key in ("company_id", "concept", "fiscal_year", "fiscal_period", "period_end", "unit")
    )
    return "financial_fact:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _registry_company_ids(registry_dir: Path | None) -> set[str] | None:
    if registry_dir is None:
        return None
    path = registry_dir / "companies.json"
    if not path.exists():
        raise ProductionFinancialError(f"registry companies file not found: {path}")
    payload = _load(path)
    if not isinstance(payload, list):
        raise ProductionFinancialError("registry companies.json must be a list")
    return {str(row.get("company_id")) for row in payload if row.get("company_id")}


def build_production_financials(
    *,
    source_dir: str | Path,
    output_dir: str | Path = "data/financials",
    registry_dir: str | Path | None = "data/company_registry",
    write: bool = False,
    strict: bool = False,
) -> dict[str, Any]:
    source = Path(source_dir)
    if not source.is_dir():
        raise ProductionFinancialError(f"source directory not found: {source}")

    facts_in = _rows(source, "financial_facts.json")
    provenance_in = _rows(source, "provenance.json")
    if not facts_in:
        raise ProductionFinancialError("financial_facts.json contains no facts")

    registry_path = Path(registry_dir) if registry_dir is not None else None
    company_ids = _registry_company_ids(registry_path)
    provenance_ids = {str(row.get("provenance_id")) for row in provenance_in if row.get("provenance_id")}
    diagnostics: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    natural_keys: Counter[tuple[Any, ...]] = Counter()

    for index, raw in enumerate(facts_in):
        company_id = str(raw.get("company_id") or "").strip()
        concept = str(raw.get("concept") or "").strip()
        statement = str(raw.get("statement") or "").strip().lower()
        fiscal_period = str(raw.get("fiscal_period") or "FY").strip().upper()
        unit = str(raw.get("unit") or "").strip().upper()
        currency = str(raw.get("currency") or "").strip().upper() or None
        taxonomy = str(raw.get("taxonomy") or "").strip() or None
        source_concept = str(raw.get("source_concept") or "").strip() or None
        fiscal_year = raw.get("fiscal_year")

        try:
            fiscal_year = int(fiscal_year)
        except (TypeError, ValueError):
            diagnostics.append(_diag("error", "invalid_fiscal_year", "Fiscal year must be an integer", row=index))
            fiscal_year = None

        if not company_id:
            diagnostics.append(_diag("error", "missing_company_id", "Financial fact has no company_id", row=index))
        elif company_ids is not None and company_id not in company_ids:
            diagnostics.append(_diag("error", "invalid_company_link", "Financial fact references unknown company", row=index, company_id=company_id))
        if not concept:
            diagnostics.append(_diag("error", "missing_concept", "Financial fact has no canonical concept", row=index))
        if statement not in _ALLOWED_STATEMENTS:
            diagnostics.append(_diag("error", "invalid_statement", "Unsupported financial statement", row=index, statement=statement))
        if fiscal_period not in _ALLOWED_PERIODS:
            diagnostics.append(_diag("error", "invalid_fiscal_period", "Unsupported fiscal period", row=index, fiscal_period=fiscal_period))
        if not unit:
            diagnostics.append(_diag("error", "missing_unit", "Financial fact has no unit", row=index))
        if unit == "CURRENCY" and not currency:
            diagnostics.append(_diag("error", "missing_currency", "Currency fact has no currency code", row=index))

        try:
            value = _decimal(raw.get("value"))
            period_start = _iso_date(raw.get("period_start"))
            period_end = _iso_date(raw.get("period_end"))
            filed_at = _iso_date(raw.get("filed_at"))
        except ProductionFinancialError as exc:
            diagnostics.append(_diag("error", "invalid_fact_value", str(exc), row=index))
            value, period_start, period_end, filed_at = None, None, None, None

        if value is None:
            diagnostics.append(_diag("error", "missing_value", "Financial fact has no numeric value", row=index))
        if period_start and period_end and period_start > period_end:
            diagnostics.append(_diag("error", "invalid_period_range", "period_start is after period_end", row=index))

        pids = sorted(set(map(str, raw.get("provenance_ids") or [])))
        if not pids:
            diagnostics.append(_diag("warning", "missing_provenance", "Financial fact has no provenance", row=index))
        unknown = [pid for pid in pids if pid not in provenance_ids]
        if unknown:
            diagnostics.append(_diag("error", "invalid_provenance", "Financial fact references unknown provenance", row=index, provenance_ids=unknown))

        normalized = {
            "fact_id": _fact_id(raw),
            "company_id": company_id or None,
            "statement": statement or None,
            "concept": concept or None,
            "value": value,
            "unit": unit or None,
            "currency": currency,
            "fiscal_year": fiscal_year,
            "fiscal_period": fiscal_period,
            "period_start": period_start,
            "period_end": period_end,
            "filed_at": filed_at,
            "taxonomy": taxonomy,
            "source_concept": source_concept,
            "form": raw.get("form"),
            "audited": bool(raw.get("audited", False)),
            "provenance_ids": pids,
            "metadata": raw.get("metadata") or {},
        }
        if normalized["fact_id"] in seen_ids:
            diagnostics.append(_diag("error", "duplicate_fact_id", "Duplicate financial fact id", fact_id=normalized["fact_id"]))
        seen_ids.add(normalized["fact_id"])
        natural_key = (company_id, concept, fiscal_year, fiscal_period, period_end, unit, currency)
        natural_keys[natural_key] += 1
        facts.append(normalized)

    for key, count in natural_keys.items():
        if count > 1:
            diagnostics.append(_diag("error", "duplicate_financial_period", "Multiple facts share the same canonical period key", key=list(key), count=count))

    facts.sort(key=lambda row: (str(row["company_id"]), str(row["concept"]), -(row["fiscal_year"] or 0), str(row["fiscal_period"]), str(row["period_end"])))
    errors = sum(item["severity"] == "error" for item in diagnostics)
    warnings = sum(item["severity"] == "warning" for item in diagnostics)
    valid = errors == 0
    if strict and not valid:
        raise ProductionFinancialError(f"financial import has {errors} validation errors")

    companies = len({row["company_id"] for row in facts if row["company_id"]})
    years = sorted({row["fiscal_year"] for row in facts if row["fiscal_year"] is not None})
    manifest = {
        "schema_version": "1.0.0",
        "financial_version": "V028.1",
        "generated_at": _now(),
        "source_dir": str(source),
        "registry_dir": str(registry_path) if registry_path is not None else None,
        "fact_count": len(facts),
        "company_count": companies,
        "fiscal_year_min": min(years) if years else None,
        "fiscal_year_max": max(years) if years else None,
        "errors": errors,
        "warnings": warnings,
        "valid": valid,
        "files": ["financial_facts.json", "provenance.json", "financial_diagnostics.json", "financial_manifest.json"],
    }
    out = Path(output_dir)
    if write:
        out.mkdir(parents=True, exist_ok=True)
        for name, payload in (
            ("financial_facts.json", facts),
            ("provenance.json", provenance_in),
            ("financial_diagnostics.json", diagnostics),
            ("financial_manifest.json", manifest),
        ):
            (out / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**manifest, "output_dir": str(out), "dry_run": not write}


def validate_production_financials(*, output_dir: str | Path = "data/financials", registry_dir: str | Path | None = "data/company_registry") -> dict[str, Any]:
    root = Path(output_dir)
    required = ["financial_facts.json", "provenance.json", "financial_diagnostics.json", "financial_manifest.json"]
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        return {"valid": False, "errors": [f"missing file: {name}" for name in missing], "output_dir": str(root)}

    facts = _load(root / "financial_facts.json")
    diagnostics = _load(root / "financial_diagnostics.json")
    manifest = _load(root / "financial_manifest.json")
    if not isinstance(facts, list) or not isinstance(diagnostics, list) or not isinstance(manifest, dict):
        return {"valid": False, "errors": ["invalid_output_shape"], "output_dir": str(root)}

    company_ids = _registry_company_ids(Path(registry_dir) if registry_dir is not None else None)
    invalid_links = [] if company_ids is None else [row.get("fact_id") for row in facts if row.get("company_id") not in company_ids]
    fact_ids = [row.get("fact_id") for row in facts]
    duplicate_ids = sorted(key for key, count in Counter(fact_ids).items() if key and count > 1)
    diagnostic_errors = [item.get("code") for item in diagnostics if item.get("severity") == "error"]
    manifest_mismatch = manifest.get("fact_count") != len(facts) or manifest.get("company_count") != len({row.get("company_id") for row in facts if row.get("company_id")})
    errors = diagnostic_errors[:]
    if invalid_links:
        errors.append("invalid_company_links")
    if duplicate_ids:
        errors.append("duplicate_fact_ids")
    if manifest_mismatch:
        errors.append("manifest_mismatch")
    return {
        "valid": not errors,
        "errors": errors,
        "fact_count": len(facts),
        "company_count": len({row.get("company_id") for row in facts if row.get("company_id")}),
        "invalid_company_links": invalid_links,
        "duplicate_fact_ids": duplicate_ids,
        "output_dir": str(root),
    }
