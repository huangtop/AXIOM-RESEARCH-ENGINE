from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from axiom_engine.etf_engine_adapter import load_cached_etf_engine_snapshot


class CanonicalETFExposureError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalETFExposureError(f"cannot read {path}: {exc}") from exc


def _stable_id(prefix: str, *values: Any) -> str:
    digest = hashlib.sha256("|".join(str(value or "") for value in values).encode()).hexdigest()[:28]
    return f"{prefix}:{digest}"


def build_canonical_etf_exposure(
    root: Path,
    *,
    cache_path: str = "data/generated/provider_cache/etf_engine_v2",
    bridge_path: str = "data/generated/etf_identity_bridge/identity_bridge.json",
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    snapshot = load_cached_etf_engine_snapshot(root / cache_path)
    bridge = _load(root / bridge_path)
    if bridge.get("schema_version") != "etf-security-identity-bridge.v031e.1":
        raise CanonicalETFExposureError("V031E.1B identity bridge input is required")
    state = snapshot["state"]
    if bridge.get("source_snapshot", {}).get("snapshot_id") != state.get("current_snapshot_id"):
        raise CanonicalETFExposureError("ETF identity bridge and provider cache snapshots do not match")
    holdings = snapshot["holdings_index"]
    bridge_by_symbol = {str(row["holding_symbol"]): row for row in bridge["records"]}
    if set(holdings) != set(bridge_by_symbol):
        raise CanonicalETFExposureError("ETF identity bridge symbol coverage does not match provider cache")

    provenance_id = _stable_id("provenance:ETF-ENGINE-V2", state["current_snapshot_id"], state["holdings_index_sha256"])
    provenance = [{
        "provenance_id": provenance_id,
        "source_type": "external_etf_holdings_provider",
        "source_name": "ETF-ENGINE-V2",
        "source_repository": state["source_repository"],
        "source_snapshot_id": state["current_snapshot_id"],
        "provider_generated_at": state["provider_generated_at"],
        "retrieved_at": state.get("cached_at"),
        "source_url": state["holdings_index_url"],
        "content_sha256": state["holdings_index_sha256"],
        "acquisition_mode": "read_only_https_cache",
        "coverage": state["holdings_coverage"],
    }]
    exposures: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    invalid_weights: list[dict[str, Any]] = []
    source_exposure_count = 0
    source_etf_ids: set[str] = set()
    source_market_counts: Counter[str] = Counter()
    resolved_market_counts: Counter[str] = Counter()
    source_missing_as_of_count = 0
    canonical_missing_as_of_count = 0
    for holding_symbol in sorted(holdings):
        identity = bridge_by_symbol[holding_symbol]
        rows = holdings[holding_symbol]
        source_exposure_count += len(rows)
        for source_row in rows:
            source_etf_id = str(source_row.get("etf_id") or "")
            source_etf_ids.add(source_etf_id)
            source_market = source_etf_id.split("-", 1)[0] if "-" in source_etf_id else "UNKNOWN"
            source_market_counts[source_market] += 1
            if not source_row.get("as_of"):
                source_missing_as_of_count += 1
        if not str(identity.get("status") or "").startswith("resolved_"):
            unresolved.append({
                "holding_symbol": holding_symbol,
                "identity_status": identity.get("status"),
                "reason_code": identity.get("reason_code"),
                "source_exposure_count": len(rows),
                "source_etf_ids": identity.get("source_etf_ids") or [],
            })
            continue
        for row in rows:
            etf_id = str(row.get("etf_id") or "")
            market = etf_id.split("-", 1)[0] if "-" in etf_id else "UNKNOWN"
            weight = row.get("weight")
            if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not 0 <= float(weight) <= 1:
                invalid_weights.append({"holding_symbol": holding_symbol, "etf_id": etf_id, "weight": weight, "reason_code": "PORTFOLIO_WEIGHT_INVALID"})
                continue
            normalized_weight = float(weight)
            as_of = row.get("as_of")
            if not as_of:
                canonical_missing_as_of_count += 1
            resolved_market_counts[market] += 1
            exposures.append({
                "etf_exposure_id": _stable_id("etf-exposure", state["current_snapshot_id"], etf_id, identity["security_id"]),
                "company_id": identity["company_id"],
                "security_id": identity["security_id"],
                "holding_symbol": holding_symbol,
                "etf_id": etf_id,
                "etf_ticker": row.get("ticker"),
                "etf_name": row.get("name"),
                "etf_name_en": row.get("name_en"),
                "portfolio_weight": normalized_weight,
                "portfolio_weight_percent": round(normalized_weight * 100, 8),
                "as_of": as_of,
                "as_of_status": "available" if as_of else "unavailable_provider_did_not_supply",
                "provider_generated_at": state["provider_generated_at"],
                "source": "ETF-ENGINE-V2",
                "source_status": state["holdings_coverage"],
                "identity_resolution_status": identity["status"],
                "provenance_ids": [provenance_id],
            })
    exposures.sort(key=lambda row: (str(row["company_id"]), -row["portfolio_weight"], str(row["etf_id"])))
    canonical_etf_ids = {str(row["etf_id"]) for row in exposures}
    canonical_company_ids = {str(row["company_id"]) for row in exposures}
    resolved_count = len(exposures)
    return {
        "schema_version": "canonical-etf-exposure.v031e.1",
        "version": "V031E.1C",
        "generated_at": current.isoformat(),
        "source_snapshot": {
            "snapshot_id": state["current_snapshot_id"],
            "provider_generated_at": state["provider_generated_at"],
            "holdings_index_sha256": state["holdings_index_sha256"],
            "holdings_coverage": state["holdings_coverage"],
        },
        "summary": {
            "source_holding_symbol_count": len(holdings),
            "provider_manifest_etf_count": (state.get("summary") or {}).get("etf_count"),
            "holdings_index_etf_count": len(source_etf_ids),
            "source_etf_exposure_count": source_exposure_count,
            "canonical_etf_exposure_count": resolved_count,
            "unresolved_etf_exposure_count": source_exposure_count - resolved_count,
            "canonical_company_count": len(canonical_company_ids),
            "canonical_etf_count": len(canonical_etf_ids),
            "canonical_exposure_ratio": round(resolved_count / source_exposure_count, 6) if source_exposure_count else 0.0,
            "source_missing_as_of_count": source_missing_as_of_count,
            "canonical_missing_as_of_count": canonical_missing_as_of_count,
            "invalid_weight_count": len(invalid_weights),
            "source_status": state["holdings_coverage"],
            "source_market_exposure_counts": dict(sorted(source_market_counts.items())),
            "canonical_market_exposure_counts": dict(sorted(resolved_market_counts.items())),
            "valuation_readiness_consumed": False,
        },
        "exposures": exposures,
        "provenance": provenance,
        "coverage_audit": {
            "unresolved_symbols": unresolved,
            "invalid_weights": invalid_weights,
            "unresolved_reason_counts": dict(sorted(Counter(row["reason_code"] for row in unresolved).items())),
            "source_etf_ids": sorted(source_etf_ids),
        },
        "indexes": {
            "company_id_to_exposure_positions": {
                company_id: [index for index, row in enumerate(exposures) if row["company_id"] == company_id]
                for company_id in sorted(canonical_company_ids)
            },
            "security_id_to_exposure_positions": {
                security_id: [index for index, row in enumerate(exposures) if row["security_id"] == security_id]
                for security_id in sorted({str(row["security_id"]) for row in exposures})
            },
        },
    }


def write_canonical_etf_exposure(report: Mapping[str, Any], output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "etf_exposures.json": report["exposures"],
        "provenance.json": report["provenance"],
        "coverage_audit.json": report["coverage_audit"],
        "manifest.json": {key: report[key] for key in ("schema_version", "version", "generated_at", "source_snapshot", "summary")},
        "indexes.json": report["indexes"],
    }
    for name, payload in outputs.items():
        temporary = output_root / f".{name}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output_root / name)
