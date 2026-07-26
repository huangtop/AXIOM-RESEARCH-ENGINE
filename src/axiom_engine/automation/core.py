from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

SCHEMA_VERSION = "automation-run.v030.8.1"
VERSION = "V030.8.1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_run_id(started_at: str, stage_names: Sequence[str]) -> str:
    payload = f"{started_at}|{'|'.join(stage_names)}|{os.getpid()}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"automation-run:{digest}"


def _tail(value: str, limit: int = 12000) -> str:
    return value if len(value) <= limit else value[-limit:]


def _parse_json_tail(stdout: str) -> Mapping[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, Mapping) else None
    except json.JSONDecodeError:
        pass
    starts = [index for index, char in enumerate(text) if char == "{"]
    for index in reversed(starts):
        try:
            parsed = json.loads(text[index:])
            if isinstance(parsed, Mapping):
                return parsed
        except json.JSONDecodeError:
            continue
    return None


def normalize_stage_specs(specs: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, source in enumerate(specs):
        spec = dict(source)
        name = str(spec.get("name", "")).strip()
        argv = spec.get("argv")
        if not name:
            raise ValueError(f"stage {index} is missing name")
        if name in names:
            raise ValueError(f"duplicate stage name: {name}")
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
            raise ValueError(f"stage {name} has invalid argv")
        names.add(name)
        normalized.append(
            {
                "name": name,
                "argv": list(argv),
                "required": bool(spec.get("required", True)),
                "supports_strict": bool(spec.get("supports_strict", True)),
                "expected_report": spec.get("expected_report"),
            }
        )
    if not normalized:
        raise ValueError("automation requires at least one stage")
    return normalized


def _stage_result(
    *,
    name: str,
    argv: Sequence[str],
    required: bool,
    started_at: str,
    finished_at: str,
    duration_ms: int,
    returncode: int | None,
    status: str,
    stdout: str = "",
    stderr: str = "",
    report: Mapping[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "status": status,
        "required": required,
        "argv": list(argv),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "returncode": returncode,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
    }
    if report is not None:
        result["report"] = dict(report)
    if error:
        result["error"] = error
    return result


def run_automation(
    repository_root: Path,
    stage_specs: Iterable[Mapping[str, Any]],
    output_path: Path,
    *,
    strict: bool = False,
    continue_on_failure: bool = False,
    dry_run: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    root = repository_root.resolve()
    specs = normalize_stage_specs(stage_specs)
    started_at = utc_now()
    run_id = stable_run_id(started_at, [spec["name"] for spec in specs])
    stages: list[dict[str, Any]] = []
    blocked = False

    for spec in specs:
        argv = list(spec["argv"])
        if strict and spec["supports_strict"] and "--strict" not in argv:
            argv.append("--strict")

        if blocked:
            now = utc_now()
            stages.append(
                _stage_result(
                    name=spec["name"], argv=argv, required=spec["required"],
                    started_at=now, finished_at=now, duration_ms=0,
                    returncode=None, status="skipped", error="blocked_by_previous_failure",
                )
            )
            continue

        if dry_run:
            now = utc_now()
            stages.append(
                _stage_result(
                    name=spec["name"], argv=argv, required=spec["required"],
                    started_at=now, finished_at=now, duration_ms=0,
                    returncode=None, status="planned",
                )
            )
            continue

        stage_started = utc_now()
        start_clock = time.perf_counter()
        try:
            completed = runner(
                argv,
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            duration_ms = round((time.perf_counter() - start_clock) * 1000)
            stage_finished = utc_now()
            report = _parse_json_tail(completed.stdout)
            status = "completed" if completed.returncode == 0 else "failed"
            result = _stage_result(
                name=spec["name"], argv=argv, required=spec["required"],
                started_at=stage_started, finished_at=stage_finished,
                duration_ms=duration_ms, returncode=completed.returncode,
                status=status, stdout=completed.stdout, stderr=completed.stderr,
                report=report,
            )
        except Exception as exc:  # boundary around external stage execution
            duration_ms = round((time.perf_counter() - start_clock) * 1000)
            stage_finished = utc_now()
            result = _stage_result(
                name=spec["name"], argv=argv, required=spec["required"],
                started_at=stage_started, finished_at=stage_finished,
                duration_ms=duration_ms, returncode=None, status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )

        stages.append(result)
        if result["status"] == "failed" and spec["required"] and not continue_on_failure:
            blocked = True

    finished_at = utc_now()
    failed = [stage for stage in stages if stage["status"] == "failed"]
    required_failed = [stage for stage in failed if stage["required"]]
    status = "planned" if dry_run else ("failed" if required_failed else ("completed_with_warnings" if failed else "completed"))
    total_duration_ms = sum(int(stage["duration_ms"]) for stage in stages)

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "run_id": run_id,
        "status": status,
        "strict": strict,
        "dry_run": dry_run,
        "continue_on_failure": continue_on_failure,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": total_duration_ms,
        "stage_count": len(stages),
        "completed_stage_count": sum(stage["status"] == "completed" for stage in stages),
        "failed_stage_count": len(failed),
        "skipped_stage_count": sum(stage["status"] == "skipped" for stage in stages),
        "stages": stages,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    latest_path = output_path.parent / "latest.json"
    latest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        key: report[key]
        for key in (
            "schema_version", "version", "run_id", "status", "started_at", "finished_at",
            "duration_ms", "stage_count", "completed_stage_count", "failed_stage_count", "skipped_stage_count",
        )
    }
    (output_path.parent / "automation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    failures = [stage for stage in stages if stage["status"] == "failed"]
    (output_path.parent / "automation_failures.json").write_text(
        json.dumps({"run_id": run_id, "failures": failures}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report
