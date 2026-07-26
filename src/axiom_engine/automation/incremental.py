from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_symbols(value: Any, keys: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in keys and isinstance(item, str) and item.strip():
                found.add(item.strip().upper())
            found.update(_extract_symbols(item, keys))
    elif isinstance(value, list):
        for item in value:
            found.update(_extract_symbols(item, keys))
    return found


def build_input_snapshot(root: Path, patterns: Iterable[str], symbol_keys: Iterable[str]) -> dict[str, Any]:
    keys = {key.lower() for key in symbol_keys}
    files: list[dict[str, Any]] = []
    all_symbols: set[str] = set()
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            stat = path.stat()
            symbols: set[str] = set()
            if path.suffix.lower() == ".json":
                try:
                    symbols = _extract_symbols(json.loads(path.read_text(encoding="utf-8")), keys)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    symbols = set()
            all_symbols.update(symbols)
            files.append({
                "path": rel,
                "sha256": _sha256(path),
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "symbols": sorted(symbols),
            })
    dedup = {item["path"]: item for item in files}
    ordered = [dedup[key] for key in sorted(dedup)]
    return {"created_at": _utc_now(), "files": ordered, "symbols": sorted(all_symbols)}


def compare_snapshots(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    prev_files = {item["path"]: item for item in (previous or {}).get("files", [])}
    cur_files = {item["path"]: item for item in current.get("files", [])}
    added = sorted(set(cur_files) - set(prev_files))
    removed = sorted(set(prev_files) - set(cur_files))
    modified = sorted(
        path for path in set(prev_files) & set(cur_files)
        if prev_files[path].get("sha256") != cur_files[path].get("sha256")
    )
    changed_paths = added + modified + removed
    symbols: set[str] = set()
    for path in changed_paths:
        item = cur_files.get(path) or prev_files.get(path) or {}
        symbols.update(item.get("symbols", []))
    return {
        "changed": bool(changed_paths),
        "added_files": added,
        "modified_files": modified,
        "removed_files": removed,
        "changed_file_count": len(changed_paths),
        "affected_symbols": sorted(symbols),
        "affected_symbol_count": len(symbols),
    }


def plan_incremental_refresh(
    root: Path,
    config: dict[str, Any],
    output_dir: Path,
    *,
    force_full: bool = False,
    force_run: bool = False,
) -> dict[str, Any]:
    snapshot_path = output_dir / "incremental_input_snapshot.json"
    previous = None
    if snapshot_path.exists():
        try:
            previous = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None
    current = build_input_snapshot(
        root,
        config.get("watch_patterns", []),
        config.get("symbol_keys", ["symbol", "ticker"]),
    )
    delta = compare_snapshots(previous, current)
    targeted_supported = bool(config.get("targeted_refresh", {}).get("enabled", False))
    max_symbols = int(config.get("targeted_refresh", {}).get("max_symbols", 250))
    if force_full:
        mode, reason = "full", "forced_full_refresh"
    elif previous is None:
        mode, reason = "full", "baseline_snapshot_missing"
    elif not delta["changed"] and not force_run:
        mode, reason = "noop", "no_input_changes"
    elif targeted_supported and 0 < delta["affected_symbol_count"] <= max_symbols:
        mode, reason = "targeted", "bounded_symbol_change_set"
    else:
        mode, reason = "full", "targeted_refresh_unavailable_or_unbounded"
    report = {
        "schema_version": "incremental-refresh-plan.v030.8.4",
        "version": "V030.8.4",
        "created_at": _utc_now(),
        "mode": mode,
        "reason": reason,
        "targeted_refresh_supported": targeted_supported,
        **delta,
        "snapshot_path": str(snapshot_path),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(output_dir / "incremental_refresh_plan.json", report)
    _atomic_write_json(output_dir / "latest_incremental_plan.json", report)
    _atomic_write_json(snapshot_path, current)
    symbols_file = output_dir / "incremental_symbols.json"
    _atomic_write_json(symbols_file, {"symbols": delta["affected_symbols"]})
    report["symbols_file"] = str(symbols_file)
    return report
