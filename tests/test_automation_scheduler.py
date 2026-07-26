from __future__ import annotations

import json
import subprocess
from pathlib import Path

from axiom_engine.automation import acquire_scheduler_lock, release_scheduler_lock, run_scheduled_automation


def test_lock_prevents_overlap(tmp_path: Path) -> None:
    lock = tmp_path / "scheduler.lock"
    acquired, _, _ = acquire_scheduler_lock(lock, stale_after_seconds=100, now_epoch=1000, pid=1, hostname="a")
    assert acquired is True
    acquired2, current, _ = acquire_scheduler_lock(lock, stale_after_seconds=100, now_epoch=1050, pid=2, hostname="b")
    assert acquired2 is False
    assert current["pid"] == 1


def test_stale_lock_is_recovered(tmp_path: Path) -> None:
    lock = tmp_path / "scheduler.lock"
    acquire_scheduler_lock(lock, stale_after_seconds=10, now_epoch=1000, pid=1, hostname="a")
    acquired, current, replaced = acquire_scheduler_lock(lock, stale_after_seconds=10, now_epoch=1011, pid=2, hostname="b")
    assert acquired is True
    assert current["pid"] == 2
    assert replaced and replaced["pid"] == 1


def test_release_only_expected_owner(tmp_path: Path) -> None:
    lock = tmp_path / "scheduler.lock"
    acquire_scheduler_lock(lock, stale_after_seconds=10, now_epoch=1000, pid=12, hostname="a")
    assert release_scheduler_lock(lock, expected_pid=99) is False
    assert lock.exists()
    assert release_scheduler_lock(lock, expected_pid=12) is True


def test_scheduled_run_writes_report_and_releases_lock(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    output = root / "data/generated/automation"
    lock = output / "scheduler.lock"

    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout=json.dumps({"status": "completed"}), stderr="")

    report = run_scheduled_automation(root, ["python", "x.py"], output, lock, runner=runner)
    assert report["status"] == "completed"
    assert report["automation"]["status"] == "completed"
    assert report["lock_released"] is True
    assert not lock.exists()
    assert (output / "latest_schedule.json").exists()


def test_overlap_is_clean_skip(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    output = root / "out"
    lock = output / "scheduler.lock"
    acquire_scheduler_lock(lock, stale_after_seconds=1000)
    report = run_scheduled_automation(root, ["python", "x.py"], output, lock, stale_lock_seconds=1000)
    assert report["status"] == "skipped_locked"
    assert report["returncode"] is None
