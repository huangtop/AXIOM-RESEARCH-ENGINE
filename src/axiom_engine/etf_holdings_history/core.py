from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import date as date_type, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from axiom_engine.etf_engine_adapter import load_cached_etf_engine_snapshot


class ETFHoldingsHistoryError(RuntimeError):
    pass


def _load(path: Path, default: Any = None) -> Any:
    if not path.is_file() and default is not None:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ETFHoldingsHistoryError(f"cannot read {path}: {exc}") from exc


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _number(row: Mapping[str, Any], names: tuple[str, ...]) -> float | None:
    for name in names:
        value = row.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _per_fund(holdings_index: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    funds: dict[str, dict[str, Any]] = {}
    for symbol, raw_rows in holdings_index.items():
        for raw in raw_rows:
            etf_id = str(raw.get("etf_id") or "")
            if not etf_id.startswith("US-"):
                continue
            fund = funds.setdefault(etf_id, {
                "etf_id": etf_id,
                "etf_ticker": etf_id.removeprefix("US-"),
                "etf_name": raw.get("name"),
                "holdings": {},
            })
            fund["holdings"][str(symbol).upper()] = {
                "holding_symbol": str(symbol).upper(),
                "weight": _number(raw, ("weight",)),
                "shares": _number(raw, ("shares", "holding_shares", "shares_held")),
            }
    return funds


def _snapshot_date(generated_at: str) -> str:
    try:
        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ETFHoldingsHistoryError("provider generated_at is invalid") from exc
    return parsed.date().isoformat()


def _history_snapshots(root: Path, excluding: str) -> list[Path]:
    snapshots = root / "snapshots"
    if not snapshots.is_dir():
        return []
    return sorted((path for path in snapshots.iterdir() if path.is_dir() and path.name != excluding), reverse=True)


def _prune_snapshots(root: Path, *, latest_date: str, retention_days: int) -> list[str]:
    if retention_days < 1:
        raise ETFHoldingsHistoryError("history_retention_days must be positive")
    try:
        cutoff = date_type.fromisoformat(latest_date) - timedelta(days=retention_days - 1)
    except ValueError as exc:
        raise ETFHoldingsHistoryError("latest ETF snapshot date is invalid") from exc
    removed: list[str] = []
    snapshots = root / "snapshots"
    for path in snapshots.iterdir() if snapshots.is_dir() else ():
        if not path.is_dir():
            continue
        try:
            snapshot_date = date_type.fromisoformat(path.name)
        except ValueError:
            continue
        if snapshot_date < cutoff:
            shutil.rmtree(path)
            removed.append(path.name)
    return sorted(removed)


def _load_funds(snapshot_root: Path) -> dict[str, dict[str, Any]]:
    manifest = _load(snapshot_root / "manifest.json")
    funds: dict[str, dict[str, Any]] = {}
    for etf_id, filename in manifest.get("fund_files", {}).items():
        payload = _load(snapshot_root / "funds" / filename)
        funds[etf_id] = {**payload, "holdings": {row["holding_symbol"]: row for row in payload.get("holdings", [])}}
    return funds


def _event_type(previous: Mapping[str, Any] | None, current: Mapping[str, Any] | None) -> str | None:
    if previous is None:
        return "ENTERED_TOP_HOLDINGS"
    if current is None:
        return "EXITED_TOP_HOLDINGS"
    delta = (current.get("weight") or 0.0) - (previous.get("weight") or 0.0)
    if abs(delta) < 1e-12:
        previous_shares, current_shares = previous.get("shares"), current.get("shares")
        if previous_shares is None or current_shares is None or previous_shares == current_shares:
            return None
        return "SHARES_INCREASED" if current_shares > previous_shares else "SHARES_DECREASED"
    return "WEIGHT_INCREASED" if delta > 0 else "WEIGHT_DECREASED"


def build_etf_holdings_history(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    source = load_cached_etf_engine_snapshot(root / "data/generated/provider_cache/etf_engine_v2")
    generated_at = str(source["manifest"]["generated_at"])
    date = _snapshot_date(generated_at)
    output = root / "data/generated/canonical_etf_holdings_history"
    current_root = output / "snapshots" / date
    funds = _per_fund(source["holdings_index"])
    digest = str(source["state"]["holdings_index_sha256"])
    history_index = _load(output / "index.json", {})
    if history_index.get("latest_date") == date and history_index.get("latest_manifest", {}).get("source_sha256") == digest:
        return {"snapshot": history_index["latest_manifest"], "summary": {"status": "unchanged", "baseline_only": False}, "events": [], "triggers": []}
    existing = _load(current_root / "manifest.json", {})
    superseded_digest = None
    if existing and existing.get("source_sha256") != digest:
        # Providers may correct a top-holdings payload later on the same day.
        # The dated slot represents the latest authoritative payload for that
        # provider day; replace it atomically and retain the superseded digest
        # in the manifest so the correction remains auditable.
        superseded_digest = existing.get("source_sha256")
        shutil.rmtree(current_root)

    fund_files: dict[str, str] = {}
    for etf_id, fund in sorted(funds.items()):
        filename = f"{etf_id}.json"
        fund_files[etf_id] = filename
        _write(current_root / "funds" / filename, {
            "schema_version": "canonical-etf-fund-holdings.v031e.6",
            "provider_generated_at": generated_at,
            "coverage": "top_holdings_only",
            **{key: fund[key] for key in ("etf_id", "etf_ticker", "etf_name")},
            "holdings": sorted(fund["holdings"].values(), key=lambda row: row["holding_symbol"]),
        })
    snapshot_manifest = {
        "schema_version": "canonical-etf-holdings-snapshot.v031e.6",
        "snapshot_date": date,
        "provider_generated_at": generated_at,
        "source_snapshot_id": source["state"]["current_snapshot_id"],
        "source_sha256": digest,
        "supersedes_source_sha256": superseded_digest,
        "coverage": "top_holdings_only",
        "fund_count": len(funds),
        "fund_files": fund_files,
    }
    _write(current_root / "manifest.json", snapshot_manifest)

    previous_paths = _history_snapshots(output, date)
    previous_root = previous_paths[0] if previous_paths else None
    previous_funds = _load_funds(previous_root) if previous_root else {}
    identities_payload = _load(root / "data/generated/etf_identity_bridge/identity_bridge.json")
    identities = {str(row.get("holding_symbol") or "").upper(): row for row in identities_payload.get("records", [])}
    catalog = _load(root / "data/generated/publication_gate/company_catalog.json", {"companies": []})
    publication = {str(row.get("company_id")): row for row in catalog.get("companies", [])}
    config = _load(root / "config/etf_holdings_refresh.v031e.6.json")
    retention_days = int(config.get("history_retention_days", 90))
    material_weight = float(config["materiality"]["absolute_weight_change"])
    material_shares = float(config["materiality"]["relative_share_change"])
    focus_etfs = [f"US-{ticker}" for ticker in config.get("focus_etfs", [])]
    events, diagnostics = [], []
    company_observations: dict[str, list[dict[str, Any]]] = {}
    for etf_id in sorted(set(funds) | set(previous_funds)):
        current_holdings = funds.get(etf_id, {}).get("holdings", {})
        previous_holdings = previous_funds.get(etf_id, {}).get("holdings", {})
        for symbol in sorted(set(current_holdings) | set(previous_holdings)):
            before, after = previous_holdings.get(symbol), current_holdings.get(symbol)
            change_type = _event_type(before, after)
            if not change_type:
                continue
            identity = identities.get(symbol)
            if not identity or not str(identity.get("status", "")).startswith("resolved_"):
                diagnostics.append({"etf_id": etf_id, "holding_symbol": symbol, "reason_code": "SECURITY_IDENTITY_NOT_FOUND"})
                continue
            previous_weight = before.get("weight") if before else None
            current_weight = after.get("weight") if after else None
            delta_weight = (current_weight or 0.0) - (previous_weight or 0.0)
            previous_shares = before.get("shares") if before else None
            current_shares = after.get("shares") if after else None
            delta_shares = None if previous_shares is None or current_shares is None else current_shares - previous_shares
            share_ratio = 0.0 if delta_shares is None or not previous_shares else abs(delta_shares / previous_shares)
            material = change_type in {"ENTERED_TOP_HOLDINGS", "EXITED_TOP_HOLDINGS"} or abs(delta_weight) >= material_weight or share_ratio >= material_shares
            company_id = identity["company_id"]
            if publication.get(company_id, {}).get("research_scope") != "core":
                continue
            event_key = f"{date}|{etf_id}|{symbol}|{change_type}"
            event = {
                "canonical_event_id": "etf-change:" + hashlib.sha256(event_key.encode()).hexdigest()[:24],
                "source_event_id": None,
                "etf_id": etf_id,
                "etf_ticker": etf_id.removeprefix("US-"),
                "holding_symbol": symbol,
                "security_id": identity["security_id"],
                "company_id": company_id,
                "change_type": change_type,
                "previous_weight": previous_weight,
                "current_weight": current_weight,
                "delta_weight": delta_weight,
                "previous_shares": previous_shares,
                "current_shares": current_shares,
                "delta_shares": delta_shares,
                "shares_status": "available" if delta_shares is not None else "not_provided_by_source",
                "previous_observed_at": previous_root.name if previous_root else None,
                "current_observed_at": date,
                "material": material,
                "coverage": "top_holdings_only",
                "official_membership_change": False,
                "source": "ETF-ENGINE-V2 daily snapshot diff",
            }
            events.append(event)
            company_observations.setdefault(company_id, []).append(event)

    events.sort(key=lambda row: (row["company_id"], row["etf_id"], row["change_type"]))
    company_ids = sorted({row["company_id"] for row in events})
    etf_ids = sorted({row["etf_id"] for row in events})
    canonical_root = root / "data/generated/canonical_etf_change_events"
    per_company_files: dict[str, str] = {}
    all_symbols = {symbol for fund in funds.values() for symbol in fund["holdings"]} | {symbol for fund in previous_funds.values() for symbol in fund["holdings"]}
    for symbol in sorted(all_symbols):
        identity = identities.get(symbol)
        if not identity or not str(identity.get("status", "")).startswith("resolved_"):
            continue
        company_id = identity["company_id"]
        if publication.get(company_id, {}).get("research_scope") != "core":
            continue
        company_events = company_observations.get(company_id, [])
        status_rows = []
        for etf_id in sorted((set(funds) | set(previous_funds)) if company_events else focus_etfs):
            before = previous_funds.get(etf_id, {}).get("holdings", {}).get(symbol)
            after = funds.get(etf_id, {}).get("holdings", {}).get(symbol)
            if before is None and after is None and etf_id not in focus_etfs:
                continue
            status_rows.append({
                "etf_id": etf_id, "etf_ticker": etf_id.removeprefix("US-"),
                "previous": before, "current": after,
                "observation_status": "observed" if before is not None or after is not None else "not_observed_in_top_holdings",
            })
        filename = f"{symbol}.json"
        per_company_files[company_id] = filename
        _write(canonical_root / "per-company" / filename, {
            "schema_version": "canonical-company-etf-changes.v031e.6",
            "company_id": company_id, "ticker": symbol,
            "comparison": {"previous_date": previous_root.name if previous_root else None, "current_date": date},
            "coverage": "top_holdings_only",
            "events": company_events,
            "fund_observations": status_rows,
        })

    triggers = []
    for event in events:
        scope = publication.get(event["company_id"], {}).get("scope_axes", {})
        research_company = bool(scope.get("research_page") or scope.get("news_ai") or scope.get("etf_change_analysis"))
        if event["material"] and research_company:
            triggers.append({
                "trigger_id": event["canonical_event_id"], "trigger_type": "etf_change",
                "company_id": event["company_id"], "ticker": event["holding_symbol"],
                "event_id": event["canonical_event_id"], "observed_at": date,
                "reason_code": "MATERIAL_ETF_CHANGE_FOR_RESEARCH_COMPANY",
            })
    indexes = {
        "company_id_to_event_positions": {cid: [i for i, row in enumerate(events) if row["company_id"] == cid] for cid in company_ids},
        "etf_id_to_event_positions": {eid: [i for i, row in enumerate(events) if row["etf_id"] == eid] for eid in etf_ids},
        "company_id_to_file": per_company_files,
    }
    summary = {"canonical_event_count": len(events), "company_count": len(company_ids), "etf_count": len(etf_ids), "trigger_count": len(triggers), "baseline_only": previous_root is None}
    _write(canonical_root / "events.json", events)
    _write(canonical_root / "indexes.json", indexes)
    _write(canonical_root / "coverage_audit.json", {"summary": summary, "diagnostics": diagnostics})
    _write(canonical_root / "manifest.json", {"schema_version": "canonical-etf-change-events.v031e.3", "version": "V031E.6", "generated_at": current_time.isoformat(), "source_snapshot": snapshot_manifest, "summary": summary})
    _write(root / "data/generated/event_triggers/etf_changes.json", {"schema_version": "axiom-event-triggers.v1", "generated_at": current_time.isoformat(), "trigger_type": "etf_change", "events": triggers})
    pruned_snapshots = _prune_snapshots(output, latest_date=date, retention_days=retention_days)
    retained_snapshots = [date] + [
        path.name for path in _history_snapshots(output, date)
    ]
    _write(output / "index.json", {"schema_version": "canonical-etf-holdings-history-index.v031e.6", "latest_date": date, "previous_date": previous_root.name if previous_root else None, "snapshots": retained_snapshots, "history_retention_days": retention_days, "pruned_snapshots": pruned_snapshots, "latest_manifest": snapshot_manifest})
    return {"snapshot": snapshot_manifest, "summary": summary, "events": events, "triggers": triggers}
