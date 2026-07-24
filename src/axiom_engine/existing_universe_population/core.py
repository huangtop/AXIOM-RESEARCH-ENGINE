from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from axiom_engine.production_registry import build_production_registry, validate_production_registry


class ExistingUniversePopulationError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExistingUniversePopulationError(f"cannot read {path}: {exc}") from exc


def _diag(severity: str, code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, "details": details}


def build_existing_universe_population(
    *,
    universe_dir: str | Path = "data/universe",
    output_dir: str | Path = "data/existing_universe_population",
    write: bool = False,
    strict: bool = False,
) -> dict[str, Any]:
    source = Path(universe_dir)
    companies_path, securities_path = source / "companies.json", source / "securities.json"
    if not companies_path.exists() or not securities_path.exists():
        raise ExistingUniversePopulationError("universe requires companies.json and securities.json")
    companies_in, securities_in = _load(companies_path), _load(securities_path)
    if not isinstance(companies_in, list) or not isinstance(securities_in, list):
        raise ExistingUniversePopulationError("universe files must contain JSON arrays")

    diagnostics: list[dict[str, Any]] = []
    company_ids: set[str] = set()
    companies: list[dict[str, Any]] = []
    provenance_id = "provenance:V030.0-existing-universe"
    for raw in companies_in:
        cid = str(raw.get("company_id") or "").strip()
        if not cid:
            diagnostics.append(_diag("error", "missing_company_id", "Company is missing company_id"))
            continue
        if cid in company_ids:
            diagnostics.append(_diag("error", "duplicate_company_id", "Duplicate company_id", company_id=cid))
            continue
        company_ids.add(cid)
        metadata = dict(raw.get("metadata") or {})
        metadata["population_source"] = "data/universe"
        companies.append({
            "company_id": cid,
            "legal_name": raw.get("legal_name"),
            "display_name": raw.get("display_name"),
            "aliases": raw.get("aliases") or [],
            "country": raw.get("country") or "US",
            "website": raw.get("website"),
            "official_sector": raw.get("official_sector"),
            "official_industry": raw.get("official_industry"),
            "business_description": raw.get("business_description"),
            "status": raw.get("status", "active"),
            "provenance_ids": [provenance_id],
            "metadata": metadata,
        })

    securities: list[dict[str, Any]] = []
    security_ids: set[str] = set()
    listing_keys: set[tuple[str, str]] = set()
    primary_counts: dict[str, int] = {}
    for raw in securities_in:
        sid = str(raw.get("security_id") or "").strip()
        cid = str(raw.get("company_id") or "").strip()
        exchange = str(raw.get("exchange") or "").strip().upper()
        ticker = str(raw.get("ticker") or "").strip().upper()
        if not sid:
            diagnostics.append(_diag("error", "missing_security_id", "Security is missing security_id"))
            continue
        if sid in security_ids:
            diagnostics.append(_diag("error", "duplicate_security_id", "Duplicate security_id", security_id=sid))
            continue
        security_ids.add(sid)
        if cid not in company_ids:
            diagnostics.append(_diag("error", "invalid_company_link", "Security references unknown company", security_id=sid, company_id=cid))
        key = (exchange, ticker)
        if key in listing_keys:
            diagnostics.append(_diag("error", "ticker_collision", "Ticker collides on exchange", exchange=exchange, ticker=ticker))
        listing_keys.add(key)
        primary = bool(raw.get("primary_listing", False))
        if primary:
            primary_counts[cid] = primary_counts.get(cid, 0) + 1
        metadata = dict(raw.get("metadata") or {})
        metadata["population_source"] = "data/universe"
        securities.append({
            "security_id": sid,
            "company_id": cid,
            "exchange": exchange,
            "ticker": ticker,
            "currency": raw.get("currency") or "USD",
            "security_type": raw.get("security_type", "common_stock"),
            "primary_listing": primary,
            "isin": raw.get("isin"),
            "figi": raw.get("figi"),
            "listing_status": raw.get("status", raw.get("listing_status", "active")),
            "provenance_ids": [provenance_id],
            "metadata": metadata,
        })

    for cid in sorted(company_ids):
        count = primary_counts.get(cid, 0)
        if count == 0:
            diagnostics.append(_diag("error", "missing_primary_listing", "Company has no primary listing", company_id=cid))
        elif count > 1:
            diagnostics.append(_diag("error", "multiple_primary_listings", "Company has multiple primary listings", company_id=cid, count=count))

    provenance = [{
        "provenance_id": provenance_id,
        "source_type": "canonical_repository_migration",
        "source_name": "AXIOM existing universe",
        "source_path": str(source),
        "captured_at": _now(),
        "version": "V030.0",
    }]
    errors = sum(x["severity"] == "error" for x in diagnostics)
    warnings = sum(x["severity"] == "warning" for x in diagnostics)
    valid = errors == 0
    if strict and not valid:
        raise ExistingUniversePopulationError(f"population has {errors} errors")

    out = Path(output_dir)
    source_out, registry_out = out / "registry_source", out / "registry"
    if write:
        source_out.mkdir(parents=True, exist_ok=True)
        for name, value in (("companies.json", companies), ("securities.json", securities), ("provenance.json", provenance)):
            (source_out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (out / "population_diagnostics.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    registry = build_production_registry(source_dir=source_out if write else _materialize_temp(out, companies, securities, provenance), output_dir=registry_out, write=write, strict=strict)
    manifest = {
        "schema_version": "1.0.0", "population_version": "V030.0", "generated_at": _now(),
        "universe_dir": str(source), "output_dir": str(out), "company_count": len(companies),
        "security_count": len(securities), "primary_listing_count": sum(primary_counts.values()),
        "errors": errors, "warnings": warnings, "valid": valid and registry.get("valid", False),
        "registry_source_dir": str(source_out), "registry_output_dir": str(registry_out),
        "registry": registry,
    }
    if write:
        (out / "universe_population_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**manifest, "dry_run": not write}


def _materialize_temp(out: Path, companies: list[dict[str, Any]], securities: list[dict[str, Any]], provenance: list[dict[str, Any]]) -> Path:
    import tempfile
    root = Path(tempfile.mkdtemp(prefix="axiom-v0300-"))
    for name, value in (("companies.json", companies), ("securities.json", securities), ("provenance.json", provenance)):
        (root / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return root


def validate_existing_universe_population(*, output_dir: str | Path = "data/existing_universe_population") -> dict[str, Any]:
    root = Path(output_dir)
    required = ["registry_source/companies.json", "registry_source/securities.json", "registry_source/provenance.json", "registry/companies.json", "registry/securities.json", "population_diagnostics.json", "universe_population_manifest.json"]
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        return {"valid": False, "errors": [f"missing file: {x}" for x in missing], "output_dir": str(root)}
    manifest = _load(root / "universe_population_manifest.json")
    diagnostics = _load(root / "population_diagnostics.json")
    registry = validate_production_registry(output_dir=root / "registry")
    errors = [x.get("code") for x in diagnostics if x.get("severity") == "error"]
    companies = _load(root / "registry_source/companies.json")
    securities = _load(root / "registry_source/securities.json")
    valid = not errors and registry.get("valid") and manifest.get("company_count") == len(companies) and manifest.get("security_count") == len(securities)
    return {"valid": bool(valid), "errors": errors + ([] if registry.get("valid") else ["invalid_registry"]), "company_count": len(companies), "security_count": len(securities), "registry": registry, "output_dir": str(root)}
