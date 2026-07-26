from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

SCHEMA_VERSION = "automation-run.v030.8.5"
STATE_SCHEMA_VERSION = "automation-state.v030.8.5"
VERSION = "V030.8.5"
TERMINAL_STAGE_STATES = {"completed", "failed", "skipped"}


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
    for index in reversed([i for i, char in enumerate(text) if char == "{"]):
        try:
            parsed = json.loads(text[index:])
            if isinstance(parsed, Mapping):
                return parsed
        except json.JSONDecodeError:
            continue
    return None


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


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
        normalized.append({
            "name": name,
            "argv": list(argv),
            "required": bool(spec.get("required", True)),
            "supports_strict": bool(spec.get("supports_strict", True)),
            "expected_report": spec.get("expected_report"),
            "run_if_report": spec.get("run_if_report"),
        })
    if not normalized:
        raise ValueError("automation requires at least one stage")
    return normalized


def _new_stage_state(spec: Mapping[str, Any], argv: Sequence[str]) -> dict[str, Any]:
    return {
        "name": spec["name"],
        "status": "pending",
        "required": spec["required"],
        "argv": list(argv),
        "attempt_count": 0,
        "started_at": None,
        "finished_at": None,
        "duration_ms": 0,
        "returncode": None,
        "stdout_tail": "",
        "stderr_tail": "",
    }


def load_automation_state(path: Path) -> dict[str, Any]:
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or not isinstance(state.get("stages"), list):
        raise ValueError(f"invalid automation state: {path}")
    # A process may die after persisting RUNNING but before persisting its result.
    for stage in state["stages"]:
        if stage.get("status") == "running":
            stage["status"] = "interrupted"
            stage["error"] = "previous_process_interrupted"
            stage["finished_at"] = utc_now()
    if state.get("status") == "running":
        state["status"] = "interrupted"
    return state


def _prepare_state(
    specs: Sequence[Mapping[str, Any]], *, strict: bool, continue_on_failure: bool,
    dry_run: bool, resume_state: Mapping[str, Any] | None, retry_failed: bool,
    skip_stages: set[str],
) -> dict[str, Any]:
    argv_by_name: dict[str, list[str]] = {}
    for spec in specs:
        argv = list(spec["argv"])
        if strict and spec["supports_strict"] and "--strict" not in argv:
            argv.append("--strict")
        argv_by_name[spec["name"]] = argv

    if resume_state is None:
        started_at = utc_now()
        state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "version": VERSION,
            "run_id": stable_run_id(started_at, [spec["name"] for spec in specs]),
            "status": "planned" if dry_run else "pending",
            "strict": strict,
            "dry_run": dry_run,
            "continue_on_failure": continue_on_failure,
            "started_at": started_at,
            "updated_at": started_at,
            "finished_at": None,
            "resume_count": 0,
            "stages": [_new_stage_state(spec, argv_by_name[spec["name"]]) for spec in specs],
        }
    else:
        state = dict(resume_state)
        existing = {stage["name"]: dict(stage) for stage in state.get("stages", [])}
        configured_names = [spec["name"] for spec in specs]
        if set(existing) != set(configured_names):
            raise ValueError("resume state stages do not match current automation config")
        state.update({
            "schema_version": STATE_SCHEMA_VERSION,
            "version": VERSION,
            "status": "pending",
            "strict": strict,
            "dry_run": dry_run,
            "continue_on_failure": continue_on_failure,
            "updated_at": utc_now(),
            "finished_at": None,
            "resume_count": int(state.get("resume_count", 0)) + 1,
        })
        rebuilt: list[dict[str, Any]] = []
        for spec in specs:
            stage = existing[spec["name"]]
            stage["argv"] = argv_by_name[spec["name"]]
            stage["required"] = spec["required"]
            previous_status = stage.get("status")
            if previous_status in {"interrupted", "running", "pending", "planned"}:
                stage["status"] = "pending"
            elif previous_status == "skipped" and stage.get("error") == "blocked_by_previous_failure":
                stage["status"] = "pending"
            elif previous_status == "failed" and retry_failed:
                stage["status"] = "pending"
            rebuilt.append(stage)
        state["stages"] = rebuilt

    unknown_skips = skip_stages - {stage["name"] for stage in state["stages"]}
    if unknown_skips:
        raise ValueError(f"unknown skip stages: {', '.join(sorted(unknown_skips))}")
    for stage in state["stages"]:
        if stage["name"] in skip_stages and stage["status"] not in {"completed"}:
            now = utc_now()
            stage.update({"status": "skipped", "started_at": now, "finished_at": now,
                          "duration_ms": 0, "returncode": None, "error": "explicitly_skipped"})
    return state


def run_automation(
    repository_root: Path,
    stage_specs: Iterable[Mapping[str, Any]],
    output_path: Path,
    *,
    strict: bool = False,
    continue_on_failure: bool = False,
    dry_run: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    state_path: Path | None = None,
    resume_state: Mapping[str, Any] | None = None,
    retry_failed: bool = False,
    skip_stages: Iterable[str] = (),
) -> dict[str, Any]:
    root = repository_root.resolve()
    specs = normalize_stage_specs(stage_specs)
    output_path = output_path.resolve()
    state_path = (state_path or output_path.with_name(f"{output_path.stem}.state.json")).resolve()
    state = _prepare_state(
        specs, strict=strict, continue_on_failure=continue_on_failure, dry_run=dry_run,
        resume_state=resume_state, retry_failed=retry_failed, skip_stages=set(skip_stages),
    )
    state["state_path"] = str(state_path)
    _atomic_write_json(state_path, state)

    blocked = False
    for stage in state["stages"]:
        status = stage.get("status")
        if status == "completed" or status == "skipped":
            continue
        if status == "failed" and not retry_failed:
            if stage.get("required") and not continue_on_failure:
                blocked = True
            continue
        if blocked:
            now = utc_now()
            stage.update({"status": "skipped", "started_at": now, "finished_at": now,
                          "duration_ms": 0, "returncode": None, "error": "blocked_by_previous_failure"})
            state["updated_at"] = now
            _atomic_write_json(state_path, state)
            continue
        if dry_run:
            now = utc_now()
            stage.update({"status": "planned", "started_at": now, "finished_at": now,
                          "duration_ms": 0, "returncode": None})
            state["updated_at"] = now
            _atomic_write_json(state_path, state)
            continue

        spec = next(item for item in specs if item["name"] == stage["name"])
        condition = spec.get("run_if_report")
        if condition:
            report_path = root / str(condition.get("path", ""))
            allowed = set(condition.get("field_in", []))
            field = str(condition.get("field", "status"))
            try:
                condition_report = json.loads(report_path.read_text(encoding="utf-8"))
                actual = condition_report.get(field)
            except (OSError, json.JSONDecodeError):
                actual = None
            if actual not in allowed:
                now = utc_now()
                stage.update({"status": "skipped", "started_at": now, "finished_at": now,
                              "duration_ms": 0, "returncode": None,
                              "error": "condition_not_met",
                              "condition": {"path": str(report_path), "field": field,
                                            "actual": actual, "allowed": sorted(allowed)}})
                state["updated_at"] = now
                _atomic_write_json(state_path, state)
                continue

        stage_started = utc_now()
        stage.update({"status": "running", "started_at": stage_started, "finished_at": None,
                      "attempt_count": int(stage.get("attempt_count", 0)) + 1,
                      "error": None, "stdout_tail": "", "stderr_tail": ""})
        state["status"] = "running"
        state["updated_at"] = stage_started
        _atomic_write_json(state_path, state)
        start_clock = time.perf_counter()
        try:
            completed = runner(stage["argv"], cwd=root, text=True, capture_output=True, check=False)
            duration_ms = round((time.perf_counter() - start_clock) * 1000)
            stage.update({
                "status": "completed" if completed.returncode == 0 else "failed",
                "finished_at": utc_now(), "duration_ms": duration_ms,
                "returncode": completed.returncode, "stdout_tail": _tail(completed.stdout),
                "stderr_tail": _tail(completed.stderr),
            })
            parsed = _parse_json_tail(completed.stdout)
            if parsed is not None:
                stage["report"] = dict(parsed)
        except Exception as exc:
            stage.update({"status": "failed", "finished_at": utc_now(),
                          "duration_ms": round((time.perf_counter() - start_clock) * 1000),
                          "returncode": None, "error": f"{type(exc).__name__}: {exc}"})
        state["updated_at"] = utc_now()
        _atomic_write_json(state_path, state)
        if stage["status"] == "failed" and stage["required"] and not continue_on_failure:
            blocked = True

    stages = state["stages"]
    failed = [stage for stage in stages if stage["status"] == "failed"]
    interrupted = [stage for stage in stages if stage["status"] == "interrupted"]
    required_failed = [stage for stage in failed if stage["required"]]
    if dry_run:
        final_status = "planned"
    elif interrupted:
        final_status = "interrupted"
    elif required_failed:
        final_status = "failed"
    elif failed:
        final_status = "completed_with_warnings"
    else:
        final_status = "completed"
    finished_at = utc_now()
    state.update({"status": final_status, "updated_at": finished_at, "finished_at": finished_at})
    _atomic_write_json(state_path, state)

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "run_id": state["run_id"],
        "status": final_status,
        "state_path": str(state_path),
        "strict": strict,
        "dry_run": dry_run,
        "continue_on_failure": continue_on_failure,
        "retry_failed": retry_failed,
        "resume_count": state.get("resume_count", 0),
        "started_at": state["started_at"],
        "finished_at": finished_at,
        "duration_ms": sum(int(stage.get("duration_ms", 0)) for stage in stages),
        "stage_count": len(stages),
        "pending_stage_count": sum(stage["status"] == "pending" for stage in stages),
        "running_stage_count": sum(stage["status"] == "running" for stage in stages),
        "completed_stage_count": sum(stage["status"] == "completed" for stage in stages),
        "failed_stage_count": len(failed),
        "skipped_stage_count": sum(stage["status"] == "skipped" for stage in stages),
        "stages": stages,
    }
    _atomic_write_json(output_path, report)
    _atomic_write_json(output_path.parent / "latest.json", report)
    summary_keys = ("schema_version", "version", "run_id", "status", "state_path", "started_at",
                    "finished_at", "duration_ms", "stage_count", "completed_stage_count",
                    "failed_stage_count", "skipped_stage_count", "resume_count")
    _atomic_write_json(output_path.parent / "automation_summary.json", {key: report[key] for key in summary_keys})
    _atomic_write_json(output_path.parent / "automation_failures.json", {"run_id": state["run_id"], "failures": failed})
    if not dry_run:
        from .monitoring import record_automation_run
        record_automation_run(root, report, output_path.parent)
    return report
