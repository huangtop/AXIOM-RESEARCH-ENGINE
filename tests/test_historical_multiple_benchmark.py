from __future__ import annotations
import json
from pathlib import Path
import pytest
from axiom_engine.historical_multiple_benchmark import HistoricalMultipleBenchmarkError, build_historical_multiple_benchmark

def _window(name: str, state: str, count: int, median: float = 30.0):
    return {"window": name, "statistics_state": state, "usable_observation_count": count, "first_observation_date": "2026-01-01", "statistics": ({"p25": median-2, "median": median, "p75": median+2} if state == "ready" else {})}

def _payload(windows, method="forward_pe", confidence="medium"):
    return {"schema_version":"historical-multiple-statistics.v030.13.2","as_of_date":"2026-07-27","statistics":[{"company_id":"company:1","primary_symbol":"AAA","display_name":"AAA Inc","method":method,"metric_name":"current_multiple","latest_observation_date":"2026-07-27","latest_value":31.0,"confidence":confidence,"formula_version":"forward-pe-engine.v1","source_formula_version":"forward-pe-inputs.v1","windows":windows}]}

def _write(root: Path, payload):
    path=root/"data/generated/historical_multiple_statistics/historical_multiple_statistics.json"; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(payload))

def test_insufficient_history_emits_no_benchmark(tmp_path):
    _write(tmp_path,_payload([_window("20d","insufficient_history",1)])); row=build_historical_multiple_benchmark(tmp_path)["benchmarks"][0]
    assert row["status"]=="insufficient_history" and row["benchmark"]=={}

def test_selects_preferred_ready_window(tmp_path):
    _write(tmp_path,_payload([_window("20d","ready",20,20),_window("60d","ready",60,25),_window("252d","ready",100,30)])); row=build_historical_multiple_benchmark(tmp_path)["benchmarks"][0]
    assert row["selected_window"]=="252d" and row["benchmark"]["target_multiple"]==30

def test_fcf_yield_uses_target_yield_name(tmp_path):
    _write(tmp_path,_payload([_window("20d","ready",20,2.5)],method="fcf_yield")); row=build_historical_multiple_benchmark(tmp_path)["benchmarks"][0]
    assert row["benchmark"]["target_yield_percent"]==2.5 and "target_multiple" not in row["benchmark"]

def test_bounds_are_preserved(tmp_path):
    _write(tmp_path,_payload([_window("20d","ready",20,30)])); b=build_historical_multiple_benchmark(tmp_path)["benchmarks"][0]["benchmark"]
    assert b["lower_bound"]==28 and b["upper_bound"]==32

def test_history_confidence_low_at_twenty(tmp_path):
    _write(tmp_path,_payload([_window("20d","ready",20)])); row=build_historical_multiple_benchmark(tmp_path)["benchmarks"][0]
    assert row["history_confidence"]=="low" and row["confidence"]=="low"

def test_confidence_capped_by_source(tmp_path):
    _write(tmp_path,_payload([_window("252d","ready",252)],confidence="medium")); row=build_historical_multiple_benchmark(tmp_path)["benchmarks"][0]
    assert row["history_confidence"]=="high" and row["confidence"]=="medium"

def test_invalid_statistics_bounds_are_diagnostic(tmp_path):
    w=_window("20d","ready",20); w["statistics"]={"p25":35,"median":30,"p75":32}; _write(tmp_path,_payload([w])); report=build_historical_multiple_benchmark(tmp_path)
    assert report["benchmarks"][0]["status"]=="invalid" and report["summary"]["diagnostic_count"]==1

def test_rejects_unsupported_schema(tmp_path):
    _write(tmp_path,{"schema_version":"old","statistics":[]})
    with pytest.raises(HistoricalMultipleBenchmarkError,match="unsupported"): build_historical_multiple_benchmark(tmp_path)

def test_window_preference_required(tmp_path):
    _write(tmp_path,_payload([]))
    with pytest.raises(HistoricalMultipleBenchmarkError,match="must not be empty"): build_historical_multiple_benchmark(tmp_path,window_preference=[])

def test_invalid_thresholds_rejected(tmp_path):
    _write(tmp_path,_payload([]))
    with pytest.raises(HistoricalMultipleBenchmarkError,match="thresholds"): build_historical_multiple_benchmark(tmp_path,medium_confidence_observations=60,high_confidence_observations=20)
