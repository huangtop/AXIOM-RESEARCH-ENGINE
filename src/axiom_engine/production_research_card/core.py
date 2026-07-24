from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ProductionResearchCardError(RuntimeError):
    pass


def _read(path: Path) -> Any:
    if not path.exists():
        raise ProductionResearchCardError(f"required file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProductionResearchCardError(f"invalid JSON: {path}: {exc}") from exc


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")


def _latest(items: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    if not items:
        return None
    return max(items, key=lambda item: str(item.get(key) or ""))


def _coverage(financials: list[dict[str, Any]], markets: list[dict[str, Any]], estimates: list[dict[str, Any]]) -> dict[str, Any]:
    financial_concepts = sorted({str(item.get("concept")) for item in financials if item.get("concept")})
    estimate_metrics = sorted({str(item.get("metric")) for item in estimates if item.get("metric")})
    missing_layers = [
        name
        for name, values in (("financial", financials), ("market", markets), ("estimate", estimates))
        if not values
    ]
    return {
        "status": "complete" if not missing_layers else "partial",
        "missing_layers": missing_layers,
        "financial_concepts": financial_concepts,
        "estimate_metrics": estimate_metrics,
        "financial_fact_count": len(financials),
        "market_snapshot_count": len(markets),
        "estimate_count": len(estimates),
        "valuation_ready": bool(financials and markets),
    }


def build_production_research_cards(
    *,
    production_dir: str | Path = "data/production",
    output_dir: str | Path = "data/production_research_cards",
    write: bool = False,
    strict: bool = False,
) -> dict[str, Any]:
    production = Path(production_dir)
    output = Path(output_dir)

    companies = _read(production / "registry" / "companies.json")
    securities = _read(production / "registry" / "securities.json")
    financials = _read(production / "financial" / "financial_facts.json")
    markets = _read(production / "market" / "market_snapshots.json")
    estimates = _read(production / "estimate" / "consensus_estimates.json")

    if not all(isinstance(value, list) for value in (companies, securities, financials, markets, estimates)):
        raise ProductionResearchCardError("production layer files must contain JSON arrays")

    securities_by_company: dict[str, list[dict[str, Any]]] = {}
    for security in securities:
        securities_by_company.setdefault(str(security.get("company_id")), []).append(security)

    financials_by_company: dict[str, list[dict[str, Any]]] = {}
    for fact in financials:
        financials_by_company.setdefault(str(fact.get("company_id")), []).append(fact)

    markets_by_company: dict[str, list[dict[str, Any]]] = {}
    for snapshot in markets:
        markets_by_company.setdefault(str(snapshot.get("company_id")), []).append(snapshot)

    estimates_by_company: dict[str, list[dict[str, Any]]] = {}
    for estimate in estimates:
        estimates_by_company.setdefault(str(estimate.get("company_id")), []).append(estimate)

    cards: list[dict[str, Any]] = []
    errors: list[str] = []
    index_by_symbol: dict[str, str] = {}
    index_by_company: dict[str, str] = {}

    for company in sorted(companies, key=lambda item: str(item.get("company_id") or "")):
        company_id = str(company.get("company_id") or "")
        if not company_id:
            errors.append("company without company_id")
            continue
        company_securities = securities_by_company.get(company_id, [])
        primary = next((item for item in company_securities if item.get("primary_listing") is True), None)
        primary = primary or (company_securities[0] if company_securities else None)
        if primary is None:
            errors.append(f"company has no security: {company_id}")
            if strict:
                continue

        company_financials = financials_by_company.get(company_id, [])
        company_markets = markets_by_company.get(company_id, [])
        company_estimates = estimates_by_company.get(company_id, [])
        latest_market = _latest(company_markets, "observed_at")

        card_id = f"research-card:{company_id}"
        symbol = str(primary.get("ticker") or primary.get("symbol") or "") if primary else ""
        card = {
            "schema_version": "1.0.0",
            "card_version": "V029.0",
            "card_id": card_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "company": company,
            "primary_security": primary,
            "securities": company_securities,
            "market": {
                "latest": latest_market,
                "history": sorted(company_markets, key=lambda item: str(item.get("observed_at") or "")),
            },
            "financials": sorted(
                company_financials,
                key=lambda item: (int(item.get("fiscal_year") or 0), str(item.get("fiscal_period") or ""), str(item.get("concept") or "")),
                reverse=True,
            ),
            "estimates": sorted(
                company_estimates,
                key=lambda item: (int(item.get("fiscal_year") or 0), str(item.get("fiscal_period") or ""), str(item.get("metric") or "")),
            ),
            "coverage": _coverage(company_financials, company_markets, company_estimates),
            "api": {
                "lookup_keys": {"company_id": company_id, "symbol": symbol or None},
                "read_only": True,
                "source": "V028.4 full production build",
            },
        }
        cards.append(card)
        filename = f"{_slug(symbol or company_id)}.json"
        index_by_company[company_id] = filename
        if symbol:
            key = symbol.upper()
            if key in index_by_symbol:
                errors.append(f"duplicate symbol: {key}")
            else:
                index_by_symbol[key] = filename
        if write:
            _write(output / "cards" / filename, card)

    manifest = {
        "schema_version": "1.0.0",
        "research_card_version": "V029.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "production_dir": str(production),
        "output_dir": str(output),
        "card_count": len(cards),
        "complete_card_count": sum(1 for card in cards if card["coverage"]["status"] == "complete"),
        "valuation_ready_count": sum(1 for card in cards if card["coverage"]["valuation_ready"]),
        "errors": len(errors),
        "error_messages": errors,
        "valid": not errors,
        "dry_run": not write,
        "files": ["research_card_index.json", "research_card_manifest.json", "cards/*.json"],
    }
    if strict and errors:
        raise ProductionResearchCardError(f"research card build failed with {len(errors)} errors: {errors[0]}")
    if write:
        _write(output / "research_card_index.json", {"by_symbol": index_by_symbol, "by_company_id": index_by_company})
        _write(output / "research_card_manifest.json", manifest)
    return manifest


def get_production_research_card(
    *,
    output_dir: str | Path = "data/production_research_cards",
    symbol: str | None = None,
    company_id: str | None = None,
) -> dict[str, Any]:
    if bool(symbol) == bool(company_id):
        raise ProductionResearchCardError("provide exactly one of symbol or company_id")
    output = Path(output_dir)
    index = _read(output / "research_card_index.json")
    if symbol:
        filename = index.get("by_symbol", {}).get(symbol.strip().upper())
        lookup = f"symbol {symbol.strip().upper()}"
    else:
        filename = index.get("by_company_id", {}).get(str(company_id).strip())
        lookup = f"company_id {company_id}"
    if not filename:
        raise ProductionResearchCardError(f"research card not found for {lookup}")
    payload = _read(output / "cards" / filename)
    if not isinstance(payload, dict):
        raise ProductionResearchCardError(f"research card must be an object: {filename}")
    return payload


def validate_production_research_cards(*, output_dir: str | Path = "data/production_research_cards") -> dict[str, Any]:
    output = Path(output_dir)
    errors: list[str] = []
    try:
        manifest = _read(output / "research_card_manifest.json")
        index = _read(output / "research_card_index.json")
    except ProductionResearchCardError as exc:
        return {"valid": False, "errors": [str(exc)], "output_dir": str(output), "card_count": 0}

    filenames = set(index.get("by_company_id", {}).values()) | set(index.get("by_symbol", {}).values())
    for filename in sorted(filenames):
        path = output / "cards" / filename
        if not path.exists():
            errors.append(f"indexed card not found: {filename}")
            continue
        try:
            card = _read(path)
        except ProductionResearchCardError as exc:
            errors.append(str(exc))
            continue
        if not card.get("card_id") or not card.get("company", {}).get("company_id"):
            errors.append(f"invalid card identity: {filename}")
        if card.get("card_version") != "V029.0":
            errors.append(f"unexpected card version: {filename}")

    expected = int(manifest.get("card_count") or 0)
    if expected != len(set(index.get("by_company_id", {}).values())):
        errors.append("manifest card_count does not match company index")
    return {
        "valid": not errors,
        "errors": errors,
        "card_count": expected,
        "symbol_count": len(index.get("by_symbol", {})),
        "company_count": len(index.get("by_company_id", {})),
        "output_dir": str(output),
    }
