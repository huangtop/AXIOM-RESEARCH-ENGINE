from __future__ import annotations

import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

LAYERS = ("financial", "market", "estimate")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _read_json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("records", "companies", "rows", "data"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


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


def overlap_summary(index_rows: list[dict[str, Any]]) -> dict[str, Any]:
    combinations: Counter[str] = Counter()
    production_ready_ids: list[str] = []
    for row in index_rows:
        usability = row.get("data_usability") if isinstance(row.get("data_usability"), dict) else {}
        usable_layers = [layer for layer in LAYERS if bool(usability.get(layer))]
        key = "+".join(usable_layers) if usable_layers else "none"
        combinations[key] += 1
        if len(usable_layers) == len(LAYERS) and row.get("company_id"):
            production_ready_ids.append(str(row["company_id"]))
    return {
        "company_count": len(index_rows),
        "usable_layer_combinations": dict(sorted(combinations.items())),
        "production_ready_company_ids": production_ready_ids[:100],
        "production_ready_company_ids_truncated": len(production_ready_ids) > 100,
    }



def build_overlap_targets(
    index_rows: list[dict[str, Any]],
    *,
    max_targets: int = 200,
    preferred_missing_layers: list[str] | None = None,
) -> dict[str, Any]:
    """Build an auditable company-level queue for increasing cross-layer overlap.

    Tier 1 companies already have two usable layers and need exactly one more
    provider observation to become production-ready. Tier 2 companies have one
    usable layer and are retained as the next expansion pool.
    """
    layer_order = [layer for layer in (preferred_missing_layers or ["estimate", "market", "financial"]) if layer in LAYERS]
    layer_rank = {layer: i for i, layer in enumerate(layer_order)}
    candidates: list[dict[str, Any]] = []
    counts_by_missing_layer: Counter[str] = Counter()
    counts_by_tier: Counter[str] = Counter()

    for row in index_rows:
        usability = row.get("data_usability") if isinstance(row.get("data_usability"), dict) else {}
        usable_layers = [layer for layer in LAYERS if bool(usability.get(layer))]
        missing_layers = [layer for layer in LAYERS if layer not in usable_layers]
        if not missing_layers or not usable_layers:
            continue
        tier = "one_layer_to_ready" if len(missing_layers) == 1 else "two_layers_to_ready"
        if len(missing_layers) > 2:
            continue
        for layer in missing_layers:
            counts_by_missing_layer[layer] += 1
        counts_by_tier[tier] += 1
        identity = {
            key: row.get(key)
            for key in ("company_id", "company_name", "name", "ticker", "primary_ticker", "security_id", "cik")
            if row.get(key) not in (None, "", [])
        }
        candidates.append({
            **identity,
            "priority_tier": tier,
            "usable_layers": usable_layers,
            "missing_layers": missing_layers,
            "missing_layer_count": len(missing_layers),
            "production_ready_uplift_if_completed": 1 if len(missing_layers) == 1 else 0,
            "recommended_action": "populate_" + "_and_".join(missing_layers),
        })

    def sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
        missing = item["missing_layers"]
        first_rank = min((layer_rank.get(layer, len(LAYERS)) for layer in missing), default=len(LAYERS))
        return (item["missing_layer_count"], first_rank, str(item.get("company_id") or item.get("ticker") or ""))

    candidates.sort(key=sort_key)
    selected = candidates[:max(0, int(max_targets))]
    one_layer = [item for item in candidates if item["missing_layer_count"] == 1]
    return {
        "schema_version": "cross-layer-overlap-targets.v030.6.7",
        "version": "V030.6.7",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": "minimum_missing_layers_then_bottleneck_order",
        "company_count_evaluated": len(index_rows),
        "candidate_count": len(candidates),
        "immediate_ready_opportunity_count": len(one_layer),
        "potential_production_ready_uplift": len(one_layer),
        "counts_by_tier": dict(sorted(counts_by_tier.items())),
        "counts_by_missing_layer": dict(sorted(counts_by_missing_layer.items())),
        "target_count": len(selected),
        "targets_truncated": len(candidates) > len(selected),
        "targets": selected,
    }


def build_provider_worklists(
    overlap_targets: dict[str, Any],
    *,
    max_per_layer: int = 200,
) -> dict[str, Any]:
    """Convert overlap targets into provider-ready per-layer worklists."""
    targets = overlap_targets.get("targets") if isinstance(overlap_targets.get("targets"), list) else []
    worklists: dict[str, list[dict[str, Any]]] = {layer: [] for layer in LAYERS}
    for target in targets:
        if not isinstance(target, dict):
            continue
        missing_layers = target.get("missing_layers") if isinstance(target.get("missing_layers"), list) else []
        for layer in missing_layers:
            if layer not in worklists or len(worklists[layer]) >= max(0, int(max_per_layer)):
                continue
            identity = {
                key: target.get(key)
                for key in ("company_id", "company_name", "name", "ticker", "primary_ticker", "security_id", "cik")
                if target.get(key) not in (None, "", [])
            }
            immediate = int(target.get("missing_layer_count", 0) or 0) == 1
            required_fields = {
                "market": ["price", "currency", "session_date", "provider"],
                "estimate": ["forward_revenue_or_eps", "fiscal_period", "period_end", "provider"],
                "financial": ["metric", "value", "period_end", "provider"],
            }[layer]
            worklists[layer].append({
                **identity,
                "target_layer": layer,
                "priority_tier": target.get("priority_tier"),
                "priority_rank": len(worklists[layer]) + 1,
                "usable_layers": list(target.get("usable_layers") or []),
                "missing_layers": list(missing_layers),
                "required_fields": required_fields,
                "immediate_production_ready_uplift": immediate,
                "expected_ready_uplift": 1 if immediate else 0,
                "recommended_action": f"fetch_{layer}_provider_data",
            })
    counts = {layer: len(rows) for layer, rows in worklists.items()}
    immediate_counts = {
        layer: sum(1 for row in rows if row["immediate_production_ready_uplift"])
        for layer, rows in worklists.items()
    }
    return {
        "schema_version": "provider-population-worklists.v030.6.8",
        "version": "V030.6.8",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": "cross_layer_overlap_then_provider_layer",
        "source_target_schema_version": overlap_targets.get("schema_version"),
        "counts_by_layer": counts,
        "immediate_ready_opportunities_by_layer": immediate_counts,
        "potential_production_ready_uplift": sum(immediate_counts.values()),
        "worklists": worklists,
    }

def _write_worklist_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "priority_rank", "company_id", "ticker", "primary_ticker", "security_id", "cik",
        "company_name", "name", "target_layer", "priority_tier",
        "immediate_production_ready_uplift", "expected_ready_uplift",
        "usable_layers", "missing_layers", "required_fields", "recommended_action",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            for key in ("usable_layers", "missing_layers", "required_fields"):
                flat[key] = "|".join(str(x) for x in (row.get(key) or []))
            writer.writerow(flat)

def build_readiness_assessment(
    after: dict[str, dict[str, float | int]],
    delta: dict[str, dict[str, float | int]],
    index_rows: list[dict[str, Any]],
    policy: dict[str, Any] | None,
    stages: list[dict[str, Any]],
) -> dict[str, Any]:
    policy = policy or {}
    layer_minimums = policy.get("layer_minimums") if isinstance(policy.get("layer_minimums"), dict) else {}
    minimum_ready = int(policy.get("minimum_production_ready_company_count", 1) or 0)
    fail_on_regression = bool(policy.get("fail_on_coverage_regression", True))
    universe_count = len(index_rows)
    checks: list[dict[str, Any]] = []

    pipeline_passed = bool(stages) and all(stage.get("returncode") == 0 for stage in stages)
    checks.append({
        "name": "pipeline_completed",
        "passed": pipeline_passed,
        "actual": sum(1 for stage in stages if stage.get("returncode") == 0),
        "required": len(stages),
    })

    for layer in LAYERS:
        minimum = layer_minimums.get(layer) if isinstance(layer_minimums.get(layer), dict) else {}
        required_count = int(minimum.get("usable_company_count", 0) or 0)
        required_pct = float(minimum.get("usable_coverage_pct", 0.0) or 0.0)
        actual_count = int(after[layer]["usable_company_count"])
        actual_pct = float(after[layer]["usable_coverage_pct"])
        checks.append({
            "name": f"{layer}_usable_minimum",
            "passed": actual_count >= required_count and actual_pct >= required_pct,
            "actual": {"usable_company_count": actual_count, "usable_coverage_pct": actual_pct},
            "required": {"usable_company_count": required_count, "usable_coverage_pct": required_pct},
            "gap": {
                "usable_company_count": max(0, required_count - actual_count),
                "usable_coverage_pct": round(max(0.0, required_pct - actual_pct), 4),
            },
        })

    actual_ready = int(after["production"]["ready_company_count"])
    checks.append({
        "name": "production_ready_minimum",
        "passed": actual_ready >= minimum_ready,
        "actual": actual_ready,
        "required": minimum_ready,
        "gap": max(0, minimum_ready - actual_ready),
    })

    regressions = {
        layer: int(delta[layer]["usable_company_count"])
        for layer in LAYERS
        if int(delta[layer]["usable_company_count"]) < 0
    }
    if int(delta["production"]["ready_company_count"]) < 0:
        regressions["production"] = int(delta["production"]["ready_company_count"])
    checks.append({
        "name": "no_coverage_regression",
        "passed": not fail_on_regression or not regressions,
        "actual": regressions,
        "required": "no negative usable-company delta" if fail_on_regression else "not enforced",
    })

    blockers = [check["name"] for check in checks if not check["passed"]]
    overlap = overlap_summary(index_rows)
    layer_gaps = {
        layer: {
            "usable_company_count": int(after[layer]["usable_company_count"]),
            "missing_to_universe": max(0, universe_count - int(after[layer]["usable_company_count"])),
        }
        for layer in LAYERS
    }
    bottleneck_order = sorted(LAYERS, key=lambda layer: (int(after[layer]["usable_company_count"]), layer))
    next_actions: list[str] = []
    if not pipeline_passed:
        next_actions.append("fix_failed_refresh_stage")
    if actual_ready < minimum_ready:
        next_actions.append("increase_cross_layer_company_overlap")
    for layer in bottleneck_order:
        check = next(c for c in checks if c["name"] == f"{layer}_usable_minimum")
        if not check["passed"]:
            next_actions.append(f"expand_{layer}_provider_population")
    if regressions:
        next_actions.append("investigate_coverage_regression")

    overlap_targets = build_overlap_targets(index_rows, preferred_missing_layers=bottleneck_order)

    return {
        "status": "qualified" if not blockers else "blocked",
        "policy_version": str(policy.get("version") or "V030.6.6-default"),
        "checks": checks,
        "blockers": blockers,
        "layer_gaps": layer_gaps,
        "bottleneck_order": bottleneck_order,
        "overlap": overlap,
        "overlap_targeting_summary": {key: value for key, value in overlap_targets.items() if key != "targets"},
        "next_actions": list(dict.fromkeys(next_actions)),
    }


def build_refresh_report(
    before_summary: dict[str, Any],
    after_summary: dict[str, Any],
    stages: list[dict[str, Any]],
    *,
    index_rows: list[dict[str, Any]] | None = None,
    readiness_policy: dict[str, Any] | None = None,
    overlap_targeting: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before = coverage_snapshot(before_summary)
    after = coverage_snapshot(after_summary)
    delta = coverage_delta(before, after)
    rows = index_rows or []
    assessment = build_readiness_assessment(after, delta, rows, readiness_policy, stages)
    targeting_config = overlap_targeting or {}
    targets = build_overlap_targets(
        rows,
        max_targets=int(targeting_config.get("max_targets", 200) or 200),
        preferred_missing_layers=targeting_config.get("preferred_missing_layers"),
    )
    pipeline_completed = all(stage.get("returncode") == 0 for stage in stages)
    return {
        "schema_version": "production-refresh-report.v030.6.8",
        "version": "V030.6.8",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed" if pipeline_completed else "failed",
        "stages": stages,
        "coverage_before": before,
        "coverage_after": after,
        "coverage_delta": delta,
        "readiness_assessment": assessment,
        "overlap_targets": targets,
    }


def run_refresh(
    repository_root: Path,
    commands: list[dict[str, Any]],
    output_path: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    *,
    readiness_policy: dict[str, Any] | None = None,
    overlap_targeting: dict[str, Any] | None = None,
    targets_output_path: Path | None = None,
    worklists_output_dir: Path | None = None,
    max_worklist_rows_per_layer: int = 200,
) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    summary_path = repository_root / "data/generated/production_population/production_population_summary.json"
    if not summary_path.exists():
        alternate = repository_root / "data/generated/production_population/population_summary.json"
        summary_path = alternate if alternate.exists() else summary_path
    index_path = repository_root / "data/generated/production_population/population_index.json"
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
    index_rows = _read_json_rows(index_path)
    report = build_refresh_report(
        before_summary,
        after_summary,
        stages,
        index_rows=index_rows,
        readiness_policy=readiness_policy,
        overlap_targeting=overlap_targeting,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if targets_output_path is not None:
        targets_output_path.parent.mkdir(parents=True, exist_ok=True)
        targets_output_path.write_text(json.dumps(report["overlap_targets"], ensure_ascii=False, indent=2), encoding="utf-8")
    worklists = build_provider_worklists(
        report["overlap_targets"], max_per_layer=max_worklist_rows_per_layer
    )
    report["provider_worklists_summary"] = {
        key: value for key, value in worklists.items() if key != "worklists"
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if worklists_output_dir is not None:
        worklists_output_dir.mkdir(parents=True, exist_ok=True)
        (worklists_output_dir / "provider_worklists.json").write_text(
            json.dumps(worklists, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for layer, rows in worklists["worklists"].items():
            (worklists_output_dir / f"{layer}_population_worklist.json").write_text(
                json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            _write_worklist_csv(worklists_output_dir / f"{layer}_population_worklist.csv", rows)
    return report
