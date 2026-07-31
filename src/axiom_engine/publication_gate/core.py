from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class PublicationGateError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicationGateError(f"cannot read publication source {path}: {exc}") from exc


def build_publication_catalog(
    root: Path,
    *,
    coverage_path: str = "data/generated/coverage_policy/coverage_policy.json",
    valuation_path: str = "data/generated/full_market_coverage/full_market_coverage.json",
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    coverage = _load(root / coverage_path)
    valuation = _load(root / valuation_path)
    if coverage.get("schema_version") != "coverage-policy-projection.v031f.1":
        raise PublicationGateError("V031F.1 Coverage Policy is required")
    if valuation.get("schema_version") != "full-market-coverage.v031.0":
        raise PublicationGateError("V031 full-market valuation is required")
    cards_by_company = {
        str((card.get("company") or {}).get("company_id")): card
        for card in valuation.get("cards") or []
        if (card.get("company") or {}).get("company_id")
    }
    records = []
    missing_cards = []
    for decision in coverage.get("records") or []:
        if not bool((decision.get("publication") or {}).get("company_page")):
            continue
        company_id = str(decision["company_id"])
        card = cards_by_company.get(company_id)
        if card is None:
            missing_cards.append({"company_id": company_id, "ticker": decision.get("ticker"), "reason_code": "PUBLIC_COMPANY_VALUATION_CARD_MISSING"})
            continue
        valuation_summary = card.get("valuation") or {}
        market = card.get("market") or {}
        records.append({
            "company_id": company_id,
            "ticker": (card.get("primary_security") or {}).get("ticker") or decision.get("ticker"),
            "display_name": (card.get("company") or {}).get("display_name"),
            "publication_tier": decision.get("publication_tier"),
            "company_page": True,
            "valuation_card": bool((decision.get("publication") or {}).get("valuation_card")),
            "valuation_status": valuation_summary.get("status"),
            "calculated_model_count": int(valuation_summary.get("calculated_model_count") or 0),
            "current_price": market.get("current_price"),
            "fair_value": valuation_summary.get("fair_value"),
            "reason_codes": list(decision.get("reason_codes") or []),
        })
    records.sort(key=lambda row: (0 if row["publication_tier"] == "core" else 1, str(row.get("ticker") or "")))
    return {
        "schema_version": "publication-gate-catalog.v031f.2",
        "version": "V031F.2",
        "generated_at": current.isoformat(),
        "summary": {
            "public_company_count": len(records),
            "core_count": sum(row["publication_tier"] == "core" for row in records),
            "coverage_count": sum(row["publication_tier"] == "coverage" for row in records),
            "missing_public_card_count": len(missing_cards),
            "contextual_or_excluded_records_emitted": 0,
        },
        "contract": {
            "coverage_policy_enforced": True,
            "contextual_default_emitted": False,
            "candidate_emitted": False,
            "excluded_emitted": False,
        },
        "companies": records,
        "diagnostics": {"missing_public_cards": missing_cards},
        "indexes": {"ticker_to_position": {row["ticker"]: index for index, row in enumerate(records) if row.get("ticker")}},
    }


def write_publication_catalog(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(output)
