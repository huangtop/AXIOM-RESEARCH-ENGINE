from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from axiom_engine.etf_engine_adapter import load_cached_etf_engine_snapshot


class ETFIdentityBridgeError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ETFIdentityBridgeError(f"cannot read {path}: {exc}") from exc


def _validate_policy(policy: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != "etf-security-identity-policy.v031e.1":
        raise ETFIdentityBridgeError("unsupported ETF identity policy")
    if policy.get("allow_name_based_matching") is not False:
        raise ETFIdentityBridgeError("name-based security matching must remain disabled")
    if policy.get("allow_manual_ticker_membership") is not False:
        raise ETFIdentityBridgeError("manual ticker membership must remain disabled")


def _symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _market_suffix(symbol: str, suffixes: Mapping[str, Any]) -> str | None:
    if "." not in symbol:
        return None
    suffix = symbol.rsplit(".", 1)[-1]
    return suffix if suffix in suffixes else None


def _class_share_alias(symbol: str) -> str | None:
    match = re.fullmatch(r"([A-Z]{1,5})-([A-Z])", symbol)
    return f"{match.group(1)}.{match.group(2)}" if match else None


def _registry_aliases(security: Mapping[str, Any]) -> set[str]:
    metadata = security.get("metadata") if isinstance(security.get("metadata"), Mapping) else {}
    values: list[Any] = []
    for owner in (security, metadata):
        for key in ("ticker_aliases", "symbol_aliases", "previous_tickers", "previous_symbols"):
            candidate = owner.get(key)
            if isinstance(candidate, list):
                values.extend(candidate)
    return {_symbol(value) for value in values if _symbol(value)}


def build_etf_identity_bridge(
    root: Path,
    *,
    policy_path: str = "config/etf_identity_bridge.v031e.1.json",
    cache_path: str = "data/generated/provider_cache/etf_engine_v2",
    securities_path: str = "data/universe/securities.json",
    identity_path: str = "data/generated/security_identity/security_identity_normalization.json",
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    policy = _load(root / policy_path)
    securities = _load(root / securities_path)
    identity = _load(root / identity_path)
    _validate_policy(policy)
    snapshot = load_cached_etf_engine_snapshot(root / cache_path)
    holdings = snapshot["holdings_index"]
    if not isinstance(securities, list) or identity.get("schema_version") != "security-identity-normalization.v031v.2":
        raise ETFIdentityBridgeError("V031V.2 security identity inputs are required")
    if not isinstance(holdings, Mapping):
        raise ETFIdentityBridgeError("cached ETF holdings index is invalid")

    normalized_by_id = {str(row.get("security_id")): row for row in identity["securities"] if row.get("security_id")}
    exact: dict[str, list[dict[str, Any]]] = defaultdict(list)
    aliases: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for security in securities:
        security_id = str(security.get("security_id") or "")
        normalized = normalized_by_id.get(security_id, {})
        if normalized.get("instrument_type") != policy["accepted_instrument_type"]:
            continue
        if str(security.get("status") or "active").lower() != "active":
            continue
        record = {
            "security_id": security_id,
            "company_id": security.get("company_id"),
            "ticker": _symbol(security.get("ticker")),
            "exchange": security.get("exchange"),
            "primary_listing": bool(security.get("primary_listing")),
        }
        exact[record["ticker"]].append(record)
        for alias in _registry_aliases(security):
            aliases[alias].append(record)

    suffixes = policy["market_suffixes"]
    status_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for holding_symbol in sorted(holdings):
        symbol = _symbol(holding_symbol)
        suffix = _market_suffix(symbol, suffixes)
        candidates = exact.get(symbol, [])
        status = ""
        reason = ""
        matched_symbol: str | None = symbol
        if len(candidates) == 1:
            status = "resolved_market_suffix" if suffix else "resolved_exact"
            reason = "UNIQUE_ACTIVE_COMMON_EQUITY_MATCH"
        elif len(candidates) > 1:
            status, reason = "ambiguous", "MULTIPLE_ACTIVE_COMMON_EQUITY_MATCHES"
        else:
            candidates = aliases.get(symbol, [])
            if len(candidates) == 1:
                status, reason = "resolved_alias", "VERIFIED_REGISTRY_TICKER_ALIAS"
                matched_symbol = candidates[0]["ticker"]
            elif len(candidates) > 1:
                status, reason = "ambiguous", "MULTIPLE_REGISTRY_ALIAS_MATCHES"
            else:
                punctuation_alias = _class_share_alias(symbol) if policy["allow_class_share_punctuation_alias"] else None
                candidates = exact.get(punctuation_alias or "", [])
                if len(candidates) == 1:
                    status, reason = "resolved_alias", "CLASS_SHARE_PUNCTUATION_NORMALIZED"
                    matched_symbol = punctuation_alias
                elif len(candidates) > 1:
                    status, reason = "ambiguous", "MULTIPLE_CLASS_SHARE_ALIAS_MATCHES"
                elif suffix:
                    status, reason = "unsupported_market", "MARKET_NOT_PRESENT_IN_AXIOM_REGISTRY"
                    matched_symbol = None
                else:
                    status, reason = "unresolved", "SECURITY_IDENTITY_NOT_FOUND"
                    matched_symbol = None
        selected = candidates[0] if len(candidates) == 1 and status.startswith("resolved_") else {}
        source_rows = holdings[holding_symbol]
        record = {
            "holding_symbol": holding_symbol,
            "normalized_holding_symbol": symbol,
            "market_suffix": suffix,
            "status": status,
            "reason_code": reason,
            "matched_registry_symbol": matched_symbol,
            "security_id": selected.get("security_id"),
            "company_id": selected.get("company_id"),
            "exchange": selected.get("exchange"),
            "candidate_security_ids": sorted(str(row["security_id"]) for row in candidates),
            "source_etf_ids": sorted({str(row.get("etf_id")) for row in source_rows if row.get("etf_id")}),
            "source_exposure_count": len(source_rows),
        }
        records.append(record)
        status_counts[status] += 1
        reason_counts[reason] += 1
        if not status.startswith("resolved_"):
            diagnostics.append({key: record[key] for key in ("holding_symbol", "market_suffix", "status", "reason_code", "candidate_security_ids", "source_etf_ids")})

    resolved = sum(count for status, count in status_counts.items() if status.startswith("resolved_"))
    return {
        "schema_version": "etf-security-identity-bridge.v031e.1",
        "version": "V031E.1B",
        "generated_at": current.isoformat(),
        "source_snapshot": {
            "snapshot_id": snapshot["state"]["current_snapshot_id"],
            "provider_generated_at": snapshot["state"]["provider_generated_at"],
            "holdings_index_sha256": snapshot["state"]["holdings_index_sha256"],
            "holdings_coverage": snapshot["state"]["holdings_coverage"],
        },
        "summary": {
            "holding_symbol_count": len(records),
            "resolved_symbol_count": resolved,
            "unresolved_symbol_count": len(records) - resolved,
            "resolved_company_count": len({row["company_id"] for row in records if row.get("company_id")}),
            "resolved_exposure_count": sum(row["source_exposure_count"] for row in records if row["status"].startswith("resolved_")),
            "unresolved_exposure_count": sum(row["source_exposure_count"] for row in records if not row["status"].startswith("resolved_")),
            "status_counts": dict(sorted(status_counts.items())),
            "reason_code_counts": dict(sorted(reason_counts.items())),
            "name_based_matching_used": False,
            "valuation_readiness_consumed": False,
        },
        "records": records,
        "diagnostics": diagnostics,
        "indexes": {
            "holding_symbol_to_position": {row["holding_symbol"]: index for index, row in enumerate(records)},
            "company_id_to_holding_symbols": {
                company_id: sorted(row["holding_symbol"] for row in records if row.get("company_id") == company_id)
                for company_id in sorted({str(row["company_id"]) for row in records if row.get("company_id")})
            },
        },
    }


def write_etf_identity_bridge(report: Mapping[str, Any], output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "identity_bridge.json": report,
        "diagnostics.json": {
            "schema_version": "etf-security-identity-diagnostics.v031e.1",
            "version": report["version"],
            "generated_at": report["generated_at"],
            "source_snapshot": report["source_snapshot"],
            "summary": report["summary"],
            "diagnostics": report["diagnostics"],
        },
        "manifest.json": {
            "schema_version": report["schema_version"],
            "version": report["version"],
            "generated_at": report["generated_at"],
            "source_snapshot": report["source_snapshot"],
            "summary": report["summary"],
        },
    }
    for name, payload in outputs.items():
        temporary = output_root / f".{name}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output_root / name)
