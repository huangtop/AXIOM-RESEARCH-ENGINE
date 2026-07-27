from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


class HistoricalMultipleBenchmarkError(RuntimeError):
    pass


SUPPORTED_METHODS = {
    "forward_pe", "trailing_pe", "price_to_sales", "ev_to_sales", "ev_to_ebitda", "fcf_yield",
}
CONFIDENCE_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise HistoricalMultipleBenchmarkError(f"required input not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HistoricalMultipleBenchmarkError(f"invalid JSON: {path}") from exc


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _minimum_confidence(*values: str) -> str:
    normalized = [value if value in CONFIDENCE_RANK else "none" for value in values]
    return min(normalized, key=lambda value: CONFIDENCE_RANK[value])


def _history_confidence(observation_count: int, medium_threshold: int, high_threshold: int) -> str:
    if observation_count >= high_threshold:
        return "high"
    if observation_count >= medium_threshold:
        return "medium"
    return "low"


def _select_window(windows: Sequence[Mapping[str, Any]], preference: Sequence[str]) -> Mapping[str, Any] | None:
    by_name = {str(row.get("window")): row for row in windows if isinstance(row, Mapping)}
    for name in preference:
        row = by_name.get(name)
        if row and row.get("statistics_state") == "ready":
            return row
    return None


def build_historical_multiple_benchmark(
    repository_root: Path,
    *,
    statistics_path: str = "data/generated/historical_multiple_statistics/historical_multiple_statistics.json",
    window_preference: Sequence[str] = ("252d", "60d", "20d", "all"),
    benchmark_statistic: str = "median",
    lower_bound_statistic: str = "p25",
    upper_bound_statistic: str = "p75",
    medium_confidence_observations: int = 60,
    high_confidence_observations: int = 252,
) -> dict[str, Any]:
    if not window_preference:
        raise HistoricalMultipleBenchmarkError("window_preference must not be empty")
    if medium_confidence_observations < 2 or high_confidence_observations < medium_confidence_observations:
        raise HistoricalMultipleBenchmarkError("invalid confidence observation thresholds")

    source = _load_json(repository_root / statistics_path)
    if not isinstance(source, Mapping) or source.get("schema_version") != "historical-multiple-statistics.v030.13.2":
        raise HistoricalMultipleBenchmarkError("unsupported historical multiple statistics schema")
    source_records = source.get("statistics")
    if not isinstance(source_records, list):
        raise HistoricalMultipleBenchmarkError("historical multiple statistics must be an array")

    records: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for raw in source_records:
        if not isinstance(raw, Mapping):
            diagnostics.append({"reason": "statistics_record_not_object"})
            continue
        company_id = str(raw.get("company_id") or "")
        method = str(raw.get("method") or "")
        if not company_id or method not in SUPPORTED_METHODS:
            diagnostics.append({"company_id": company_id or None, "method": method or None, "reason": "invalid_statistics_contract"})
            continue
        windows = raw.get("windows")
        if not isinstance(windows, list):
            diagnostics.append({"company_id": company_id, "method": method, "reason": "windows_not_array"})
            continue
        selected = _select_window(windows, window_preference)
        base = {
            "company_id": company_id,
            "primary_symbol": raw.get("primary_symbol"),
            "display_name": raw.get("display_name"),
            "method": method,
            "metric_name": raw.get("metric_name"),
            "latest_observation_date": raw.get("latest_observation_date"),
            "latest_value": raw.get("latest_value"),
            "source_confidence": raw.get("confidence"),
            "formula_version": raw.get("formula_version"),
            "source_formula_version": raw.get("source_formula_version"),
        }
        if selected is None:
            records.append({**base, "status": "insufficient_history", "confidence": "none", "reason": "no_ready_statistics_window", "selected_window": None, "observation_count": 0, "benchmark": {}})
            continue
        stats = selected.get("statistics")
        if not isinstance(stats, Mapping):
            records.append({**base, "status": "invalid", "confidence": "none", "reason": "selected_window_statistics_missing", "selected_window": selected.get("window"), "observation_count": selected.get("usable_observation_count", 0), "benchmark": {}})
            diagnostics.append({"company_id": company_id, "method": method, "reason": "selected_window_statistics_missing"})
            continue
        target = _finite(stats.get(benchmark_statistic))
        lower = _finite(stats.get(lower_bound_statistic))
        upper = _finite(stats.get(upper_bound_statistic))
        if target is None or lower is None or upper is None or lower > target or target > upper:
            records.append({**base, "status": "invalid", "confidence": "none", "reason": "invalid_benchmark_statistics", "selected_window": selected.get("window"), "observation_count": selected.get("usable_observation_count", 0), "benchmark": {}})
            diagnostics.append({"company_id": company_id, "method": method, "reason": "invalid_benchmark_statistics"})
            continue
        count = int(selected.get("usable_observation_count") or 0)
        history_confidence = _history_confidence(count, medium_confidence_observations, high_confidence_observations)
        confidence = _minimum_confidence(str(raw.get("confidence") or "none"), history_confidence)
        target_name = "target_yield_percent" if method == "fcf_yield" else "target_multiple"
        records.append({
            **base,
            "status": "ready",
            "confidence": confidence,
            "history_confidence": history_confidence,
            "reason": "preferred_ready_window_selected",
            "selected_window": selected.get("window"),
            "observation_count": count,
            "first_observation_date": selected.get("first_observation_date"),
            "benchmark": {
                target_name: target,
                "lower_bound": lower,
                "upper_bound": upper,
                "benchmark_statistic": benchmark_statistic,
                "lower_bound_statistic": lower_bound_statistic,
                "upper_bound_statistic": upper_bound_statistic,
            },
        })

    status_counts = {"ready": 0, "insufficient_history": 0, "invalid": 0}
    method_counts = {method: {"ready": 0, "insufficient_history": 0, "invalid": 0} for method in sorted(SUPPORTED_METHODS)}
    for row in records:
        status_counts[row["status"]] += 1
        method_counts[row["method"]][row["status"]] += 1
    return {
        "schema_version": "historical-multiple-benchmark.v030.13.3",
        "version": "V030.13.3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of_date": source.get("as_of_date"),
        "sources": {"statistics_path": statistics_path, "statistics_schema_version": source.get("schema_version")},
        "policy": {
            "window_preference": list(window_preference),
            "benchmark_statistic": benchmark_statistic,
            "lower_bound_statistic": lower_bound_statistic,
            "upper_bound_statistic": upper_bound_statistic,
            "medium_confidence_observations": medium_confidence_observations,
            "high_confidence_observations": high_confidence_observations,
            "insufficient_history_policy": "do_not_emit_benchmark",
        },
        "summary": {
            "company_count": len({row["company_id"] for row in records}),
            "method_count": len(SUPPORTED_METHODS),
            "benchmark_record_count": len(records),
            "ready_benchmark_count": status_counts["ready"],
            "insufficient_benchmark_count": status_counts["insufficient_history"],
            "invalid_benchmark_count": status_counts["invalid"],
            "diagnostic_count": len(diagnostics),
            "method_benchmark_counts": method_counts,
        },
        "benchmarks": records,
        "indexes": {"company_method_to_benchmark_position": {f"{row['company_id']}|{row['method']}": index for index, row in enumerate(records)}},
        "diagnostic": {"issues": diagnostics},
    }


def write_historical_multiple_benchmark(report: Mapping[str, Any], output_path: Path, diagnostic_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    diagnostic_path.write_text(json.dumps({
        "schema_version": "historical-multiple-benchmark-diagnostic.v030.13.3",
        "version": "V030.13.3",
        "generated_at": report.get("generated_at"),
        "summary": report.get("summary"),
        "issues": report.get("diagnostic", {}).get("issues", []),
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
