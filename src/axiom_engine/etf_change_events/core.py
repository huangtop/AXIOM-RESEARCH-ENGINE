from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


class ETFChangeEventError(RuntimeError):
    pass


Fetcher = Callable[[str], bytes]
EVENT_TYPES = {
    "ENTERED_TOP_HOLDINGS",
    "EXITED_TOP_HOLDINGS",
    "WEIGHT_INCREASED",
    "WEIGHT_DECREASED",
    "UNCHANGED",
}


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "AXIOM-Research-ETF-Adapter/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ETFChangeEventError(f"cannot read {path}: {exc}") from exc


def _decode(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ETFChangeEventError(f"invalid {label} JSON: {exc}") from exc


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _validate(config: Mapping[str, Any], manifest: Any, latest: Any) -> None:
    if config.get("schema_version") != "etf-engine-change-source-contract.v031e.3":
        raise ETFChangeEventError("unsupported ETF change source contract")
    if config.get("source_mode") != "read_only":
        raise ETFChangeEventError("ETF change source must be read-only")
    if not str(config.get("base_url") or "").startswith("https://"):
        raise ETFChangeEventError("ETF change source must use HTTPS")
    if not isinstance(manifest, Mapping) or not isinstance(latest, Mapping):
        raise ETFChangeEventError("ETF change documents must be objects")
    if manifest.get("schema_version") != config.get("required_provider_schema_version"):
        raise ETFChangeEventError("ETF change manifest schema mismatch")
    if manifest.get("coverage") != "top_holdings_only" or latest.get("coverage") != "top_holdings_only":
        raise ETFChangeEventError("ETF change coverage mismatch")
    if latest.get("selection") != "latest_transition_per_etf":
        raise ETFChangeEventError("unsupported ETF change selection")
    if not isinstance(latest.get("changes"), list):
        raise ETFChangeEventError("ETF latest changes must be a list")
    for event in latest["changes"]:
        if not isinstance(event, Mapping) or event.get("change_type") not in EVENT_TYPES:
            raise ETFChangeEventError("invalid ETF change event")
        if not event.get("event_id") or not event.get("etf_id") or not event.get("holding_symbol"):
            raise ETFChangeEventError("incomplete ETF change event")


def load_cached_etf_change_snapshot(cache_root: Path) -> dict[str, Any]:
    state = _load(cache_root / "state.json")
    snapshot = cache_root / "snapshots" / str(state.get("current_snapshot_id") or "")
    if not snapshot.is_dir():
        raise ETFChangeEventError("ETF change cache is incomplete")
    return {"state": state, "manifest": _load(snapshot / "manifest.json"), "latest": _load(snapshot / "latest_changes.json")}


def sync_etf_change_cache(
    root: Path,
    *,
    allow_live: bool = False,
    force: bool = False,
    now: datetime | None = None,
    fetcher: Fetcher = _download,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    config = _load(root / "config/etf_engine_changes.v031e.3.json")
    cache_root = root / "data/generated/provider_cache/etf_engine_v2_changes"
    state_path = cache_root / "state.json"
    previous = _load(state_path) if state_path.is_file() else None
    if previous and not force:
        checked = datetime.fromisoformat(str(previous["checked_at"]).replace("Z", "+00:00"))
        if current - checked < timedelta(hours=float(config["cache_ttl_hours"])):
            return {"status": "cache_fresh", "state": previous, "used_last_known_good": False}
    if not allow_live:
        return {"status": "cache_stale_live_disabled" if previous else "unavailable_live_disabled", "state": previous, "used_last_known_good": bool(previous)}
    base = str(config["base_url"]).rstrip("/")
    try:
        manifest_raw = fetcher(f"{base}/{config['manifest_path']}")
        latest_raw = fetcher(f"{base}/{config['latest_changes_path']}")
        manifest, latest = _decode(manifest_raw, "manifest"), _decode(latest_raw, "latest changes")
        _validate(config, manifest, latest)
        digest = hashlib.sha256(manifest_raw + b"\0" + latest_raw).hexdigest()
        snapshot_id = f"{str(manifest.get('generated_at') or 'unknown')[:10]}-{digest[:12]}"
        snapshot = cache_root / "snapshots" / snapshot_id
        _write(snapshot / "manifest.json", manifest)
        _write(snapshot / "latest_changes.json", latest)
        state = {
            "schema_version": "etf-change-cache-state.v031e.3",
            "current_snapshot_id": snapshot_id,
            "checked_at": current.isoformat(),
            "cached_at": current.isoformat(),
            "status": "updated",
            "source_repository": config["repository"],
            "content_sha256": digest,
            "provider_generated_at": manifest.get("generated_at"),
            "coverage": manifest["coverage"],
        }
        _write(state_path, state)
        return {"status": "updated", "state": state, "used_last_known_good": False}
    except Exception as exc:
        if previous:
            fallback = {**previous, "checked_at": current.isoformat(), "status": "stale_fallback", "last_error": str(exc)}
            _write(state_path, fallback)
            return {"status": "stale_fallback", "state": fallback, "used_last_known_good": True}
        raise


def build_canonical_etf_change_events(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    snapshot = load_cached_etf_change_snapshot(root / "data/generated/provider_cache/etf_engine_v2_changes")
    bridge = _load(root / "data/generated/etf_identity_bridge/identity_bridge.json")
    if bridge.get("schema_version") != "etf-security-identity-bridge.v031e.1":
        raise ETFChangeEventError("ETF identity bridge is unavailable")
    identities = {str(row.get("holding_symbol") or "").upper(): row for row in bridge.get("records", [])}
    events, diagnostics = [], []
    source_us_events = 0
    for raw in snapshot["latest"]["changes"]:
        etf_id = str(raw["etf_id"])
        if not etf_id.startswith("US-"):
            continue
        source_us_events += 1
        identity = identities.get(str(raw["holding_symbol"]).upper())
        if not identity or not str(identity.get("status") or "").startswith("resolved_"):
            diagnostics.append({"event_id": raw["event_id"], "etf_id": etf_id, "holding_symbol": raw["holding_symbol"], "reason_code": (identity or {}).get("reason_code") or "SECURITY_IDENTITY_NOT_FOUND"})
            continue
        events.append({
            "canonical_event_id": f"etf-change:{raw['event_id']}",
            "source_event_id": raw["event_id"],
            "etf_id": etf_id,
            "etf_ticker": etf_id.removeprefix("US-"),
            "holding_symbol": raw["holding_symbol"],
            "security_id": identity["security_id"],
            "company_id": identity["company_id"],
            "change_type": raw["change_type"],
            "previous_weight": raw.get("previous_weight"),
            "current_weight": raw.get("current_weight"),
            "delta_weight": raw.get("delta_weight"),
            "previous_observed_at": raw.get("previous_observed_at"),
            "current_observed_at": raw.get("current_observed_at"),
            "coverage": "top_holdings_only",
            "official_membership_change": False,
            "source": "ETF-ENGINE-V2",
        })
    events.sort(key=lambda row: (str(row["company_id"]), str(row["etf_id"]), str(row["change_type"])))
    company_ids = sorted({str(row["company_id"]) for row in events})
    etf_ids = sorted({str(row["etf_id"]) for row in events})
    return {
        "schema_version": "canonical-etf-change-events.v031e.3",
        "version": "V031E.3",
        "generated_at": current.isoformat(),
        "source_snapshot": snapshot["state"],
        "summary": {
            "source_us_event_count": source_us_events,
            "canonical_event_count": len(events),
            "unresolved_event_count": len(diagnostics),
            "company_count": len(company_ids),
            "etf_count": len(etf_ids),
            "change_type_counts": dict(sorted(Counter(row["change_type"] for row in events).items())),
            "non_us_events_excluded": len(snapshot["latest"]["changes"]) - source_us_events,
            "valuation_readiness_consumed": False,
        },
        "events": events,
        "diagnostics": diagnostics,
        "indexes": {
            "company_id_to_event_positions": {company_id: [i for i, row in enumerate(events) if row["company_id"] == company_id] for company_id in company_ids},
            "etf_id_to_event_positions": {etf_id: [i for i, row in enumerate(events) if row["etf_id"] == etf_id] for etf_id in etf_ids},
        },
    }


def write_canonical_etf_change_events(report: Mapping[str, Any], output_root: Path) -> None:
    for name, payload in {
        "events.json": report["events"],
        "indexes.json": report["indexes"],
        "coverage_audit.json": {"summary": report["summary"], "diagnostics": report["diagnostics"]},
        "manifest.json": {key: report[key] for key in ("schema_version", "version", "generated_at", "source_snapshot", "summary")},
    }.items():
        _write(output_root / name, payload)
