from __future__ import annotations
import json
from pathlib import Path
from axiom_engine.automation import build_input_snapshot, compare_snapshots, plan_incremental_refresh


def test_snapshot_extracts_symbols(tmp_path: Path) -> None:
    p = tmp_path / "data/provider_intake/accepted/a.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"records": [{"symbol": "aapl"}, {"ticker": "MSFT"}]}))
    snap = build_input_snapshot(tmp_path, ["data/**/*.json"], ["symbol", "ticker"])
    assert snap["symbols"] == ["AAPL", "MSFT"]


def test_compare_detects_added_modified_removed(tmp_path: Path) -> None:
    previous = {"files": [{"path": "a.json", "sha256": "1", "symbols": ["AAPL"]}, {"path": "gone.json", "sha256": "x", "symbols": ["IBM"]}]}
    current = {"files": [{"path": "a.json", "sha256": "2", "symbols": ["AAPL"]}, {"path": "b.json", "sha256": "3", "symbols": ["MSFT"]}]}
    delta = compare_snapshots(previous, current)
    assert delta["modified_files"] == ["a.json"]
    assert delta["added_files"] == ["b.json"]
    assert delta["removed_files"] == ["gone.json"]
    assert delta["affected_symbols"] == ["AAPL", "IBM", "MSFT"]


def test_first_run_falls_back_to_full(tmp_path: Path) -> None:
    report = plan_incremental_refresh(tmp_path, {"watch_patterns": [], "targeted_refresh": {"enabled": False}}, tmp_path / "out")
    assert report["mode"] == "full"
    assert report["reason"] == "baseline_snapshot_missing"


def test_second_unchanged_run_is_noop(tmp_path: Path) -> None:
    config = {"watch_patterns": [], "targeted_refresh": {"enabled": False}}
    out = tmp_path / "out"
    plan_incremental_refresh(tmp_path, config, out)
    report = plan_incremental_refresh(tmp_path, config, out)
    assert report["mode"] == "noop"
    assert report["changed_file_count"] == 0


def test_changed_input_without_target_support_falls_back_full(tmp_path: Path) -> None:
    config = {"watch_patterns": ["data/*.json"], "symbol_keys": ["symbol"], "targeted_refresh": {"enabled": False}}
    out = tmp_path / "out"
    plan_incremental_refresh(tmp_path, config, out)
    p = tmp_path / "data/x.json"; p.parent.mkdir(); p.write_text('{"symbol":"AAPL"}')
    report = plan_incremental_refresh(tmp_path, config, out)
    assert report["mode"] == "full"
    assert report["affected_symbols"] == ["AAPL"]


def test_targeted_mode_when_enabled_and_bounded(tmp_path: Path) -> None:
    config = {"watch_patterns": ["data/*.json"], "symbol_keys": ["symbol"], "targeted_refresh": {"enabled": True, "max_symbols": 10}}
    out = tmp_path / "out"
    plan_incremental_refresh(tmp_path, config, out)
    p = tmp_path / "data/x.json"; p.parent.mkdir(); p.write_text('{"symbol":"AAPL"}')
    report = plan_incremental_refresh(tmp_path, config, out)
    assert report["mode"] == "targeted"
    assert report["affected_symbol_count"] == 1


def test_orchestrator_skips_refresh_when_plan_is_noop(tmp_path: Path) -> None:
    from axiom_engine.automation import run_automation
    report_path = tmp_path / "plan.json"
    report_path.write_text('{"mode":"noop"}')
    calls = []
    def runner(argv, **kwargs):
        import subprocess
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout='{}', stderr='')
    stages = [{
        "name": "refresh", "argv": ["python", "refresh.py"], "required": True,
        "supports_strict": False,
        "run_if_report": {"path": "plan.json", "field": "mode", "field_in": ["full", "targeted"]}
    }]
    report = run_automation(tmp_path, stages, tmp_path / "run.json", runner=runner)
    assert calls == []
    assert report["stages"][0]["status"] == "skipped"
    assert report["stages"][0]["error"] == "condition_not_met"
