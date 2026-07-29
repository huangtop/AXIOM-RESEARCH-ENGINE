from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping


class ETFCompanyCardError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ETFCompanyCardError(f"cannot read {path}: {exc}") from exc


def _decimal(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def build_etf_company_cards(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    exposure_root = root / "data/generated/canonical_etf_exposure"
    exposure_manifest = _load(exposure_root / "manifest.json")
    exposures = _load(exposure_root / "etf_exposures.json")
    exposure_audit = _load(exposure_root / "coverage_audit.json")
    valuations = _load(root / "data/generated/full_market_coverage/full_market_coverage.json")
    if exposure_manifest.get("schema_version") != "canonical-etf-exposure.v031e.1":
        raise ETFCompanyCardError("unsupported Canonical ETF Exposure schema")
    if valuations.get("schema_version") != "full-market-coverage.v031.0":
        raise ETFCompanyCardError("unsupported Full-Market Valuation schema")
    if not isinstance(exposures, list) or not isinstance(valuations.get("cards"), list):
        raise ETFCompanyCardError("ETF company-card inputs are invalid")

    valuation_by_company = {
        str(card.get("company", {}).get("company_id")): card
        for card in valuations["cards"]
        if card.get("company", {}).get("company_id")
    }
    known_etf_ids = sorted(
        etf_id
        for etf_id in {str(value) for value in exposure_audit.get("source_etf_ids", [])}
        if etf_id.startswith("US-")
    )
    cards: list[dict[str, Any]] = []
    missing_valuation = []
    for exposure in exposures:
        etf_id = str(exposure.get("etf_id") or "")
        if not etf_id.startswith("US-"):
            continue
        company_id = str(exposure.get("company_id") or "")
        valuation_card = valuation_by_company.get(company_id)
        if valuation_card is None:
            missing_valuation.append({
                "etf_id": etf_id,
                "company_id": company_id,
                "security_id": exposure.get("security_id"),
                "reason_code": "COMPANY_NOT_IN_FULL_MARKET_VALUATION_SCOPE",
            })
            company, security, market, valuation = {}, {}, {}, {}
        else:
            company = valuation_card.get("company") or {}
            security = valuation_card.get("primary_security") or {}
            market = valuation_card.get("market") or {}
            valuation = valuation_card.get("valuation") or {}
        price = _decimal(market.get("current_price"))
        fair_value = _decimal(valuation.get("fair_value"))
        upside = fair_value / price - 1 if price is not None and price > 0 and fair_value is not None else None
        valuation_status = str(valuation.get("status") or "unavailable")
        reason = valuation.get("reason_code")
        if valuation_card is None:
            valuation_status, reason = "unavailable", "COMPANY_NOT_IN_FULL_MARKET_VALUATION_SCOPE"
        elif fair_value is None:
            valuation_status, reason = "unavailable", reason or "NO_CALCULATED_MODELS"
        cards.append({
            "etf_company_card_id": f"etf-company-card:{etf_id}:{exposure.get('security_id')}",
            "etf_id": etf_id,
            "etf_ticker": exposure.get("etf_ticker") or etf_id.removeprefix("US-"),
            "etf_name": exposure.get("etf_name"),
            "company": {
                "company_id": company_id,
                "display_name": company.get("display_name") or company.get("legal_name"),
            },
            "security": {
                "security_id": exposure.get("security_id"),
                "ticker": exposure.get("holding_symbol") or security.get("ticker"),
                "exchange": security.get("exchange"),
            },
            "exposure": {
                "portfolio_weight": exposure.get("portfolio_weight"),
                "portfolio_weight_percent": exposure.get("portfolio_weight_percent"),
                "as_of": exposure.get("as_of"),
                "as_of_status": exposure.get("as_of_status"),
                "source_status": exposure.get("source_status"),
            },
            "market": {
                "status": market.get("status") or "unavailable",
                "current_price": market.get("current_price"),
                "currency": market.get("currency") or security.get("currency"),
                "as_of_date": market.get("as_of_date"),
                "reason_code": market.get("reason_code") or ("MARKET_DATA_UNAVAILABLE" if price is None else None),
            },
            "valuation": {
                "status": valuation_status,
                "fair_value": valuation.get("fair_value"),
                "upside": format(upside, "f") if upside is not None else None,
                "upside_percent": float(upside * 100) if upside is not None else None,
                "calculated_model_count": int(valuation.get("calculated_model_count") or 0),
                "total_model_count": int(valuation.get("total_model_count") or 7),
                "reason_code": reason,
                "aggregation_version": valuation.get("aggregation_version"),
            },
        })
    cards.sort(key=lambda row: (str(row["etf_id"]), -float(row["exposure"]["portfolio_weight"] or 0), str(row["security"]["ticker"])))
    company_ids = sorted({str(row["company"]["company_id"]) for row in cards})
    status_counts = Counter(str(row["valuation"]["status"]) for row in cards)
    etf_ids_with_cards = sorted({str(row["etf_id"]) for row in cards})
    all_known = sorted(set(known_etf_ids) | set(etf_ids_with_cards))
    return {
        "schema_version": "etf-company-cards.v031e.4",
        "version": "V031E.4",
        "generated_at": current.isoformat(),
        "source_snapshots": {
            "canonical_etf_exposure": exposure_manifest.get("source_snapshot"),
            "full_market_coverage_generated_at": valuations.get("generated_at"),
        },
        "summary": {
            "known_us_etf_count": len(all_known),
            "etf_with_cards_count": len(etf_ids_with_cards),
            "company_count": len(company_ids),
            "card_count": len(cards),
            "valuation_status_counts": dict(sorted(status_counts.items())),
            "missing_valuation_card_count": len(missing_valuation),
            "valuation_readiness_used_for_membership": False,
        },
        "cards": cards,
        "coverage_audit": {"missing_valuation_cards": missing_valuation},
        "indexes": {
            "known_etf_ids": all_known,
            "etf_id_to_card_positions": {etf_id: [i for i, row in enumerate(cards) if row["etf_id"] == etf_id] for etf_id in all_known},
            "company_id_to_card_positions": {company_id: [i for i, row in enumerate(cards) if row["company"]["company_id"] == company_id] for company_id in company_ids},
        },
    }


def write_etf_company_cards(report: Mapping[str, Any], output_root: Path) -> None:
    for name, payload in {
        "cards.json": report["cards"],
        "indexes.json": report["indexes"],
        "coverage_audit.json": report["coverage_audit"],
        "manifest.json": {key: report[key] for key in ("schema_version", "version", "generated_at", "source_snapshots", "summary")},
    }.items():
        _atomic_write(output_root / name, payload)
