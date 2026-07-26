from __future__ import annotations

import json
import subprocess
import hashlib
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



def build_provider_batch_contracts(provider_worklists: dict[str, Any]) -> dict[str, Any]:
    """Build deterministic request contracts and response templates for provider batches."""
    worklists = provider_worklists.get("worklists") if isinstance(provider_worklists.get("worklists"), dict) else {}
    batches: dict[str, dict[str, Any]] = {}
    for layer in LAYERS:
        rows = worklists.get(layer) if isinstance(worklists.get(layer), list) else []
        requests: list[dict[str, Any]] = []
        for row in rows:
            company_id = str(row.get("company_id") or "")
            ticker = str(row.get("ticker") or row.get("primary_ticker") or "")
            raw = f"V030.6.9|{layer}|{company_id}|{ticker}"
            request_id = "provider-request:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
            requests.append({
                "request_id": request_id,
                "target_layer": layer,
                "company_id": company_id,
                "ticker": ticker or None,
                "priority_rank": row.get("priority_rank"),
                "priority_tier": row.get("priority_tier"),
                "immediate_production_ready_uplift": bool(row.get("immediate_production_ready_uplift")),
                "required_fields": list(row.get("required_fields") or []),
            })
        batch_seed = "|".join(request["request_id"] for request in requests)
        batch_id = f"provider-batch:{layer}:" + hashlib.sha256(batch_seed.encode("utf-8")).hexdigest()[:16]
        batches[layer] = {
            "schema_version": "provider-batch-request.v030.6.9",
            "version": "V030.6.9",
            "batch_id": batch_id,
            "target_layer": layer,
            "request_count": len(requests),
            "requests": requests,
            "response_contract": {
                "schema_version": "provider-batch-response.v030.6.9",
                "required_envelope_fields": ["schema_version", "batch_id", "target_layer", "provider", "observations"],
                "observation_required_fields": ["request_id", "company_id", "provider_record_id", "observed_at", "data"],
            },
        }
    return {
        "schema_version": "provider-batch-contracts.v030.6.9",
        "version": "V030.6.9",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "batch_count": len(LAYERS),
        "request_count_by_layer": {layer: batches[layer]["request_count"] for layer in LAYERS},
        "batches": batches,
    }


def validate_provider_batch_response(response: dict[str, Any], batch_request: dict[str, Any]) -> dict[str, Any]:
    """Validate identity, envelope, duplicates and minimum provider observation fields."""
    errors: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    expected = {str(r.get("request_id")): r for r in batch_request.get("requests", []) if isinstance(r, dict)}
    if response.get("schema_version") != "provider-batch-response.v030.6.9":
        errors.append({"reason": "invalid_schema_version"})
    for key in ("batch_id", "target_layer"):
        if response.get(key) != batch_request.get(key):
            errors.append({"reason": f"{key}_mismatch", "actual": response.get(key), "expected": batch_request.get(key)})
    if not response.get("provider"):
        errors.append({"reason": "missing_provider"})
    observations = response.get("observations") if isinstance(response.get("observations"), list) else []
    seen: set[str] = set()
    rejected: list[dict[str, Any]] = []
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            rejected.append({"index": index, "reason": "observation_not_object"}); continue
        request_id = str(observation.get("request_id") or "")
        request = expected.get(request_id)
        reason = None
        if not request:
            reason = "unknown_request_id"
        elif request_id in seen:
            reason = "duplicate_request_id"
        elif observation.get("company_id") != request.get("company_id"):
            reason = "company_id_mismatch"
        elif not observation.get("provider_record_id"):
            reason = "missing_provider_record_id"
        elif not observation.get("observed_at"):
            reason = "missing_observed_at"
        elif not isinstance(observation.get("data"), dict) or not observation.get("data"):
            reason = "missing_data"
        if reason:
            rejected.append({"index": index, "request_id": request_id or None, "reason": reason})
        else:
            seen.add(request_id); accepted.append(observation)
    return {
        "schema_version": "provider-batch-validation.v030.6.9",
        "version": "V030.6.9",
        "batch_id": batch_request.get("batch_id"),
        "target_layer": batch_request.get("target_layer"),
        "valid": not errors and not rejected,
        "envelope_errors": errors,
        "observation_count": len(observations),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "unfulfilled_request_count": len(expected) - len(seen),
        "rejected_observations": rejected,
        "accepted_observations": accepted,
    }


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
        "schema_version": "production-refresh-report.v030.7.0",
        "version": "V030.7.0",
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
    contracts_output_dir: Path | None = None,
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
    contracts = build_provider_batch_contracts(worklists)
    report["provider_batch_contracts_summary"] = {
        key: value for key, value in contracts.items() if key != "batches"
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if contracts_output_dir is not None:
        contracts_output_dir.mkdir(parents=True, exist_ok=True)
        (contracts_output_dir / "provider_batch_contracts.json").write_text(
            json.dumps(contracts, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for layer, batch in contracts["batches"].items():
            (contracts_output_dir / f"{layer}_batch_request.json").write_text(
                json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            template = {
                "schema_version": "provider-batch-response.v030.6.9",
                "batch_id": batch["batch_id"],
                "target_layer": layer,
                "provider": "REPLACE_WITH_PROVIDER",
                "observations": [],
            }
            (contracts_output_dir / f"{layer}_batch_response.template.json").write_text(
                json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    return report



def _stable_provider_fact_id(layer: str, provider: str, provider_record_id: str, company_id: str) -> str:
    seed = f"V030.7.0|{layer}|{provider}|{provider_record_id}|{company_id}"
    return f"provider-fact:{layer}:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:28]


def canonicalize_provider_observation(
    observation: dict[str, Any],
    *,
    provider: str,
    target_layer: str,
    request: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Convert one validated provider observation into a canonical population fact."""
    data = observation.get("data") if isinstance(observation.get("data"), dict) else {}
    company_id = str(request.get("company_id") or observation.get("company_id") or "")
    provider_record_id = str(observation.get("provider_record_id") or "")
    base = {
        "record_id": _stable_provider_fact_id(target_layer, provider, provider_record_id, company_id),
        "semantic_type": f"{target_layer}_fact",
        "company_id": company_id,
        "ticker": request.get("ticker") or None,
        "provider": provider,
        "provider_record_id": provider_record_id,
        "observed_at": observation.get("observed_at"),
        "source_request_id": observation.get("request_id"),
        "source_batch_id": observation.get("batch_id"),
        "record_state": "provider_observed",
        "provenance_ids": [provider_record_id, str(observation.get("request_id") or "")],
    }
    if target_layer == "market":
        price = data.get("price", data.get("close", data.get("previous_close")))
        try:
            price = float(price)
        except (TypeError, ValueError):
            return None, "invalid_market_price"
        session_date = data.get("session_date") or data.get("market_date") or data.get("date")
        currency = data.get("currency")
        if not session_date:
            return None, "missing_session_date"
        if not currency:
            return None, "missing_currency"
        return {
            **base,
            "price": price,
            "currency": str(currency),
            "session_date": str(session_date),
            "market_state": data.get("market_state") or "historical",
            "exchange_timezone": data.get("exchange_timezone"),
        }, None
    if target_layer == "estimate":
        metric_aliases = {
            "forward_revenue": "forward_revenue", "revenue": "forward_revenue", "sales": "forward_revenue",
            "forward_eps": "forward_eps", "eps": "forward_eps", "diluted_eps": "forward_eps",
            "forward_ebit": "forward_ebit", "ebit": "forward_ebit",
            "forward_ebitda": "forward_ebitda", "ebitda": "forward_ebitda",
            "target_price": "target_price",
        }
        metric = data.get("metric")
        value = data.get("value")
        if metric is None:
            for key in metric_aliases:
                if data.get(key) is not None:
                    metric, value = key, data.get(key)
                    break
        canonical_metric = metric_aliases.get(str(metric or "").lower())
        if not canonical_metric:
            return None, "unsupported_estimate_metric"
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None, "invalid_estimate_value"
        period_end = data.get("period_end")
        fiscal_period = data.get("fiscal_period")
        if not period_end and not fiscal_period:
            return None, "missing_estimate_period"
        return {
            **base,
            "metric": canonical_metric,
            "value": value,
            "currency": data.get("currency"),
            "unit": data.get("unit"),
            "estimate_kind": data.get("estimate_kind") or "consensus",
            "analyst_count": data.get("analyst_count"),
            "fiscal_year": data.get("fiscal_year"),
            "fiscal_period": fiscal_period,
            "period_end": period_end,
        }, None
    if target_layer == "financial":
        metric = data.get("metric")
        value = data.get("value")
        if not metric:
            return None, "missing_financial_metric"
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None, "invalid_financial_value"
        if not data.get("period_end"):
            return None, "missing_period_end"
        return {
            **base,
            "metric": str(metric),
            "value": value,
            "currency": data.get("currency"),
            "unit": data.get("unit"),
            "period_start": data.get("period_start"),
            "period_end": data.get("period_end"),
            "fiscal_year": data.get("fiscal_year"),
            "fiscal_period": data.get("fiscal_period"),
            "statement": data.get("statement"),
        }, None
    return None, "unsupported_target_layer"


def merge_provider_facts(existing_rows: list[dict[str, Any]], incoming_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    """Merge by stable record_id; incoming provider observations replace older duplicates."""
    merged = {str(row.get("record_id") or ""): row for row in existing_rows if isinstance(row, dict) and row.get("record_id")}
    inserted = updated = 0
    for row in incoming_rows:
        record_id = str(row.get("record_id") or "")
        if not record_id:
            continue
        if record_id in merged:
            updated += 1
        else:
            inserted += 1
        merged[record_id] = row
    return sorted(merged.values(), key=lambda row: (str(row.get("company_id") or ""), str(row.get("record_id") or ""))), inserted, updated


def import_provider_batch_response(
    response: dict[str, Any],
    batch_request: dict[str, Any],
    existing_ledger_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate a provider response, canonicalize accepted observations and merge the persistent ledger."""
    validation = validate_provider_batch_response(response, batch_request)
    provider = str(response.get("provider") or "")
    layer = str(batch_request.get("target_layer") or "")
    request_map = {str(row.get("request_id")): row for row in batch_request.get("requests", []) if isinstance(row, dict)}
    canonical_rows: list[dict[str, Any]] = []
    canonical_rejections: list[dict[str, Any]] = []
    if not validation["envelope_errors"]:
        for observation in validation["accepted_observations"]:
            request = request_map.get(str(observation.get("request_id") or ""), {})
            enriched = dict(observation)
            enriched["batch_id"] = response.get("batch_id")
            row, reason = canonicalize_provider_observation(
                enriched, provider=provider, target_layer=layer, request=request
            )
            if reason:
                canonical_rejections.append({"request_id": observation.get("request_id"), "reason": reason})
            elif row:
                canonical_rows.append(row)
    merged, inserted, updated = merge_provider_facts(existing_ledger_rows or [], canonical_rows)
    valid = bool(validation["valid"] and not canonical_rejections)
    return {
        "schema_version": "provider-response-import-report.v030.7.0",
        "version": "V030.7.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "valid": valid,
        "batch_id": batch_request.get("batch_id"),
        "target_layer": layer,
        "provider": provider,
        "validation": {key: value for key, value in validation.items() if key != "accepted_observations"},
        "canonicalized_count": len(canonical_rows),
        "canonical_rejected_count": len(canonical_rejections),
        "canonical_rejections": canonical_rejections,
        "inserted_count": inserted,
        "updated_count": updated,
        "ledger_record_count": len(merged),
        "canonical_rows": canonical_rows,
        "ledger_rows": merged,
    }


def merge_intake_ledger_into_production_source(
    ledger_rows: list[dict[str, Any]],
    production_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged, _, _ = merge_provider_facts(production_rows, ledger_rows)
    return merged


def provider_response_content_hash(payload: bytes | str | dict[str, Any]) -> str:
    """Return a deterministic SHA-256 digest for replay protection."""
    if isinstance(payload, dict):
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = payload
    return hashlib.sha256(raw).hexdigest()


def build_provider_intake_receipt(
    *,
    response_path: str,
    content_hash: str,
    status: str,
    layer: str | None = None,
    import_report: dict[str, Any] | None = None,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    """Build the durable receipt used by the provider intake lifecycle."""
    report = import_report or {}
    return {
        "schema_version": "provider-intake-receipt.v030.7.1",
        "version": "V030.7.1",
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "response_path": response_path,
        "content_sha256": content_hash,
        "status": status,
        "target_layer": layer or report.get("target_layer"),
        "batch_id": report.get("batch_id"),
        "provider": report.get("provider"),
        "canonicalized_count": int(report.get("canonicalized_count", 0) or 0),
        "inserted_count": int(report.get("inserted_count", 0) or 0),
        "updated_count": int(report.get("updated_count", 0) or 0),
        "failure_reason": failure_reason,
    }


def provider_archive_filename(original_name: str, content_hash: str, *, status: str) -> str:
    """Create a collision-resistant, deterministic archive filename."""
    path = Path(original_name)
    return f"{path.stem}.{status}.{content_hash[:12]}{path.suffix}"
