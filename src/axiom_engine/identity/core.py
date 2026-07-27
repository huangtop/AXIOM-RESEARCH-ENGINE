from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def normalize_symbol(value: Any) -> str | None:
    token = str(value or "").strip().upper()
    if not token:
        return None
    return token.replace(".", "-")


def normalize_cik(value: Any) -> str | None:
    if value is None:
        return None
    match = re.search(r"(?:CIK)?0*(\d+)", str(value).strip(), re.I)
    if not match:
        return None
    return match.group(1).zfill(10)


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _snapshot_symbols(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    symbols = payload.get("symbols") or {}
    if isinstance(symbols, dict):
        return {s for s in (normalize_symbol(k) for k in symbols) if s}
    if isinstance(symbols, list):
        out = set()
        for row in symbols:
            if isinstance(row, dict):
                symbol = normalize_symbol(row.get("symbol") or row.get("ticker"))
                if symbol:
                    out.add(symbol)
        return out
    return set()


def _symbol_cache_symbols(path: Path) -> set[str]:
    """Discover Yahoo symbols directly from per-symbol cache files.

    This is the authoritative fallback when the merged canonical snapshot is
    missing, stale, or empty. Invalid JSON files are ignored rather than
    failing the identity build.
    """
    if not path.exists():
        return set()
    symbols: set[str] = set()
    for item in sorted(path.glob("*.json")):
        symbol = None
        try:
            payload = json.loads(item.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                symbol = normalize_symbol(payload.get("symbol") or payload.get("ticker"))
        except (OSError, json.JSONDecodeError):
            pass
        symbol = symbol or normalize_symbol(item.stem)
        if symbol:
            symbols.add(symbol)
    return symbols


def build_identity_mapping(
    repository_root: Path,
    *,
    companies_path: str = "data/universe/companies.json",
    securities_path: str = "data/universe/securities.json",
    yahoo_snapshot_path: str = "data/generated/company/yahoo_company_snapshot.json",
    yahoo_symbol_cache_root: str = "data/generated/provider_cache/yahoo/company_snapshot",
    registry_companies_path: str = "data/company_registry/companies.json",
    registry_securities_path: str = "data/company_registry/securities.json",
) -> dict[str, Any]:
    companies = _load(repository_root / companies_path, [])
    securities = _load(repository_root / securities_path, [])
    canonical_symbols = _snapshot_symbols(_load(repository_root / yahoo_snapshot_path, {}))
    per_symbol_cache_symbols = _symbol_cache_symbols(repository_root / yahoo_symbol_cache_root)
    yahoo_symbols = canonical_symbols | per_symbol_cache_symbols
    registry_companies = _load(repository_root / registry_companies_path, [])
    registry_securities = _load(repository_root / registry_securities_path, [])

    registry_company_by_id = {
        str(row.get("company_id")): row
        for row in registry_companies
        if isinstance(row, dict) and row.get("company_id")
    }
    registry_cik_by_symbol: dict[str, str] = {}
    for security in registry_securities:
        if not isinstance(security, dict):
            continue
        symbol = normalize_symbol(security.get("ticker") or security.get("symbol"))
        registry_company = registry_company_by_id.get(str(security.get("company_id") or ""), {})
        cik = normalize_cik(
            (registry_company.get("metadata") or {}).get("cik")
            or registry_company.get("cik")
            or registry_company.get("company_id")
        )
        if symbol and cik:
            registry_cik_by_symbol[symbol] = cik

    company_by_id = {str(row.get("company_id")): row for row in companies if row.get("company_id")}
    securities_by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ticker_owners: dict[str, set[str]] = defaultdict(set)
    security_ids: set[str] = set()

    for row in securities:
        company_id = str(row.get("company_id") or "")
        symbol = normalize_symbol(row.get("ticker") or row.get("symbol"))
        security_id = str(row.get("security_id") or "")
        if company_id:
            securities_by_company[company_id].append(row)
        if company_id and symbol:
            ticker_owners[symbol].add(company_id)
        if security_id:
            security_ids.add(security_id)

    collisions = {
        symbol: sorted(owners)
        for symbol, owners in sorted(ticker_owners.items())
        if len(owners) > 1
    }

    records: list[dict[str, Any]] = []
    unresolved_primary_security: list[str] = []
    missing_cik: list[str] = []
    yahoo_unmapped = sorted(symbol for symbol in yahoo_symbols if symbol not in ticker_owners)

    for company_id, company in sorted(company_by_id.items()):
        listings = securities_by_company.get(company_id, [])
        primary_id = company.get("primary_security_id")
        primary = next((s for s in listings if s.get("security_id") == primary_id), None)
        if primary is None:
            primary = next((s for s in listings if s.get("primary_listing") is True), None)
        if primary is None and listings:
            primary = sorted(listings, key=lambda s: str(s.get("security_id") or ""))[0]
        if primary is None:
            unresolved_primary_security.append(company_id)
            primary = {}

        primary_symbol = normalize_symbol(primary.get("ticker") or primary.get("symbol"))
        cik = normalize_cik((company.get("metadata") or {}).get("cik") or company.get("cik") or company_id)
        if cik is None and primary_symbol:
            cik = registry_cik_by_symbol.get(primary_symbol)
        if cik is None:
            missing_cik.append(company_id)
        aliases = sorted({
            symbol for symbol in (
                normalize_symbol(s.get("ticker") or s.get("symbol")) for s in listings
            ) if symbol and symbol != primary_symbol
        })
        listing_records = []
        for security in sorted(listings, key=lambda s: str(s.get("security_id") or "")):
            symbol = normalize_symbol(security.get("ticker") or security.get("symbol"))
            listing_records.append({
                "security_id": security.get("security_id"),
                "symbol": symbol,
                "exchange": security.get("exchange"),
                "primary_listing": bool(security.get("primary_listing")),
                "currency": security.get("currency"),
            })

        records.append({
            "company_id": company_id,
            "cik": cik,
            "legal_name": company.get("legal_name"),
            "display_name": company.get("display_name") or company.get("legal_name"),
            "primary_security_id": primary.get("security_id") or primary_id,
            "primary_symbol": primary_symbol,
            "symbol_aliases": aliases,
            "listings": listing_records,
            "provider_links": {
                "sec": {"cik": cik, "linked": cik is not None},
                "yahoo": {
                    "symbol": primary_symbol,
                    "linked": bool(primary_symbol and primary_symbol in yahoo_symbols),
                    "cache_present": bool(primary_symbol and primary_symbol in yahoo_symbols),
                },
            },
            "identity_state": "resolved" if cik and primary_symbol else "partial",
        })

    generated_at = datetime.now(timezone.utc).isoformat()
    resolved = sum(1 for row in records if row["identity_state"] == "resolved")
    report = {
        "schema_version": "canonical-identity-map.v030.10.4",
        "version": "V030.10.4",
        "generated_at": generated_at,
        "summary": {
            "company_count": len(records),
            "resolved_company_count": resolved,
            "partial_company_count": len(records) - resolved,
            "security_count": len(securities),
            "unique_symbol_count": len(ticker_owners),
            "symbol_collision_count": len(collisions),
            "yahoo_cached_symbol_count": len(yahoo_symbols),
            "yahoo_canonical_symbol_count": len(canonical_symbols),
            "yahoo_per_symbol_cache_count": len(per_symbol_cache_symbols),
            "yahoo_unmapped_symbol_count": len(yahoo_unmapped),
        },
        "records": records,
        "indexes": {
            "symbol_to_company_id": {
                symbol: next(iter(owners))
                for symbol, owners in sorted(ticker_owners.items())
                if len(owners) == 1
            },
            "cik_to_company_id": {
                row["cik"]: row["company_id"] for row in records if row.get("cik")
            },
            "security_id_to_company_id": {
                str(s["security_id"]): str(s["company_id"])
                for s in securities if s.get("security_id") and s.get("company_id")
            },
        },
        "diagnostics": {
            "symbol_collisions": collisions,
            "companies_without_primary_security": unresolved_primary_security,
            "companies_without_cik": missing_cik,
            "yahoo_unmapped_symbols": yahoo_unmapped,
        },
    }
    return report


def write_identity_mapping(report: dict[str, Any], output_path: Path, diagnostic_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    diagnostic_path.write_text(json.dumps({
        "schema_version": "canonical-identity-diagnostic.v030.10.4",
        "version": report["version"],
        "generated_at": report["generated_at"],
        "summary": report["summary"],
        **report["diagnostics"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
