from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


class ProductionMarketError(RuntimeError):
    """Raised when canonical production market import cannot complete."""


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ProductionMarketError(f"missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProductionMarketError(f"invalid JSON: {path}: {exc}") from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _diag(severity: str, code: str, message: str, **context: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, "context": context}


def _decimal(value: Any, field: str, diagnostics: list[dict[str, Any]], index: int, *, nonnegative: bool = False, positive: bool = False) -> str | None:
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        diagnostics.append(_diag("error", "invalid_decimal", f"{field} must be decimal-compatible", index=index, field=field, value=value))
        return None
    if not number.is_finite():
        diagnostics.append(_diag("error", "non_finite_decimal", f"{field} must be finite", index=index, field=field, value=value))
        return None
    if nonnegative and number < 0:
        diagnostics.append(_diag("error", "negative_value", f"{field} cannot be negative", index=index, field=field, value=value))
    if positive and number <= 0:
        diagnostics.append(_diag("error", "non_positive_value", f"{field} must be positive", index=index, field=field, value=value))
    normalized = format(number.normalize(), "f")
    return "0" if normalized in {"-0", ""} else normalized


def _timestamp(value: Any, diagnostics: list[dict[str, Any]], index: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        diagnostics.append(_diag("error", "missing_observed_at", "observed_at is required", index=index))
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        diagnostics.append(_diag("error", "invalid_observed_at", "observed_at must be ISO-8601", index=index, value=value))
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        diagnostics.append(_diag("error", "naive_observed_at", "observed_at must include timezone", index=index, value=value))
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _registry(registry_dir: Path) -> tuple[set[str], dict[str, str]]:
    companies = _load(registry_dir / "companies.json")
    securities = _load(registry_dir / "securities.json")
    if not isinstance(companies, list) or not isinstance(securities, list):
        raise ProductionMarketError("registry companies.json and securities.json must be arrays")
    company_ids = {str(row.get("company_id")) for row in companies if isinstance(row, dict) and row.get("company_id")}
    security_company = {
        str(row.get("security_id")): str(row.get("company_id"))
        for row in securities
        if isinstance(row, dict) and row.get("security_id") and row.get("company_id")
    }
    return company_ids, security_company


def _snapshot_id(row: dict[str, Any]) -> str:
    key = "|".join(str(row.get(k) or "") for k in ("security_id", "provider", "observed_at"))
    return "market:" + sha256(key.encode("utf-8")).hexdigest()[:24]


def build_production_market(
    *,
    source_dir: str | Path,
    output_dir: str | Path = "data/market",
    registry_dir: str | Path = "data/company_registry",
    strict: bool = False,
    write: bool = False,
) -> dict[str, Any]:
    source = Path(source_dir)
    registry_path = Path(registry_dir)
    raw_snapshots = _load(source / "market_snapshots.json")
    provenance = _load(source / "provenance.json")
    if not isinstance(raw_snapshots, list) or not isinstance(provenance, list):
        raise ProductionMarketError("market_snapshots.json and provenance.json must be arrays")
    company_ids, security_company = _registry(registry_path)
    provenance_ids = {str(row.get("provenance_id")) for row in provenance if isinstance(row, dict) and row.get("provenance_id")}
    diagnostics: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    natural_keys: Counter[tuple[str, str, str]] = Counter()
    decimal_fields = {
        "regular_market_price": {"positive": True},
        "previous_close": {"nonnegative": True},
        "market_cap": {"nonnegative": True},
        "shares_outstanding": {"positive": True},
        "trailing_earnings_per_share": {},
        "forward_earnings_per_share": {},
        "trailing_price_to_earnings": {},
        "forward_price_to_earnings": {},
        "price_to_book": {},
        "enterprise_value": {},
        "enterprise_value_to_revenue": {},
        "enterprise_value_to_ebitda": {},
        "beta": {},
        "fifty_two_week_low": {"nonnegative": True},
        "fifty_two_week_high": {"nonnegative": True},
    }
    for index, raw in enumerate(raw_snapshots):
        if not isinstance(raw, dict):
            diagnostics.append(_diag("error", "invalid_snapshot_shape", "snapshot must be an object", index=index))
            continue
        security_id = str(raw.get("security_id") or "").strip()
        company_id = str(raw.get("company_id") or "").strip()
        provider = str(raw.get("provider") or "").strip().lower()
        symbol = str(raw.get("symbol") or "").strip().upper()
        observed_at = _timestamp(raw.get("observed_at"), diagnostics, index)
        if not security_id:
            diagnostics.append(_diag("error", "missing_security_id", "security_id is required", index=index))
        elif security_id not in security_company:
            diagnostics.append(_diag("error", "unknown_security_id", "security_id not found in registry", index=index, security_id=security_id))
        if not company_id:
            diagnostics.append(_diag("error", "missing_company_id", "company_id is required", index=index))
        elif company_id not in company_ids:
            diagnostics.append(_diag("error", "unknown_company_id", "company_id not found in registry", index=index, company_id=company_id))
        expected_company = security_company.get(security_id)
        if expected_company and company_id and expected_company != company_id:
            diagnostics.append(_diag("error", "security_company_mismatch", "security_id belongs to a different company_id", index=index, security_id=security_id, expected_company_id=expected_company, company_id=company_id))
        if not provider:
            diagnostics.append(_diag("error", "missing_provider", "provider is required", index=index))
        if not symbol:
            diagnostics.append(_diag("error", "missing_symbol", "symbol is required", index=index))
        currency = str(raw.get("currency") or "").strip().upper() or None
        if currency is not None and (len(currency) != 3 or not currency.isalpha()):
            diagnostics.append(_diag("error", "invalid_currency", "currency must be a three-letter code", index=index, currency=currency))
        pids = sorted({str(item) for item in (raw.get("provenance_ids") or []) if str(item).strip()})
        missing_pids = [pid for pid in pids if pid not in provenance_ids]
        if not pids:
            diagnostics.append(_diag("warning", "missing_provenance", "snapshot has no provenance_ids", index=index))
        if missing_pids:
            diagnostics.append(_diag("error", "unknown_provenance", "snapshot references unknown provenance", index=index, provenance_ids=missing_pids))
        normalized: dict[str, Any] = {
            "snapshot_id": "",
            "company_id": company_id,
            "security_id": security_id,
            "symbol": symbol,
            "provider": provider,
            "observed_at": observed_at,
            "currency": currency,
            "exchange": str(raw.get("exchange") or "").strip().upper() or None,
            "quote_type": str(raw.get("quote_type") or "").strip().lower() or None,
            "company_name": str(raw.get("company_name") or "").strip() or None,
            "provenance_ids": pids,
            "metadata": raw.get("metadata") or {},
        }
        for field, rules in decimal_fields.items():
            normalized[field] = _decimal(raw.get(field), field, diagnostics, index, **rules)
        low, high = normalized["fifty_two_week_low"], normalized["fifty_two_week_high"]
        if low is not None and high is not None and Decimal(low) > Decimal(high):
            diagnostics.append(_diag("error", "invalid_52_week_range", "fifty_two_week_low exceeds fifty_two_week_high", index=index))
        normalized["snapshot_id"] = str(raw.get("snapshot_id") or "").strip() or _snapshot_id(normalized)
        if normalized["snapshot_id"] in seen_ids:
            diagnostics.append(_diag("error", "duplicate_snapshot_id", "duplicate snapshot_id", index=index, snapshot_id=normalized["snapshot_id"]))
        seen_ids.add(normalized["snapshot_id"])
        natural_keys[(security_id, provider, observed_at or "")] += 1
        snapshots.append(normalized)
    for key, count in natural_keys.items():
        if count > 1:
            diagnostics.append(_diag("error", "duplicate_market_snapshot", "multiple snapshots share security/provider/observed_at", key=list(key), count=count))
    snapshots.sort(key=lambda row: (str(row["security_id"]), str(row["observed_at"]), str(row["provider"])))
    errors = sum(item["severity"] == "error" for item in diagnostics)
    warnings = sum(item["severity"] == "warning" for item in diagnostics)
    valid = errors == 0
    if strict and not valid:
        raise ProductionMarketError(f"market import has {errors} validation errors")
    manifest = {
        "schema_version": "1.0.0",
        "market_version": "V028.2",
        "generated_at": _now(),
        "source_dir": str(source),
        "registry_dir": str(registry_path),
        "snapshot_count": len(snapshots),
        "company_count": len({row["company_id"] for row in snapshots if row["company_id"]}),
        "security_count": len({row["security_id"] for row in snapshots if row["security_id"]}),
        "provider_count": len({row["provider"] for row in snapshots if row["provider"]}),
        "errors": errors,
        "warnings": warnings,
        "valid": valid,
        "files": ["market_snapshots.json", "provenance.json", "market_diagnostics.json", "market_manifest.json"],
    }
    out = Path(output_dir)
    if write:
        out.mkdir(parents=True, exist_ok=True)
        for name, payload in (("market_snapshots.json", snapshots), ("provenance.json", provenance), ("market_diagnostics.json", diagnostics), ("market_manifest.json", manifest)):
            (out / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**manifest, "output_dir": str(out), "dry_run": not write}


def validate_production_market(*, output_dir: str | Path = "data/market", registry_dir: str | Path = "data/company_registry") -> dict[str, Any]:
    root = Path(output_dir)
    required = ["market_snapshots.json", "provenance.json", "market_diagnostics.json", "market_manifest.json"]
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        return {"valid": False, "errors": [f"missing file: {name}" for name in missing], "output_dir": str(root)}
    snapshots = _load(root / "market_snapshots.json")
    diagnostics = _load(root / "market_diagnostics.json")
    manifest = _load(root / "market_manifest.json")
    if not isinstance(snapshots, list) or not isinstance(diagnostics, list) or not isinstance(manifest, dict):
        return {"valid": False, "errors": ["invalid_output_shape"], "output_dir": str(root)}
    company_ids, security_company = _registry(Path(registry_dir))
    invalid_security_links = [row.get("snapshot_id") for row in snapshots if row.get("security_id") not in security_company]
    invalid_company_links = [row.get("snapshot_id") for row in snapshots if row.get("company_id") not in company_ids]
    mismatches = [row.get("snapshot_id") for row in snapshots if security_company.get(row.get("security_id")) not in (None, row.get("company_id"))]
    ids = [row.get("snapshot_id") for row in snapshots]
    duplicate_ids = sorted(key for key, count in Counter(ids).items() if key and count > 1)
    errors = [item.get("code") for item in diagnostics if item.get("severity") == "error"]
    if invalid_security_links: errors.append("invalid_security_links")
    if invalid_company_links: errors.append("invalid_company_links")
    if mismatches: errors.append("security_company_mismatches")
    if duplicate_ids: errors.append("duplicate_snapshot_ids")
    if manifest.get("snapshot_count") != len(snapshots): errors.append("manifest_mismatch")
    return {
        "valid": not errors,
        "errors": errors,
        "snapshot_count": len(snapshots),
        "company_count": len({row.get("company_id") for row in snapshots if row.get("company_id")}),
        "security_count": len({row.get("security_id") for row in snapshots if row.get("security_id")}),
        "invalid_security_links": invalid_security_links,
        "invalid_company_links": invalid_company_links,
        "security_company_mismatches": mismatches,
        "duplicate_snapshot_ids": duplicate_ids,
        "output_dir": str(root),
    }
