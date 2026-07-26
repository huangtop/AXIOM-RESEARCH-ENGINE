from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from axiom_engine.automation import normalize_stage_specs, run_automation


def completed(argv, cwd, text, capture_output, check):
    return subprocess.CompletedProcess(argv, 0, stdout='{"status":"completed"}\n', stderr="")


def failed(argv, cwd, text, capture_output, check):
    code = 2 if "first.py" in argv else 0
    return subprocess.CompletedProcess(argv, code, stdout="{}\n", stderr="boom" if code else "")


def test_successful_run_writes_reports(tmp_path: Path):
    output = tmp_path / "generated" / "automation_run.json"
    report = run_automation(
        tmp_path,
        [{"name": "one", "argv": ["python", "one.py"]}, {"name": "two", "argv": ["python", "two.py"]}],
        output,
        strict=True,
        runner=completed,
    )
    assert report["status"] == "completed"
    assert report["completed_stage_count"] == 2
    assert report["stages"][0]["argv"][-1] == "--strict"
    assert output.exists()
    assert (output.parent / "latest.json").exists()
    assert (output.parent / "automation_summary.json").exists()
    assert (output.parent / "automation_failures.json").exists()


def test_required_failure_stops_following_stage(tmp_path: Path):
    report = run_automation(
        tmp_path,
        [{"name": "first", "argv": ["python", "first.py"]}, {"name": "second", "argv": ["python", "second.py"]}],
        tmp_path / "run.json",
        runner=failed,
    )
    assert report["status"] == "failed"
    assert report["stages"][0]["status"] == "failed"
    assert report["stages"][1]["status"] == "skipped"


def test_continue_on_failure_runs_remaining_stages(tmp_path: Path):
    report = run_automation(
        tmp_path,
        [{"name": "first", "argv": ["python", "first.py"]}, {"name": "second", "argv": ["python", "second.py"]}],
        tmp_path / "run.json",
        continue_on_failure=True,
        runner=failed,
    )
    assert report["status"] == "failed"
    assert report["stages"][1]["status"] == "completed"


def test_dry_run_executes_no_commands(tmp_path: Path):
    def should_not_run(*args, **kwargs):
        raise AssertionError("runner should not be invoked")
    report = run_automation(
        tmp_path,
        [{"name": "one", "argv": ["python", "one.py"]}],
        tmp_path / "run.json",
        dry_run=True,
        runner=should_not_run,
    )
    assert report["status"] == "planned"
    assert report["stages"][0]["status"] == "planned"


def test_invalid_duplicate_stage_names_are_rejected():
    with pytest.raises(ValueError, match="duplicate stage name"):
        normalize_stage_specs([
            {"name": "same", "argv": ["python", "one.py"]},
            {"name": "same", "argv": ["python", "two.py"]},
        ])
