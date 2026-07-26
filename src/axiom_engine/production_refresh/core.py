from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

LAYERS = ("financial", "market", "estimate")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def coverage_snapshot(summary: dict[str, Any] | None) -> dict[str, dict[str, float | int]]:
    summary = summary or {}
    coverage = summary.get("coverage") if isinstance(summary.get("coverage"), dict) else {}
    legacy = summary.get("coverage_pct") if isinstance(summary.get("coverage_pct"), dict) else {}
    snapshot: dict[str, dict[str, float | int]] = {}
    for layer in LAYERS:
        item = coverage.get(layer) if isinstance(coverage.get(layer), dict) else {}
        usable = int(item.get("usable", 0) or 0)
        linked = int(item.get("linked", usable) or 0)
        usable_pct = float(item.get("usable_pct", legacy.get(layer, 0.0)) or 0.0)
        linked_pct = float(item.get("linked_pct", usable_pct) or 0.0)
        snapshot[layer] = {
            "linked_company_count": linked,
            "linked_coverage_pct": round(linked_pct, 4),
            "usable_company_count": usable,
            "usable_coverage_pct": round(usable_pct, 4),
        }
    readiness = summary.get("readiness") if isinstance(summary.get("readiness"), dict) else {}
    snapshot["production"] = {
        "ready_company_count": int(readiness.get("production_ready_company_count", 0) or 0)
    }
    return snapshot


def coverage_delta(before: dict[str, dict[str, float | int]], after: dict[str, dict[str, float | int]]) -> dict[str, dict[str, float | int]]:
    result: dict[str, dict[str, float | int]] = {}
    for layer in LAYERS:
        result[layer] = {
            "linked_company_count": int(after[layer]["linked_company_count"]) - int(before[layer]["linked_company_count"]),
            "linked_coverage_pct": round(float(after[layer]["linked_coverage_pct"]) - float(before[layer]["linked_coverage_pct"]), 4),
            "usable_company_count": int(after[layer]["usable_company_count"]) - int(before[layer]["usable_company_count"]),
            "usable_coverage_pct": round(float(after[layer]["usable_coverage_pct"]) - float(before[layer]["usable_coverage_pct"]), 4),
        }
    result["production"] = {
        "ready_company_count": int(after["production"]["ready_company_count"]) - int(before["production"]["ready_company_count"])
    }
    return result


def build_refresh_report(before_summary: dict[str, Any], after_summary: dict[str, Any], stages: list[dict[str, Any]]) -> dict[str, Any]:
    before = coverage_snapshot(before_summary)
    after = coverage_snapshot(after_summary)
    return {
        "schema_version": "production-refresh-report.v030.6.5",
        "version": "V030.6.5",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed" if all(stage.get("returncode") == 0 for stage in stages) else "failed",
        "stages": stages,
        "coverage_before": before,
        "coverage_after": after,
        "coverage_delta": coverage_delta(before, after),
    }


def run_refresh(
    repository_root: Path,
    commands: list[dict[str, Any]],
    output_path: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    summary_path = repository_root / "data/generated/production_population/production_population_summary.json"
    if not summary_path.exists():
        alternate = repository_root / "data/generated/production_population/population_summary.json"
        summary_path = alternate if alternate.exists() else summary_path
    before_summary = _read_json(summary_path)
    stages: list[dict[str, Any]] = []

    for spec in commands:
        argv = [str(x) for x in spec["argv"]]
        completed = runner(argv, cwd=repository_root, text=True, capture_output=True)
        stage = {
            "name": spec["name"],
            "returncode": int(completed.returncode),
            "command": argv,
            "stdout_tail": (completed.stdout or "")[-4000:],
            "stderr_tail": (completed.stderr or "")[-4000:],
        }
        stages.append(stage)
        if completed.returncode != 0:
            break

    after_summary = _read_json(summary_path)
    report = build_refresh_report(before_summary, after_summary, stages)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
