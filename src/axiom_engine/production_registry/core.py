from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ProductionRegistryError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionRegistryError(f"cannot read JSON source {path}: {exc}") from exc


def _rows(source_dir: Path, name: str) -> list[dict[str, Any]]:
    key = name.removesuffix(".json")
    path = source_dir / name
    candidates = [path] if path.exists() else sorted(source_dir.glob("*.json"))
    for candidate in candidates:
        value = _load(candidate)
        if candidate == path and isinstance(value, list):
            return value
        rows = value.get(key) if isinstance(value, dict) else None
        if isinstance(rows, list):
            return rows
    return []


def _norm_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace(".", "-")


def _norm_exchange(value: Any) -> str:
    return str(value or "").strip().upper()


def _slug(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", value.upper()).strip("-")


def _company_id(row: dict[str, Any]) -> str:
    existing = str(row.get("company_id") or "").strip()
    if existing:
        return existing
    country = str(row.get("country") or "XX").upper()
    identifiers = row.get("identifiers") or {}
    cik = str(row.get("cik") or identifiers.get("cik") or "").zfill(10)
    if cik.strip("0"):
        return f"company:{country}-CIK{cik}"
    lei = str(row.get("lei") or identifiers.get("lei") or "").strip().upper()
    if lei:
        return f"company:{country}-LEI{lei}"
    name = str(row.get("legal_name") or row.get("display_name") or row.get("name") or "UNKNOWN")
    digest = hashlib.sha256(f"{country}|{name.casefold()}".encode()).hexdigest()[:16]
    return f"company:{country}-NAME-{digest}"


def _diag(severity: str, code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, "details": details}


def build_production_registry(*, source_dir: str | Path, output_dir: str | Path = "data/company_registry", write: bool = False, strict: bool = False) -> dict[str, Any]:
    source = Path(source_dir)
    if not source.is_dir():
        raise ProductionRegistryError(f"source directory not found: {source}")
    companies_in = _rows(source, "companies.json")
    securities_in = _rows(source, "securities.json")
    provenance_in = _rows(source, "provenance.json")
    if not companies_in:
        raise ProductionRegistryError("companies.json contains no companies")

    diagnostics: list[dict[str, Any]] = []
    provenance_ids = {str(row.get("provenance_id")) for row in provenance_in if row.get("provenance_id")}
    companies: list[dict[str, Any]] = []
    company_ids: set[str] = set()
    aliases: dict[str, str] = {}

    for raw in companies_in:
        cid = _company_id(raw)
        if cid in company_ids:
            diagnostics.append(_diag("error", "duplicate_company", "Duplicate canonical company id", company_id=cid))
            continue
        company_ids.add(cid)
        legal_name = str(raw.get("legal_name") or raw.get("name") or "").strip() or None
        display_name = str(raw.get("display_name") or legal_name or "").strip() or None
        if not legal_name:
            diagnostics.append(_diag("error", "missing_company_name", "Company has no legal name", company_id=cid))
        country = str(raw.get("country") or "").strip().upper() or None
        if not country:
            diagnostics.append(_diag("warning", "missing_country", "Company country is missing", company_id=cid))
        pids = sorted(set(map(str, raw.get("provenance_ids") or [])))
        missing_pids = [pid for pid in pids if pid not in provenance_ids]
        if not pids:
            diagnostics.append(_diag("warning", "missing_provenance", "Company has no provenance", company_id=cid))
        elif missing_pids:
            diagnostics.append(_diag("error", "invalid_provenance", "Company references unknown provenance", company_id=cid, provenance_ids=missing_pids))
        companies.append({
            "company_id": cid, "legal_name": legal_name, "display_name": display_name,
            "country": country, "website": raw.get("website"),
            "official_sector": raw.get("official_sector"), "official_industry": raw.get("official_industry"),
            "business_description": raw.get("business_description"), "status": raw.get("status", "active"),
            "provenance_ids": pids, "metadata": raw.get("metadata") or {},
        })
        for alias in raw.get("aliases") or []:
            aliases[str(alias).casefold()] = cid

    securities: list[dict[str, Any]] = []
    seen_security: set[str] = set()
    listing_keys: Counter[tuple[str, str]] = Counter()
    primary_by_company: defaultdict[str, int] = defaultdict(int)
    for raw in securities_in:
        cid = str(raw.get("company_id") or "").strip()
        exchange, ticker = _norm_exchange(raw.get("exchange")), _norm_ticker(raw.get("ticker"))
        sid = str(raw.get("security_id") or "").strip() or f"security:{_slug(exchange or 'UNKNOWN')}-{_slug(ticker or 'UNKNOWN')}"
        if sid in seen_security:
            diagnostics.append(_diag("error", "duplicate_security", "Duplicate security id", security_id=sid))
            continue
        seen_security.add(sid)
        if cid not in company_ids:
            diagnostics.append(_diag("error", "invalid_company_link", "Security references unknown company", security_id=sid, company_id=cid))
        if not exchange:
            diagnostics.append(_diag("error", "missing_exchange", "Security exchange is missing", security_id=sid))
        if not ticker:
            diagnostics.append(_diag("error", "missing_ticker", "Security ticker is missing", security_id=sid))
        if exchange and ticker:
            listing_keys[(exchange, ticker)] += 1
        primary = bool(raw.get("primary_listing", False))
        if primary:
            primary_by_company[cid] += 1
        pids = sorted(set(map(str, raw.get("provenance_ids") or [])))
        if not pids:
            diagnostics.append(_diag("warning", "missing_provenance", "Security has no provenance", security_id=sid))
        unknown = [pid for pid in pids if pid not in provenance_ids]
        if unknown:
            diagnostics.append(_diag("error", "invalid_provenance", "Security references unknown provenance", security_id=sid, provenance_ids=unknown))
        securities.append({
            "security_id": sid, "company_id": cid, "exchange": exchange or None, "ticker": ticker or None,
            "currency": raw.get("currency"), "security_type": raw.get("security_type", "common_stock"),
            "primary_listing": primary, "isin": raw.get("isin"), "figi": raw.get("figi"),
            "listing_status": raw.get("listing_status", "active"), "provenance_ids": pids,
            "metadata": raw.get("metadata") or {},
        })

    for (exchange, ticker), count in sorted(listing_keys.items()):
        if count > 1:
            diagnostics.append(_diag("error", "ticker_collision", "Ticker collides on the same exchange", exchange=exchange, ticker=ticker, count=count))
    for cid, count in primary_by_company.items():
        if count > 1:
            diagnostics.append(_diag("error", "duplicate_primary_listing", "Company has multiple primary listings", company_id=cid, count=count))
    for cid in company_ids:
        if primary_by_company[cid] == 0:
            diagnostics.append(_diag("warning", "missing_primary_listing", "Company has no primary listing", company_id=cid))

    errors = sum(d["severity"] == "error" for d in diagnostics)
    warnings = sum(d["severity"] == "warning" for d in diagnostics)
    valid = errors == 0
    if strict and not valid:
        raise ProductionRegistryError(f"registry has {errors} validation errors")
    generated_at = _now()
    manifest = {
        "schema_version": "1.0.0", "registry_version": "V028.0", "generated_at": generated_at,
        "source_dir": str(source), "company_count": len(companies), "security_count": len(securities),
        "primary_listings": sum(bool(x["primary_listing"]) for x in securities),
        "errors": errors, "warnings": warnings, "valid": valid,
        "files": ["companies.json", "securities.json", "provenance.json", "registry_diagnostics.json", "registry_manifest.json"],
    }
    out = Path(output_dir)
    if write:
        out.mkdir(parents=True, exist_ok=True)
        for name, value in (("companies.json", companies), ("securities.json", securities), ("provenance.json", provenance_in), ("registry_diagnostics.json", diagnostics), ("registry_manifest.json", manifest)):
            (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**manifest, "output_dir": str(out), "dry_run": not write}


def validate_production_registry(*, output_dir: str | Path = "data/company_registry") -> dict[str, Any]:
    root = Path(output_dir)
    required = ["companies.json", "securities.json", "provenance.json", "registry_diagnostics.json", "registry_manifest.json"]
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        return {"valid": False, "errors": [f"missing file: {name}" for name in missing], "output_dir": str(root)}
    companies, securities = _load(root / "companies.json"), _load(root / "securities.json")
    diagnostics, manifest = _load(root / "registry_diagnostics.json"), _load(root / "registry_manifest.json")
    errors = [d for d in diagnostics if d.get("severity") == "error"]
    company_ids = {row.get("company_id") for row in companies}
    invalid_links = [row.get("security_id") for row in securities if row.get("company_id") not in company_ids]
    valid = not errors and not invalid_links and manifest.get("company_count") == len(companies) and manifest.get("security_count") == len(securities)
    return {"valid": valid, "errors": [d.get("code") for d in errors] + (["invalid_security_links"] if invalid_links else []), "company_count": len(companies), "security_count": len(securities), "invalid_security_links": invalid_links, "output_dir": str(root)}
