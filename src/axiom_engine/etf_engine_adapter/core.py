from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


class ETFEngineAdapterError(RuntimeError):
    pass


class ETFEngineContractError(ETFEngineAdapterError):
    pass


Fetcher = Callable[[str], bytes]


def _download(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AXIOM-Research-ETF-Adapter/1.0", "Accept-Encoding": "identity"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def _decode_json(raw: bytes, *, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ETFEngineContractError(f"invalid {label} JSON: {exc}") from exc


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ETFEngineAdapterError(f"cannot read {path}: {exc}") from exc


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)


def _validate_source_config(config: Mapping[str, Any]) -> None:
    if config.get("schema_version") != "etf-engine-source-contract.v031e.1":
        raise ETFEngineContractError("unsupported ETF Engine source contract")
    if config.get("source_mode") != "read_only":
        raise ETFEngineContractError("ETF Engine source must be read-only")
    base_url = str(config.get("base_url") or "")
    if not base_url.startswith("https://"):
        raise ETFEngineContractError("ETF Engine base_url must use HTTPS")
    if float(config.get("cache_ttl_hours") or 0) <= 0:
        raise ETFEngineContractError("cache_ttl_hours must be positive")


def _validate_manifest(payload: Any, config: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ETFEngineContractError("ETF Engine manifest must be an object")
    if str(payload.get("schema_version") or "") != str(config["required_provider_schema_version"]):
        raise ETFEngineContractError("ETF Engine manifest schema version mismatch")
    required_counts = ("etf_count", "holding_symbols", "overlap_pairs")
    if any(not isinstance(payload.get(key), int) or int(payload[key]) < 0 for key in required_counts):
        raise ETFEngineContractError("ETF Engine manifest counts are invalid")
    markets = payload.get("markets")
    if not isinstance(markets, Mapping) or any(not isinstance(value, int) or value < 0 for value in markets.values()):
        raise ETFEngineContractError("ETF Engine manifest markets are invalid")
    generated_at = str(payload.get("generated_at") or "")
    try:
        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ETFEngineContractError("ETF Engine manifest generated_at is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ETFEngineContractError("ETF Engine manifest generated_at must be timezone-aware")
    return payload


def _validate_holdings_index(payload: Any) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ETFEngineContractError("ETF Engine holdings index must be an object")
    for symbol, rows in payload.items():
        if not str(symbol).strip() or not isinstance(rows, list):
            raise ETFEngineContractError("ETF Engine holdings index symbol entry is invalid")
        for row in rows:
            if not isinstance(row, Mapping) or not row.get("etf_id") or not row.get("ticker"):
                raise ETFEngineContractError(f"ETF Engine holding record is invalid: {symbol}")
            weight = row.get("weight")
            if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not 0 <= float(weight) <= 1:
                raise ETFEngineContractError(f"ETF Engine holding weight is invalid: {symbol}")
    return payload


def _snapshot_id(manifest: Mapping[str, Any], digest: str) -> str:
    timestamp = re.sub(r"[^0-9]", "", str(manifest["generated_at"]))[:14]
    return f"{timestamp}-{digest[:12]}"


def _cache_state(cache_root: Path) -> Mapping[str, Any] | None:
    path = cache_root / "state.json"
    return _load_json(path) if path.is_file() else None


def load_cached_etf_engine_snapshot(cache_root: Path) -> dict[str, Any]:
    state = _cache_state(cache_root)
    if not state or not state.get("current_snapshot_id"):
        raise ETFEngineAdapterError("ETF Engine cache is unavailable")
    snapshot_root = cache_root / "snapshots" / str(state["current_snapshot_id"])
    manifest_path = snapshot_root / "manifest.json"
    holdings_path = snapshot_root / "holdings_index.json"
    if not manifest_path.is_file() or not holdings_path.is_file():
        raise ETFEngineAdapterError("ETF Engine current cache snapshot is incomplete")
    return {
        "state": state,
        "manifest": _load_json(manifest_path),
        "holdings_index": _load_json(holdings_path),
        "snapshot_root": snapshot_root,
    }


def sync_etf_engine_cache(
    root: Path,
    *,
    config_path: str = "config/etf_engine_source.v031e.1.json",
    cache_path: str = "data/generated/provider_cache/etf_engine_v2",
    allow_live: bool = False,
    force: bool = False,
    now: datetime | None = None,
    fetcher: Fetcher = _download,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    config = _load_json(root / config_path)
    _validate_source_config(config)
    cache_root = root / cache_path
    previous = _cache_state(cache_root)
    ttl = timedelta(hours=float(config["cache_ttl_hours"]))
    if previous and not force:
        checked_at = datetime.fromisoformat(str(previous["checked_at"]).replace("Z", "+00:00"))
        if current - checked_at < ttl:
            return {"status": "cache_fresh", "used_last_known_good": False, "state": previous}
    if not allow_live:
        if previous:
            return {"status": "cache_stale_live_disabled", "used_last_known_good": True, "state": previous}
        return {"status": "unavailable_live_disabled", "used_last_known_good": False, "state": None}

    base_url = str(config["base_url"]).rstrip("/")
    manifest_url = f"{base_url}/{str(config['manifest_path']).lstrip('/')}"
    holdings_url = f"{base_url}/{str(config['holdings_index_path']).lstrip('/')}"
    try:
        manifest_raw = fetcher(manifest_url)
        manifest = _validate_manifest(_decode_json(manifest_raw, label="manifest"), config)
        manifest_digest = _sha256(manifest_raw)
        if previous and previous.get("manifest_sha256") == manifest_digest:
            updated = {**previous, "checked_at": current.isoformat(), "status": "unchanged"}
            _atomic_write(cache_root / "state.json", _json_bytes(updated))
            return {"status": "unchanged", "used_last_known_good": False, "state": updated}
        holdings_raw = fetcher(holdings_url)
        holdings = _validate_holdings_index(_decode_json(holdings_raw, label="holdings index"))
        if len(holdings) != int(manifest["holding_symbols"]):
            raise ETFEngineContractError("holdings index symbol count does not match manifest")
        holdings_digest = _sha256(holdings_raw)
        snapshot_id = _snapshot_id(manifest, manifest_digest)
        snapshot_root = cache_root / "snapshots" / snapshot_id
        _atomic_write(snapshot_root / "manifest.json", _json_bytes(manifest))
        _atomic_write(snapshot_root / "holdings_index.json", _json_bytes(holdings))
        state = {
            "schema_version": "etf-engine-cache-state.v031e.1",
            "provider_id": config["provider_id"],
            "source_mode": "read_only",
            "source_repository": config["repository"],
            "current_snapshot_id": snapshot_id,
            "provider_generated_at": manifest["generated_at"],
            "checked_at": current.isoformat(),
            "cached_at": current.isoformat(),
            "status": "updated",
            "manifest_sha256": manifest_digest,
            "holdings_index_sha256": holdings_digest,
            "manifest_url": manifest_url,
            "holdings_index_url": holdings_url,
            "holdings_coverage": config["holdings_coverage"],
            "summary": {
                "etf_count": manifest["etf_count"],
                "holding_symbols": manifest["holding_symbols"],
                "overlap_pairs": manifest["overlap_pairs"],
                "markets": manifest["markets"],
                "holding_exposure_count": sum(len(rows) for rows in holdings.values()),
            },
        }
        _atomic_write(cache_root / "state.json", _json_bytes(state))
        return {"status": "updated", "used_last_known_good": False, "state": state}
    except Exception as exc:
        if previous:
            fallback = {
                **previous,
                "checked_at": current.isoformat(),
                "status": "stale_fallback",
                "last_error": {"error_type": type(exc).__name__, "message": str(exc)},
            }
            _atomic_write(cache_root / "state.json", _json_bytes(fallback))
            return {"status": "stale_fallback", "used_last_known_good": True, "state": fallback}
        raise
