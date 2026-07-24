from __future__ import annotations

import json
import os
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


class ValuationCardError(RuntimeError):
    pass


def _read(path: Path, default: Any = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise ValuationCardError(f"required research file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValuationCardError(f"cannot read JSON: {path}") from exc


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _metric(section: dict[str, Any], name: str) -> dict[str, Any] | None:
    row = section.get(name)
    return row if isinstance(row, dict) else None


def _growth(actual: dict[str, Any], estimate: dict[str, Any], name: str) -> Decimal | None:
    current = _decimal((_metric(actual, name) or {}).get("value"))
    forward = _decimal((_metric(estimate, name) or {}).get("value"))
    if current in (None, Decimal("0")) or forward is None:
        return None
    return forward / current - Decimal("1")


def _diagnostics_for(diagnostics: list[dict[str, Any]], company_id: str) -> list[dict[str, Any]]:
    return [
        {
            "severity": row.get("severity", "warning"),
            "code": row.get("code", "unknown"),
            "message": row.get("message", ""),
            "details": row.get("details", {}),
        }
        for row in diagnostics
        if row.get("company_id") == company_id
    ]


def _scenario(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {"status": "unavailable", "fair_value": None, "current_price": None, "upside": None, "confidence": None}
    confidence = row.get("confidence")
    return {
        "status": row.get("status", "unavailable"),
        "fair_value": row.get("fair_value_per_share"),
        "current_price": row.get("current_price"),
        "upside": row.get("upside_downside"),
        "confidence": confidence.get("score") if isinstance(confidence, dict) else confidence,
        "confidence_detail": confidence if isinstance(confidence, dict) else None,
    }


def _ranking(bundles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bundle in bundles:
        financial = bundle.get("financial_summary") or {}
        estimates = bundle.get("estimate_summary") or {}
        growth = _growth(financial, estimates, "revenue")
        metric = "revenue"
        if growth is None:
            growth = _growth(financial, estimates, "net_income")
            metric = "net_income"
        if growth is None:
            continue
        rows.append({
            "ticker": bundle.get("ticker"),
            "company_id": bundle.get("company_id"),
            "display_name": (bundle.get("profile") or {}).get("display_name"),
            "metric": metric,
            "growth": str(growth),
        })
    rows.sort(key=lambda row: _decimal(row["growth"]) or Decimal("-Infinity"), reverse=True)
    for index, row in enumerate(rows, 1):
        row["rank"] = index
    return rows


def _to_card(bundle: dict[str, Any], diagnostics: list[dict[str, Any]], ranking: list[dict[str, Any]]) -> dict[str, Any]:
    company_id = str(bundle.get("company_id", ""))
    profile = bundle.get("profile") or {}
    financial = bundle.get("financial_summary") or {}
    estimates = bundle.get("estimate_summary") or {}
    market = bundle.get("market_snapshot") or {}
    valuation = bundle.get("valuation_summary") or {}
    ticker = bundle.get("ticker")
    own_rank = next((row for row in ranking if row.get("company_id") == company_id), None)
    return {
        "schema_version": "1.0.0",
        "research_bundle_id": bundle.get("research_bundle_id"),
        "company_id": company_id,
        "ticker": ticker,
        "status": bundle.get("status", "partial"),
        "generated_at": bundle.get("generated_at"),
        "profile": profile,
        "market": {
            "current_price": _metric(market, "current_price"),
            "previous_close": _metric(market, "previous_close"),
            "market_cap": _metric(market, "market_cap"),
            "enterprise_value": _metric(market, "enterprise_value"),
            "beta": _metric(market, "beta"),
            "price_change": market.get("price_change_from_previous_close"),
        },
        "financials": financial,
        "estimates": estimates,
        "valuation": {
            "bear": _scenario(valuation.get("bear")),
            "base": _scenario(valuation.get("base")),
            "bull": _scenario(valuation.get("bull")),
        },
        "research_confidence": bundle.get("confidence") or {"score": 0, "components": {}},
        "quality_diagnostics": _diagnostics_for(diagnostics, company_id),
        "analyst_growth_ranking": {
            "status": "available" if ranking else "unavailable",
            "company": own_rank,
            "universe": ranking,
        },
        "sections": {
            "overview": {"status": "available"},
            "company_analysis": {"status": "available" if profile.get("business_description") else "awaiting_canonical_data"},
            "industry_map": {"status": "awaiting_canonical_data", "items": []},
            "research_notes": {"status": "awaiting_storage_adapter", "items": []},
            "valuation": {"status": "available" if valuation else "unavailable"},
            "analyst_growth_ranking": {"status": "available" if ranking else "unavailable"},
            "related_news": {"status": "awaiting_news_adapter", "items": []},
        },
        "source_record_ids": bundle.get("source_record_ids") or [],
    }


def build_valuation_cards(*, research_dir: str | Path = "data/research_data", output_dir: str | Path = "data/valuation_card", write: bool = False) -> dict[str, Any]:
    root = Path(research_dir)
    bundles = _read(root / "company_research.json")
    diagnostics = _read(root / "diagnostics.json", default=[])
    if not isinstance(bundles, list) or not isinstance(diagnostics, list):
        raise ValuationCardError("research bundle and diagnostics must be JSON arrays")
    ranking = _ranking(bundles)
    cards = [_to_card(row, diagnostics, ranking) for row in bundles]
    report = {
        "cards_built": len(cards),
        "completed": sum(1 for row in cards if row["status"] == "completed"),
        "partial": sum(1 for row in cards if row["status"] == "partial"),
        "output_directory": str(output_dir),
        "dry_run": not write,
        "valid": bool(cards),
    }
    if write:
        out = Path(output_dir)
        _write(out / "valuation_cards.json", cards)
        _write(out / "manifest.json", {"schema_version": "1.0.0", **report, "files": ["valuation_cards.json", "manifest.json"]})
    return report


def get_valuation_card(*, ticker: str | None = None, company_id: str | None = None, research_dir: str | Path = "data/research_data") -> dict[str, Any]:
    root = Path(research_dir)
    bundles = _read(root / "company_research.json")
    diagnostics = _read(root / "diagnostics.json", default=[])
    if not isinstance(bundles, list):
        raise ValuationCardError("company_research.json must be a JSON array")
    token = str(ticker or "").strip().upper()
    match = next((row for row in bundles if (company_id and row.get("company_id") == company_id) or (token and str(row.get("ticker", "")).upper() == token)), None)
    if match is None:
        raise ValuationCardError(f"research company not found: {ticker or company_id}")
    return _to_card(match, diagnostics if isinstance(diagnostics, list) else [], _ranking(bundles))


def validate_valuation_cards(*, output_dir: str | Path = "data/valuation_card") -> dict[str, Any]:
    root = Path(output_dir)
    errors: list[str] = []
    cards = _read(root / "valuation_cards.json", default=[])
    if not isinstance(cards, list):
        errors.append("valuation_cards.json must be a JSON array")
        cards = []
    required = {"schema_version", "company_id", "ticker", "profile", "market", "valuation", "research_confidence", "sections"}
    for index, row in enumerate(cards):
        if not isinstance(row, dict):
            errors.append(f"card[{index}] must be an object")
            continue
        missing = sorted(required - set(row))
        if missing:
            errors.append(f"card[{index}] missing fields: {', '.join(missing)}")
    return {"output_directory": str(output_dir), "valuation_cards": len(cards), "valid": not errors and bool(cards), "errors": errors}
