from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

from axiom_engine.coverage_policy import CoveragePolicyNotFound, CoveragePolicyService, CoveragePublicationDenied


class PublicationGateError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicationGateError(f"cannot read publication source {path}: {exc}") from exc


def _filename(ticker: str) -> str:
    return quote(ticker, safe="._-") + ".json"


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
    if coverage.get("schema_version") != "coverage-policy-projection.v031f.2.1":
        raise PublicationGateError("V031F.2.1 Coverage Policy is required")
    if valuation.get("schema_version") != "full-market-coverage.v031.0":
        raise PublicationGateError("V031 full-market valuation is required")

    coverage_service = CoveragePolicyService(root=root, projection_path=root / coverage_path)
    records: list[dict[str, Any]] = []
    projections: dict[str, dict[str, Any]] = {}
    for card in valuation.get("cards") or []:
        ticker = str((card.get("primary_security") or {}).get("ticker") or "").upper()
        if not ticker:
            continue
        try:
            decision = coverage_service.require_public(ticker, capability="valuation_card")
        except (CoveragePublicationDenied, CoveragePolicyNotFound):
            continue
        company_id = str((card.get("company") or {}).get("company_id") or decision["company_id"])
        valuation_summary = card.get("valuation") or {}
        market = card.get("market") or {}
        scope_axes = dict(decision.get("scope_axes") or {})
        records.append({
            "company_id": company_id,
            "ticker": ticker,
            "display_name": (card.get("company") or {}).get("display_name"),
            "product_scope": decision.get("product_scope") or "basic_market",
            "research_scope": decision.get("research_scope") or "contextual",
            "scope_axes": scope_axes,
            "valuation_status": valuation_summary.get("status"),
            "calculated_model_count": int(valuation_summary.get("calculated_model_count") or 0),
            "current_price": market.get("current_price"),
            "fair_value": valuation_summary.get("fair_value"),
        })
        projections[ticker] = {
            "schema_version": "company-page-projection.v031f.2.1",
            "version": "V031F.2.1",
            "generated_at": current.isoformat(),
            "company_id": company_id,
            "ticker": ticker,
            "product_scope": decision.get("product_scope") or "basic_market",
            "research_scope": decision.get("research_scope") or "contextual",
            "scope_axes": scope_axes,
            "coverage_policy": {
                "reason_codes": list(decision.get("reason_codes") or []),
                "review_status": decision.get("review_status"),
            },
            "valuation_card": card,
        }

    records.sort(key=lambda row: str(row.get("ticker") or ""))
    index = {row["ticker"]: _filename(row["ticker"]) for row in records}
    axis_counts = {
        axis: sum(bool((row.get("scope_axes") or {}).get(axis)) for row in records)
        for axis in ("research_page", "news_ai", "etf_exposure", "etf_change_analysis", "supply_chain_analysis", "deep_research")
    }
    return {
        "schema_version": "publication-gate-catalog.v031f.2.1",
        "version": "V031F.2.1",
        "generated_at": current.isoformat(),
        "summary": {
            "public_company_count": len(records),
            "basic_market_count": sum(row["product_scope"] == "basic_market" for row in records),
            "frontier_research_count": sum(row["product_scope"] == "frontier_research" for row in records),
            "scope_axis_counts": axis_counts,
            "per_company_projection_count": len(projections),
        },
        "contract": {
            "operating_company_pages_are_market_wide": True,
            "research_actions_determine_basic_publication": False,
            "non_company_instruments_emitted": False,
            "single_company_lookup_requires_full_market_snapshot": False,
        },
        "companies": records,
        "indexes": {"ticker_to_file": index},
        "_company_projections": projections,
    }


def write_publication_catalog(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    projections = report.get("_company_projections") or {}
    archive = output.parent / "company_projections.zip"
    temporary_archive = archive.with_suffix(".zip.tmp")
    with ZipFile(temporary_archive, "w", compression=ZIP_DEFLATED, compresslevel=9) as bundle:
        for ticker, projection in sorted(projections.items()):
            bundle.writestr(_filename(str(ticker)), json.dumps(projection, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary_archive.replace(archive)
    serializable = {key: value for key, value in report.items() if key != "_company_projections"}
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(serializable, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(output)
