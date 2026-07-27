from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


class HistoricalMultipleStatisticsError(RuntimeError):
    pass


SUPPORTED_METHODS = {
    "forward_pe",
    "trailing_pe",
    "price_to_sales",
    "ev_to_sales",
    "ev_to_ebitda",
    "fcf_yield",
}


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise HistoricalMultipleStatisticsError(f"required input not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HistoricalMultipleStatisticsError(f"invalid JSON: {path}") from exc


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _percentile(sorted_values: Sequence[float], percentile: float) -> float:
    if not sorted_values:
        raise HistoricalMultipleStatisticsError("cannot calculate percentile for empty values")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (len(sorted_values) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(sorted_values[lower])
    weight = rank - lower
    return float(sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight)


def _iqr_filter(values: Sequence[float], multiplier: float) -> tuple[list[float], dict[str, Any]]:
    ordered = sorted(float(value) for value in values)
    if len(ordered) < 4:
        return ordered, {
            "method": "iqr",
            "applied": False,
            "reason": "fewer_than_four_observations",
            "lower_bound": None,
            "upper_bound": None,
            "excluded_count": 0,
        }
    q1 = _percentile(ordered, 0.25)
    q3 = _percentile(ordered, 0.75)
    iqr = q3 - q1
    lower = q1 - multiplier * iqr
    upper = q3 + multiplier * iqr
    filtered = [value for value in ordered if lower <= value <= upper]
    return filtered, {
        "method": "iqr",
        "applied": True,
        "reason": "iqr_bounds_applied",
        "lower_bound": lower,
        "upper_bound": upper,
        "excluded_count": len(ordered) - len(filtered),
    }


def _window_statistics(
    observations: Sequence[Mapping[str, Any]],
    *,
    window_name: str,
    maximum_observations: int | None,
    minimum_ready_observations: int,
    outlier_iqr_multiplier: float,
) -> dict[str, Any]:
    selected = list(observations if maximum_observations is None else observations[-maximum_observations:])
    raw_values = [_finite(row.get("value")) for row in selected]
    values = [value for value in raw_values if value is not None]
    filtered, outlier = _iqr_filter(values, outlier_iqr_multiplier)
    count = len(values)
    usable_count = len(filtered)
    ready = count >= minimum_ready_observations and usable_count >= minimum_ready_observations
    result: dict[str, Any] = {
        "window": window_name,
        "maximum_observations": maximum_observations,
        "observation_count": count,
        "usable_observation_count": usable_count,
        "first_observation_date": selected[0].get("observation_date") if selected else None,
        "latest_observation_date": selected[-1].get("observation_date") if selected else None,
        "statistics_state": "ready" if ready else "insufficient_history",
        "minimum_ready_observations": minimum_ready_observations,
        "outlier_policy": outlier,
        "statistics": {},
    }
    if not ready:
        return result
    ordered = sorted(filtered)
    mean = statistics.fmean(ordered)
    standard_deviation = statistics.pstdev(ordered) if len(ordered) > 1 else 0.0
    result["statistics"] = {
        "minimum": ordered[0],
        "p10": _percentile(ordered, 0.10),
        "p25": _percentile(ordered, 0.25),
        "median": statistics.median(ordered),
        "mean": mean,
        "p75": _percentile(ordered, 0.75),
        "p90": _percentile(ordered, 0.90),
        "maximum": ordered[-1],
        "standard_deviation": standard_deviation,
        "coefficient_of_variation": (standard_deviation / abs(mean)) if mean != 0 else None,
    }
    return result


def build_historical_multiple_statistics(
    repository_root: Path,
    *,
    dataset_path: str = "data/generated/historical_multiples/historical_multiple_dataset.json",
    windows: Mapping[str, int | None] | None = None,
    minimum_ready_observations: int = 20,
    outlier_iqr_multiplier: float = 1.5,
) -> dict[str, Any]:
    if minimum_ready_observations < 2:
        raise HistoricalMultipleStatisticsError("minimum_ready_observations must be at least 2")
    if outlier_iqr_multiplier <= 0:
        raise HistoricalMultipleStatisticsError("outlier_iqr_multiplier must be positive")
    windows = dict(windows or {"20d": 20, "60d": 60, "252d": 252, "all": None})
    if not windows:
        raise HistoricalMultipleStatisticsError("at least one statistics window is required")
    for name, size in windows.items():
        if not str(name).strip():
            raise HistoricalMultipleStatisticsError("statistics window names must not be empty")
        if size is not None and int(size) < 2:
            raise HistoricalMultipleStatisticsError("statistics window sizes must be at least 2")

    dataset = _load_json(repository_root / dataset_path)
    if not isinstance(dataset, Mapping) or dataset.get("schema_version") != "historical-multiple-dataset.v030.13.1":
        raise HistoricalMultipleStatisticsError("unsupported historical multiple dataset schema")
    observations = dataset.get("observations")
    if not isinstance(observations, list):
        raise HistoricalMultipleStatisticsError("historical multiple observations must be an array")

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    rejected: list[dict[str, Any]] = []
    for raw in observations:
        if not isinstance(raw, Mapping):
            rejected.append({"reason": "observation_not_object"})
            continue
        company_id = str(raw.get("company_id") or "")
        method = str(raw.get("method") or "")
        date = str(raw.get("observation_date") or "")
        value = _finite(raw.get("value"))
        if not company_id or method not in SUPPORTED_METHODS or not date or value is None:
            rejected.append({
                "company_id": company_id or None,
                "method": method or None,
                "observation_date": date or None,
                "reason": "invalid_observation_contract",
            })
            continue
        row = dict(raw)
        row["value"] = value
        groups.setdefault((company_id, method), []).append(row)

    records: list[dict[str, Any]] = []
    ready_window_count = 0
    insufficient_window_count = 0
    for (company_id, method), rows in sorted(groups.items()):
        rows.sort(key=lambda item: item["observation_date"])
        latest = rows[-1]
        window_results = []
        for window_name, maximum in windows.items():
            window_result = _window_statistics(
                rows,
                window_name=window_name,
                maximum_observations=maximum,
                minimum_ready_observations=minimum_ready_observations,
                outlier_iqr_multiplier=outlier_iqr_multiplier,
            )
            window_results.append(window_result)
            if window_result["statistics_state"] == "ready":
                ready_window_count += 1
            else:
                insufficient_window_count += 1
        ready_windows = [row["window"] for row in window_results if row["statistics_state"] == "ready"]
        records.append({
            "company_id": company_id,
            "primary_symbol": latest.get("primary_symbol"),
            "display_name": latest.get("display_name"),
            "method": method,
            "metric_name": latest.get("metric_name"),
            "latest_observation_date": latest.get("observation_date"),
            "latest_value": latest.get("value"),
            "confidence": latest.get("confidence"),
            "formula_version": latest.get("formula_version"),
            "source_formula_version": latest.get("source_formula_version"),
            "statistics_state": "ready" if ready_windows else "insufficient_history",
            "ready_windows": ready_windows,
            "windows": window_results,
        })

    method_counts = {method: 0 for method in sorted(SUPPORTED_METHODS)}
    ready_series_count = 0
    for record in records:
        method_counts[record["method"]] += 1
        if record["statistics_state"] == "ready":
            ready_series_count += 1

    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "historical-multiple-statistics.v030.13.2",
        "version": "V030.13.2",
        "generated_at": generated_at,
        "as_of_date": dataset.get("as_of_date"),
        "sources": {
            "historical_multiple_dataset_path": dataset_path,
            "historical_multiple_dataset_schema_version": dataset.get("schema_version"),
        },
        "policy": {
            "windows": windows,
            "minimum_ready_observations": minimum_ready_observations,
            "percentile_interpolation": "linear",
            "outlier_method": "iqr_exclusion",
            "outlier_iqr_multiplier": outlier_iqr_multiplier,
            "insufficient_history_policy": "do_not_emit_statistics",
        },
        "summary": {
            "company_count": len({record["company_id"] for record in records}),
            "method_count": len(SUPPORTED_METHODS),
            "series_count": len(records),
            "ready_series_count": ready_series_count,
            "insufficient_series_count": len(records) - ready_series_count,
            "window_record_count": ready_window_count + insufficient_window_count,
            "ready_window_count": ready_window_count,
            "insufficient_window_count": insufficient_window_count,
            "rejected_observation_count": len(rejected),
            "method_series_counts": method_counts,
        },
        "statistics": records,
        "indexes": {
            "company_method_to_statistics_position": {
                f"{row['company_id']}|{row['method']}": position for position, row in enumerate(records)
            }
        },
        "diagnostic": {"rejected_observations": rejected},
    }


def write_historical_multiple_statistics(report: Mapping[str, Any], output: Path, diagnostic: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    diagnostic.parent.mkdir(parents=True, exist_ok=True)
    clean = dict(report)
    diag = clean.pop("diagnostic")
    output.write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    diagnostic.write_text(json.dumps({
        "schema_version": "historical-multiple-statistics-diagnostic.v030.13.2",
        "version": "V030.13.2",
        "generated_at": report.get("generated_at"),
        **diag,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
