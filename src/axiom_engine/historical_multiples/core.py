from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class HistoricalMultipleDatasetError(RuntimeError):
    pass


METHOD_METRICS = {
    "forward_pe": "current_multiple",
    "trailing_pe": "current_multiple",
    "price_to_sales": "current_multiple",
    "ev_to_sales": "current_multiple",
    "ev_to_ebitda": "current_multiple",
    "fcf_yield": "current_yield_percent",
}


def _load_json(path: Path, *, required: bool) -> Any:
    if not path.exists():
        if required:
            raise HistoricalMultipleDatasetError(f"required input not found: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HistoricalMultipleDatasetError(f"invalid JSON: {path}") from exc


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _observation_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return str(row.get("company_id")), str(row.get("method")), str(row.get("observation_date"))


def _series_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("company_id")), str(row.get("method"))


def _series_summary(rows: list[dict[str, Any]], minimum_ready_observations: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(_series_key(row), []).append(row)

    series: list[dict[str, Any]] = []
    for (company_id, method), observations in sorted(groups.items()):
        observations.sort(key=lambda item: item["observation_date"])
        values = [float(item["value"]) for item in observations]
        latest = observations[-1]
        count = len(values)
        series.append({
            "company_id": company_id,
            "primary_symbol": latest.get("primary_symbol"),
            "method": method,
            "metric_name": latest.get("metric_name"),
            "observation_count": count,
            "first_observation_date": observations[0]["observation_date"],
            "latest_observation_date": latest["observation_date"],
            "latest_value": latest["value"],
            "minimum_value": min(values),
            "maximum_value": max(values),
            "median_value": statistics.median(values),
            "history_state": "ready" if count >= minimum_ready_observations else "collecting",
        })
    return series


def build_historical_multiple_dataset(
    repository_root: Path,
    *,
    engine_path: str = "data/generated/valuation_engine/valuation_snapshot.json",
    existing_dataset_path: str = "data/generated/historical_multiples/historical_multiple_dataset.json",
    minimum_ready_observations: int = 20,
) -> dict[str, Any]:
    if minimum_ready_observations < 2:
        raise HistoricalMultipleDatasetError("minimum_ready_observations must be at least 2")

    engine = _load_json(repository_root / engine_path, required=True)
    if not isinstance(engine, Mapping) or not str(engine.get("schema_version") or "").startswith("valuation-engine-snapshot."):
        raise HistoricalMultipleDatasetError("unsupported valuation engine snapshot schema")

    observation_date = str(engine.get("as_of_date") or "").strip()
    if not observation_date:
        raise HistoricalMultipleDatasetError("valuation engine snapshot must contain as_of_date")
    companies = engine.get("companies")
    if not isinstance(companies, list) or not companies:
        raise HistoricalMultipleDatasetError("valuation engine snapshot must contain companies")

    existing = _load_json(repository_root / existing_dataset_path, required=False)
    prior_rows: list[dict[str, Any]] = []
    if existing is not None:
        if not isinstance(existing, Mapping) or existing.get("schema_version") != "historical-multiple-dataset.v030.13.1":
            raise HistoricalMultipleDatasetError("existing historical multiple dataset schema is incompatible")
        raw_prior = existing.get("observations")
        if not isinstance(raw_prior, list):
            raise HistoricalMultipleDatasetError("existing dataset observations must be an array")
        prior_rows = [dict(row) for row in raw_prior if isinstance(row, Mapping)]

    observations_by_key = {_observation_key(row): row for row in prior_rows}
    added_count = 0
    replaced_count = 0
    skipped: list[dict[str, Any]] = []

    for company in companies:
        if not isinstance(company, Mapping) or not company.get("company_id"):
            raise HistoricalMultipleDatasetError("every engine company must contain company_id")
        methods = company.get("methods") if isinstance(company.get("methods"), Mapping) else {}
        for method, metric_name in METHOD_METRICS.items():
            payload = methods.get(method)
            if not isinstance(payload, Mapping) or payload.get("status") != "calculated":
                skipped.append({
                    "company_id": company["company_id"],
                    "primary_symbol": company.get("primary_symbol"),
                    "method": method,
                    "reason": "engine_method_not_calculated",
                })
                continue
            metrics = payload.get("metrics") if isinstance(payload.get("metrics"), Mapping) else {}
            value = _finite_number(metrics.get(metric_name))
            if value is None:
                skipped.append({
                    "company_id": company["company_id"],
                    "primary_symbol": company.get("primary_symbol"),
                    "method": method,
                    "reason": "historical_metric_missing_or_non_finite",
                })
                continue
            row = {
                "company_id": company["company_id"],
                "primary_symbol": company.get("primary_symbol"),
                "display_name": company.get("display_name"),
                "method": method,
                "metric_name": metric_name,
                "observation_date": observation_date,
                "value": value,
                "confidence": payload.get("confidence"),
                "formula_version": payload.get("formula_version"),
                "source_formula_version": payload.get("source_formula_version"),
                "source_snapshot_schema_version": engine.get("schema_version"),
            }
            key = _observation_key(row)
            if key in observations_by_key:
                replaced_count += 1
            else:
                added_count += 1
            observations_by_key[key] = row

    observations = sorted(
        observations_by_key.values(),
        key=lambda item: (item["company_id"], item["method"], item["observation_date"]),
    )
    series = _series_summary(observations, minimum_ready_observations)
    ready_count = sum(1 for row in series if row["history_state"] == "ready")
    method_counts = {method: 0 for method in METHOD_METRICS}
    for row in observations:
        method_counts[row["method"]] += 1

    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "historical-multiple-dataset.v030.13.1",
        "version": "V030.13.1",
        "generated_at": generated_at,
        "as_of_date": observation_date,
        "sources": {
            "valuation_engine_path": engine_path,
            "valuation_engine_schema_version": engine.get("schema_version"),
            "existing_dataset_path": existing_dataset_path,
        },
        "policy": {
            "observation_mode": "append_only_daily_engine_snapshot",
            "same_day_policy": "replace_same_company_method_date",
            "minimum_ready_observations": minimum_ready_observations,
            "point_in_time_integrity": "do_not_backfill_with_current_fundamentals",
        },
        "summary": {
            "company_count": len({row["company_id"] for row in observations}),
            "method_count": len(METHOD_METRICS),
            "observation_count": len(observations),
            "series_count": len(series),
            "ready_series_count": ready_count,
            "collecting_series_count": len(series) - ready_count,
            "added_observation_count": added_count,
            "replaced_observation_count": replaced_count,
            "skipped_method_record_count": len(skipped),
            "method_observation_counts": method_counts,
        },
        "observations": observations,
        "series": series,
        "indexes": {
            "company_method_to_series_position": {
                f"{row['company_id']}|{row['method']}": position for position, row in enumerate(series)
            }
        },
        "diagnostic": {"skipped_methods": skipped},
    }


def write_historical_multiple_dataset(report: Mapping[str, Any], output: Path, diagnostic: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    diagnostic.parent.mkdir(parents=True, exist_ok=True)
    clean = dict(report)
    diag = clean.pop("diagnostic")
    output.write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    diagnostic.write_text(json.dumps({
        "schema_version": "historical-multiple-diagnostic.v030.13.1",
        "version": "V030.13.1",
        "generated_at": report.get("generated_at"),
        **diag,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
