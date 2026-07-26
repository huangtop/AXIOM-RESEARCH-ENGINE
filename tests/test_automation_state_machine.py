from __future__ import annotations

import json
import subprocess
from pathlib import Path

from axiom_engine.automation import load_automation_state, run_automation


def ok(argv, cwd, text, capture_output, check):
    return subprocess.CompletedProcess(argv, 0, stdout='{"status":"completed"}\n', stderr="")


def fail_first(argv, cwd, text, capture_output, check):
    code = 2 if "first.py" in argv else 0
    return subprocess.CompletedProcess(argv, code, stdout="{}\n", stderr="boom" if code else "")


def specs():
    return [
        {"name": "first", "argv": ["python", "first.py"]},
        {"name": "second", "argv": ["python", "second.py"]},
    ]


def test_state_is_persisted_and_attempts_are_counted(tmp_path: Path):
    state_path = tmp_path / "state.json"
    report = run_automation(tmp_path, specs(), tmp_path / "run.json", state_path=state_path, runner=ok)
    state = json.loads(state_path.read_text())
    assert report["status"] == "completed"
    assert [row["status"] for row in state["stages"]] == ["completed", "completed"]
    assert [row["attempt_count"] for row in state["stages"]] == [1, 1]


def test_resume_preserves_completed_and_retries_failed(tmp_path: Path):
    state_path = tmp_path / "state.json"
    first = run_automation(tmp_path, specs(), tmp_path / "first.json", state_path=state_path, runner=fail_first)
    assert first["status"] == "failed"
    loaded = load_automation_state(state_path)
    calls = []
    def record(argv, cwd, text, capture_output, check):
        calls.append(argv)
        return ok(argv, cwd, text, capture_output, check)
    resumed = run_automation(tmp_path, specs(), tmp_path / "second.json", state_path=state_path,
                             resume_state=loaded, retry_failed=True, runner=record)
    assert resumed["status"] == "completed"
    assert len(calls) == 2  # failed first and previously blocked second
    assert resumed["stages"][0]["attempt_count"] == 2
    assert resumed["resume_count"] == 1


def test_resume_without_retry_does_not_rerun_failed_stage(tmp_path: Path):
    state_path = tmp_path / "state.json"
    run_automation(tmp_path, specs(), tmp_path / "first.json", state_path=state_path, runner=fail_first)
    loaded = load_automation_state(state_path)
    calls = []
    def record(argv, cwd, text, capture_output, check):
        calls.append(argv)
        return ok(argv, cwd, text, capture_output, check)
    resumed = run_automation(tmp_path, specs(), tmp_path / "second.json", state_path=state_path,
                             resume_state=loaded, runner=record)
    assert resumed["status"] == "failed"
    assert calls == []


def test_running_state_is_recovered_as_interrupted(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"status":"running", "stages":[{"name":"first", "status":"running"}]}))
    state = load_automation_state(path)
    assert state["status"] == "interrupted"
    assert state["stages"][0]["status"] == "interrupted"


def test_explicit_skip_stage(tmp_path: Path):
    report = run_automation(tmp_path, specs(), tmp_path / "run.json", skip_stages=["first"], runner=ok)
    assert report["status"] == "completed"
    assert report["stages"][0]["status"] == "skipped"
    assert report["stages"][0]["error"] == "explicitly_skipped"
    assert report["stages"][1]["status"] == "completed"


def test_completed_stage_is_not_reexecuted_on_resume(tmp_path: Path):
    state_path = tmp_path / "state.json"
    run_automation(tmp_path, specs(), tmp_path / "first.json", state_path=state_path, runner=ok)
    loaded = load_automation_state(state_path)
    def should_not_run(*args, **kwargs):
        raise AssertionError("completed stages must not run again")
    resumed = run_automation(tmp_path, specs(), tmp_path / "second.json", state_path=state_path,
                             resume_state=loaded, retry_failed=True, runner=should_not_run)
    assert resumed["status"] == "completed"
    assert resumed["resume_count"] == 1
