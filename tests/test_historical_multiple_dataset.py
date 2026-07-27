from __future__ import annotations

import json
from pathlib import Path

import pytest

from axiom_engine.historical_multiples import HistoricalMultipleDatasetError, build_historical_multiple_dataset


def _engine(date: str = "2026-07-24") -> dict:
    methods = {}
    metrics = {
        "forward_pe": {"current_multiple": 30.0},
        "trailing_pe": {"current_multiple": 32.0},
        "price_to_sales": {"current_multiple": 10.0},
        "ev_to_sales": {"current_multiple": 9.0},
        "ev_to_ebitda": {"current_multiple": 20.0},
        "fcf_yield": {"current_yield_percent": 2.5},
        "dcf": {"current_price": 300.0},
    }
    for name, values in metrics.items():
        methods[name] = {
            "status": "calculated", "confidence": "medium", "metrics": values,
            "formula_version": f"{name}-engine.v1", "source_formula_version": f"{name}-inputs.v1",
        }
    return {
        "schema_version": "valuation-engine-snapshot.v030.13.0", "as_of_date": date,
        "companies": [{"company_id": "company:1", "primary_symbol": "AAA", "display_name": "AAA Inc", "methods": methods}],
    }


def _write(root: Path, payload: dict) -> None:
    path = root / "data/generated/valuation_engine/valuation_snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_builds_six_historical_metrics_and_excludes_dcf(tmp_path: Path) -> None:
    _write(tmp_path, _engine())
    report = build_historical_multiple_dataset(tmp_path)
    assert report["summary"]["observation_count"] == 6
    assert {row["method"] for row in report["observations"]} == {
        "forward_pe", "trailing_pe", "price_to_sales", "ev_to_sales", "ev_to_ebitda", "fcf_yield"
    }


def test_preserves_formula_and_confidence_provenance(tmp_path: Path) -> None:
    _write(tmp_path, _engine())
    row = build_historical_multiple_dataset(tmp_path)["observations"][0]
    assert row["confidence"] == "medium"
    assert row["formula_version"]
    assert row["source_formula_version"]


def test_same_day_is_idempotently_replaced(tmp_path: Path) -> None:
    _write(tmp_path, _engine())
    first = build_historical_multiple_dataset(tmp_path)
    path = tmp_path / "data/generated/historical_multiples/historical_multiple_dataset.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = dict(first); clean.pop("diagnostic")
    path.write_text(json.dumps(clean), encoding="utf-8")
    second = build_historical_multiple_dataset(tmp_path)
    assert second["summary"]["observation_count"] == 6
    assert second["summary"]["replaced_observation_count"] == 6


def test_new_date_appends_observations(tmp_path: Path) -> None:
    _write(tmp_path, _engine("2026-07-24"))
    first = build_historical_multiple_dataset(tmp_path)
    path = tmp_path / "data/generated/historical_multiples/historical_multiple_dataset.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = dict(first); clean.pop("diagnostic")
    path.write_text(json.dumps(clean), encoding="utf-8")
    _write(tmp_path, _engine("2026-07-25"))
    second = build_historical_multiple_dataset(tmp_path)
    assert second["summary"]["observation_count"] == 12
    assert second["summary"]["added_observation_count"] == 6


def test_series_statistics_are_computed(tmp_path: Path) -> None:
    _write(tmp_path, _engine("2026-07-24"))
    first = build_historical_multiple_dataset(tmp_path)
    path = tmp_path / "data/generated/historical_multiples/historical_multiple_dataset.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = dict(first); clean.pop("diagnostic")
    path.write_text(json.dumps(clean), encoding="utf-8")
    newer = _engine("2026-07-25")
    newer["companies"][0]["methods"]["forward_pe"]["metrics"]["current_multiple"] = 40.0
    _write(tmp_path, newer)
    report = build_historical_multiple_dataset(tmp_path, minimum_ready_observations=2)
    series = next(row for row in report["series"] if row["method"] == "forward_pe")
    assert series["median_value"] == 35.0
    assert series["history_state"] == "ready"


def test_blocked_method_is_skipped(tmp_path: Path) -> None:
    payload = _engine()
    payload["companies"][0]["methods"]["forward_pe"] = {"status": "blocked", "metrics": {}}
    _write(tmp_path, payload)
    report = build_historical_multiple_dataset(tmp_path)
    assert report["summary"]["observation_count"] == 5
    assert report["summary"]["skipped_method_record_count"] == 1


def test_non_finite_metric_is_skipped(tmp_path: Path) -> None:
    payload = _engine()
    payload["companies"][0]["methods"]["forward_pe"]["metrics"]["current_multiple"] = "NaN"
    _write(tmp_path, payload)
    report = build_historical_multiple_dataset(tmp_path)
    assert report["summary"]["observation_count"] == 5


def test_requires_as_of_date(tmp_path: Path) -> None:
    payload = _engine(); payload.pop("as_of_date")
    _write(tmp_path, payload)
    with pytest.raises(HistoricalMultipleDatasetError, match="as_of_date"):
        build_historical_multiple_dataset(tmp_path)


def test_rejects_incompatible_existing_schema(tmp_path: Path) -> None:
    _write(tmp_path, _engine())
    path = tmp_path / "data/generated/historical_multiples/historical_multiple_dataset.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": "old"}), encoding="utf-8")
    with pytest.raises(HistoricalMultipleDatasetError, match="incompatible"):
        build_historical_multiple_dataset(tmp_path)


def test_minimum_ready_observations_must_be_at_least_two(tmp_path: Path) -> None:
    _write(tmp_path, _engine())
    with pytest.raises(HistoricalMultipleDatasetError, match="at least 2"):
        build_historical_multiple_dataset(tmp_path, minimum_ready_observations=1)
