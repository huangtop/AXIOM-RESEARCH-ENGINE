from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

SCHEDULE_SCHEMA_VERSION = "scheduled-automation-run.v030.8.3"
SCHEDULE_VERSION = "V030.8.3"
LOCK_SCHEMA_VERSION = "automation-scheduler-lock.v030.8.3"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def acquire_scheduler_lock(
    lock_path: Path,
    *,
    stale_after_seconds: int,
    now_epoch: float | None = None,
    pid: int | None = None,
    hostname: str | None = None,
) -> tuple[bool, dict[str, Any], dict[str, Any] | None]:
    """Atomically acquire a scheduler lock.

    Returns (acquired, current_lock, replaced_stale_lock).
    """
    if stale_after_seconds <= 0:
        raise ValueError("stale_after_seconds must be positive")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    now_epoch = time.time() if now_epoch is None else float(now_epoch)
    payload = {
        "schema_version": LOCK_SCHEMA_VERSION,
        "version": SCHEDULE_VERSION,
        "pid": os.getpid() if pid is None else int(pid),
        "hostname": socket.gethostname() if hostname is None else hostname,
        "acquired_at": datetime.fromtimestamp(now_epoch, timezone.utc).isoformat(),
        "acquired_at_epoch": now_epoch,
    }
    replaced: dict[str, Any] | None = None
    while True:
        try:
            fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            return True, payload, replaced
        except FileExistsError:
            try:
                existing = _read_json(lock_path)
                acquired_epoch = float(existing.get("acquired_at_epoch", 0))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                acquired_epoch = lock_path.stat().st_mtime
                existing = {"invalid_lock": True, "mtime_epoch": acquired_epoch}
            age = max(0.0, now_epoch - acquired_epoch)
            existing["age_seconds"] = round(age, 3)
            if age < stale_after_seconds:
                return False, existing, None
            replaced = existing
            try:
                lock_path.unlink()
            except FileNotFoundError:
                continue


def release_scheduler_lock(lock_path: Path, expected_pid: int | None = None) -> bool:
    try:
        if expected_pid is not None:
            current = _read_json(lock_path)
            if int(current.get("pid", -1)) != int(expected_pid):
                return False
        lock_path.unlink()
        return True
    except FileNotFoundError:
        return False


def run_scheduled_automation(
    repository_root: Path,
    command: Sequence[str],
    output_dir: Path,
    lock_path: Path,
    *,
    trigger: str = "manual",
    trigger_id: str | None = None,
    timeout_seconds: int = 7200,
    stale_lock_seconds: int = 10800,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    root = repository_root.resolve()
    output_dir = output_dir.resolve()
    lock_path = lock_path.resolve()
    started_at = utc_now()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report_path = output_dir / f"schedule_run_{stamp}.json"
    acquired, lock_info, replaced_stale = acquire_scheduler_lock(
        lock_path, stale_after_seconds=stale_lock_seconds
    )
    report: dict[str, Any] = {
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "version": SCHEDULE_VERSION,
        "trigger": trigger,
        "trigger_id": trigger_id,
        "status": "running" if acquired else "skipped_locked",
        "started_at": started_at,
        "finished_at": None,
        "duration_ms": 0,
        "command": list(command),
        "lock_path": str(lock_path),
        "lock": lock_info,
        "recovered_stale_lock": replaced_stale is not None,
        "replaced_stale_lock": replaced_stale,
        "returncode": None,
        "stdout_tail": "",
        "stderr_tail": "",
    }
    if not acquired:
        report["finished_at"] = utc_now()
        _atomic_write_json(report_path, report)
        _atomic_write_json(output_dir / "latest_schedule.json", report)
        return report

    start_clock = time.perf_counter()
    try:
        completed = runner(
            list(command), cwd=root, text=True, capture_output=True,
            check=False, timeout=timeout_seconds,
        )
        report["returncode"] = completed.returncode
        report["stdout_tail"] = completed.stdout[-12000:]
        report["stderr_tail"] = completed.stderr[-12000:]
        report["status"] = "completed" if completed.returncode == 0 else "failed"
        try:
            parsed = json.loads(completed.stdout)
            if isinstance(parsed, dict):
                report["automation"] = parsed
        except json.JSONDecodeError:
            pass
    except subprocess.TimeoutExpired as exc:
        report["status"] = "timed_out"
        report["error"] = f"automation exceeded timeout_seconds={timeout_seconds}"
        report["stdout_tail"] = (exc.stdout or "")[-12000:] if isinstance(exc.stdout, str) else ""
        report["stderr_tail"] = (exc.stderr or "")[-12000:] if isinstance(exc.stderr, str) else ""
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        report["lock_released"] = release_scheduler_lock(lock_path, expected_pid=os.getpid())
        report["finished_at"] = utc_now()
        report["duration_ms"] = round((time.perf_counter() - start_clock) * 1000)
        _atomic_write_json(report_path, report)
        _atomic_write_json(output_dir / "latest_schedule.json", report)
    return report
