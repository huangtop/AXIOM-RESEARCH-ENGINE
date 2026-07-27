from __future__ import annotations

import json
from pathlib import Path

import pytest

from axiom_engine.historical_multiple_statistics import (
    HistoricalMultipleStatisticsError,
    build_historical_multiple_statistics,
)


def _dataset(values: list[float], method: str = "forward_pe") -> dict:
    observations = []
    for index, value in enumerate(values, start=1):
        observations.append({
            "company_id": "company:1", "primary_symbol": "AAA", "display_name": "AAA Inc",
            "method": method, "metric_name": "current_multiple",
            "observation_date": f"2026-07-{index:02d}", "value": value, "confidence": "medium",
            "formula_version": "forward-pe-engine.v1", "source_formula_version": "forward-pe-inputs.v1",
        })
    return {
        "schema_version": "historical-multiple-dataset.v030.13.1",
        "as_of_date": "2026-07-27", "observations": observations,
    }


def _write(root: Path, payload: dict) -> None:
    path = root / "data/generated/historical_multiples/historical_multiple_dataset.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_single_observation_is_insufficient_and_emits_no_statistics(tmp_path: Path) -> None:
    _write(tmp_path, _dataset([30.0]))
    report = build_historical_multiple_statistics(tmp_path)
    record = report["statistics"][0]
    assert record["statistics_state"] == "insufficient_history"
    assert all(not window["statistics"] for window in record["windows"])


def test_ready_statistics_include_percentiles_and_dispersion(tmp_path: Path) -> None:
    _write(tmp_path, _dataset([float(value) for value in range(1, 21)]))
    report = build_historical_multiple_statistics(tmp_path)
    window = next(row for row in report["statistics"][0]["windows"] if row["window"] == "20d")
    assert window["statistics_state"] == "ready"
    assert window["statistics"]["median"] == 10.5
    assert window["statistics"]["p25"] == 5.75
    assert window["statistics"]["p75"] == 15.25
    assert window["statistics"]["standard_deviation"] > 0


def test_window_uses_latest_observations_only(tmp_path: Path) -> None:
    _write(tmp_path, _dataset([float(value) for value in range(1, 31)]))
    report = build_historical_multiple_statistics(tmp_path)
    window = next(row for row in report["statistics"][0]["windows"] if row["window"] == "20d")
    assert window["statistics"]["minimum"] == 11.0
    assert window["statistics"]["maximum"] == 30.0


def test_all_window_uses_complete_history(tmp_path: Path) -> None:
    _write(tmp_path, _dataset([float(value) for value in range(1, 31)]))
    report = build_historical_multiple_statistics(tmp_path)
    window = next(row for row in report["statistics"][0]["windows"] if row["window"] == "all")
    assert window["observation_count"] == 30
    assert window["statistics"]["median"] == 15.5


def test_iqr_outlier_is_excluded(tmp_path: Path) -> None:
    values = [10.0] * 20 + [1000.0]
    _write(tmp_path, _dataset(values))
    report = build_historical_multiple_statistics(tmp_path, windows={"all": None})
    window = report["statistics"][0]["windows"][0]
    assert window["outlier_policy"]["excluded_count"] == 1
    assert window["statistics"]["maximum"] == 10.0


def test_preserves_latest_provenance(tmp_path: Path) -> None:
    _write(tmp_path, _dataset([float(value) for value in range(1, 21)]))
    record = build_historical_multiple_statistics(tmp_path)["statistics"][0]
    assert record["confidence"] == "medium"
    assert record["formula_version"] == "forward-pe-engine.v1"
    assert record["source_formula_version"] == "forward-pe-inputs.v1"


def test_invalid_observation_is_diagnostic(tmp_path: Path) -> None:
    payload = _dataset([float(value) for value in range(1, 21)])
    payload["observations"].append({"company_id": "company:2", "method": "dcf", "value": 1})
    _write(tmp_path, payload)
    report = build_historical_multiple_statistics(tmp_path)
    assert report["summary"]["rejected_observation_count"] == 1


def test_rejects_unsupported_dataset_schema(tmp_path: Path) -> None:
    _write(tmp_path, {"schema_version": "old", "observations": []})
    with pytest.raises(HistoricalMultipleStatisticsError, match="unsupported"):
        build_historical_multiple_statistics(tmp_path)


def test_minimum_ready_observations_must_be_at_least_two(tmp_path: Path) -> None:
    _write(tmp_path, _dataset([1.0]))
    with pytest.raises(HistoricalMultipleStatisticsError, match="at least 2"):
        build_historical_multiple_statistics(tmp_path, minimum_ready_observations=1)


def test_invalid_window_size_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, _dataset([1.0]))
    with pytest.raises(HistoricalMultipleStatisticsError, match="window sizes"):
        build_historical_multiple_statistics(tmp_path, windows={"bad": 1})


def test_non_positive_iqr_multiplier_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, _dataset([1.0]))
    with pytest.raises(HistoricalMultipleStatisticsError, match="positive"):
        build_historical_multiple_statistics(tmp_path, outlier_iqr_multiplier=0)
