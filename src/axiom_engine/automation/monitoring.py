from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

MONITORING_SCHEMA_VERSION = "automation-monitoring.v030.8.5"
METRICS_SCHEMA_VERSION = "automation-metrics.v030.8.5"
TREND_SCHEMA_VERSION = "automation-trends.v030.8.5"
VERSION = "V030.8.5"
SUCCESS_STATUSES = {"completed", "completed_with_warnings"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _find_numeric(payload: Any, keys: Iterable[str]) -> float | int | None:
    wanted = set(keys)
    if isinstance(payload, Mapping):
        for key in wanted:
            value = _number(payload.get(key))
            if value is not None:
                return value
        for value in payload.values():
            found = _find_numeric(value, wanted)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_numeric(value, wanted)
            if found is not None:
                return found
    return None


def collect_operational_snapshot(repository_root: Path) -> dict[str, Any]:
    root = repository_root.resolve()
    candidates = [
        root / "data/generated/production_refresh/refresh_report.json",
        root / "data/generated/production_refresh/provider_delivery_reconciliation.json",
        root / "data/generated/valuation_readiness/readiness_report.json",
        root / "data/generated/valuation_readiness/latest.json",
        root / "data/generated/population_manifest/population_manifest.json",
    ]
    documents = [doc for path in candidates if (doc := _read_json(path)) is not None]
    coverage = None
    ready = None
    for doc in documents:
        if coverage is None:
            coverage = _find_numeric(doc, ("coverage_pct", "coverage_percent", "overall_coverage_pct", "coverage"))
        if ready is None:
            ready = _find_numeric(doc, ("ready_company_count", "ready_count", "valuation_ready_count", "immediate_ready_count"))
    return {
        "captured_at": utc_now(),
        "coverage_pct": coverage,
        "ready_company_count": ready,
    }


def _history_files(history_dir: Path) -> list[Path]:
    return sorted(history_dir.glob("*.json"), key=lambda p: p.name)


def load_history(history_dir: Path, limit: int | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in _history_files(history_dir):
        value = _read_json(path)
        if value is not None:
            records.append(value)
    records.sort(key=lambda item: str(item.get("finished_at") or item.get("started_at") or ""))
    return records[-limit:] if limit else records


def build_metrics(history: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    runs = list(history)
    total = len(runs)
    successful = sum(run.get("status") in SUCCESS_STATUSES for run in runs)
    failed = sum(run.get("status") in {"failed", "interrupted", "timed_out"} for run in runs)
    durations = [int(run.get("duration_ms", 0) or 0) for run in runs]
    stage_durations: dict[str, list[int]] = defaultdict(list)
    stage_failures: Counter[str] = Counter()
    failure_reasons: Counter[str] = Counter()
    skipped_refresh = 0
    last_failure_at = None
    for run in runs:
        if run.get("status") in {"failed", "interrupted", "timed_out"}:
            last_failure_at = run.get("finished_at") or run.get("started_at")
        for stage in run.get("stages", []):
            name = str(stage.get("name", "unknown"))
            stage_durations[name].append(int(stage.get("duration_ms", 0) or 0))
            if stage.get("status") == "failed":
                stage_failures[name] += 1
                failure_reasons[str(stage.get("error") or f"returncode_{stage.get('returncode')}")] += 1
            if name == "production_refresh" and stage.get("status") == "skipped":
                skipped_refresh += 1
    return {
        "schema_version": METRICS_SCHEMA_VERSION,
        "version": VERSION,
        "generated_at": utc_now(),
        "total_runs": total,
        "successful_runs": successful,
        "failed_runs": failed,
        "success_rate": round(successful * 100 / total, 4) if total else 0.0,
        "average_duration_ms": round(sum(durations) / total) if total else 0,
        "average_stage_duration_ms": {
            name: round(sum(values) / len(values)) for name, values in sorted(stage_durations.items())
        },
        "stage_failure_count": dict(sorted(stage_failures.items())),
        "failure_reason_count": dict(sorted(failure_reasons.items())),
        "skipped_production_refresh_runs": skipped_refresh,
        "last_failure_at": last_failure_at,
    }


def build_trends(history: Iterable[Mapping[str, Any]], window: int = 30) -> dict[str, Any]:
    runs = list(history)[-window:]
    points = []
    for run in runs:
        operations = run.get("operations", {}) if isinstance(run.get("operations"), Mapping) else {}
        points.append({
            "run_id": run.get("run_id"),
            "finished_at": run.get("finished_at"),
            "status": run.get("status"),
            "duration_ms": run.get("duration_ms", 0),
            "coverage_pct": operations.get("coverage_pct"),
            "ready_company_count": operations.get("ready_company_count"),
            "production_refresh_status": next(
                (s.get("status") for s in run.get("stages", []) if s.get("name") == "production_refresh"), None
            ),
        })
    return {
        "schema_version": TREND_SCHEMA_VERSION,
        "version": VERSION,
        "generated_at": utc_now(),
        "window": window,
        "point_count": len(points),
        "points": points,
    }


def record_automation_run(
    repository_root: Path,
    report: Mapping[str, Any],
    output_dir: Path,
    *,
    history_limit: int = 100,
    trend_window: int = 30,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    history_dir = output_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    enriched = dict(report)
    enriched["monitoring_schema_version"] = MONITORING_SCHEMA_VERSION
    enriched["operations"] = collect_operational_snapshot(repository_root)
    token = str(enriched.get("run_id", "unknown")).replace(":", "-")
    history_path = history_dir / f"{token}.json"
    _atomic_write_json(history_path, enriched)

    files = _history_files(history_dir)
    for old in files[:-history_limit] if history_limit > 0 else []:
        old.unlink(missing_ok=True)
    history = load_history(history_dir)
    metrics = build_metrics(history)
    trends = build_trends(history, window=trend_window)
    _atomic_write_json(output_dir / "automation_metrics.json", metrics)
    _atomic_write_json(output_dir / "automation_trends.json", trends)
    _atomic_write_json(output_dir / "latest_monitored_run.json", enriched)
    return {"history_path": str(history_path), "metrics": metrics, "trends": trends}


def format_automation_status(output_dir: Path) -> str:
    latest = _read_json(output_dir / "latest_monitored_run.json") or _read_json(output_dir / "latest.json") or {}
    metrics = _read_json(output_dir / "automation_metrics.json") or {}
    operations = latest.get("operations", {}) if isinstance(latest.get("operations"), Mapping) else {}
    refresh_status = next(
        (stage.get("status") for stage in latest.get("stages", []) if stage.get("name") == "production_refresh"),
        "unknown",
    )
    duration_ms = int(latest.get("duration_ms", 0) or 0)
    status = str(latest.get("status", "no_runs")).upper()
    coverage = operations.get("coverage_pct")
    ready = operations.get("ready_company_count")
    lines = [
        "========================",
        "AXIOM Automation V030.8.5",
        "========================",
        f"Latest Run: {status}",
        f"Run ID: {latest.get('run_id', '-')}",
        f"Duration: {duration_ms / 1000:.3f} sec",
        f"Stages: {latest.get('completed_stage_count', 0)} completed / {latest.get('stage_count', 0)} total",
        f"Production Refresh: {refresh_status}",
        f"Coverage: {coverage if coverage is not None else 'n/a'}",
        f"Ready Companies: {ready if ready is not None else 'n/a'}",
        f"Success Rate: {metrics.get('success_rate', 0.0)}%",
        f"Average Runtime: {int(metrics.get('average_duration_ms', 0) or 0) / 1000:.3f} sec",
        f"Total Runs: {metrics.get('total_runs', 0)}",
        f"Last Failure: {metrics.get('last_failure_at') or 'none'}",
        "========================",
    ]
    return "\n".join(lines)
