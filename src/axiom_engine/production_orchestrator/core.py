from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from axiom_engine.batch_pipeline import run_batch_pipeline, validate_batch_pipeline
from axiom_engine.coverage_audit import build_coverage_audit, validate_coverage_audit
from axiom_engine.valuation_strategy import build_valuation_strategies, validate_valuation_strategies


class ProductionOrchestratorError(RuntimeError):
    pass


def _read(path: Path, default: Any = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise ProductionOrchestratorError(f"required output not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionOrchestratorError(f"cannot read JSON: {path}") from exc


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _company_id(record: dict[str, Any]) -> str | None:
    direct = record.get("company_id")
    if direct:
        return str(direct)
    company = record.get("company")
    if isinstance(company, dict) and company.get("company_id"):
        return str(company["company_id"])
    identity = record.get("identity")
    if isinstance(identity, dict) and identity.get("company_id"):
        return str(identity["company_id"])
    return None


def _strategy_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategy_id": row.get("strategy_id"),
        "method": row.get("selected_strategy"),
        "coverage_tier": row.get("coverage_tier"),
        "confidence": row.get("confidence"),
        "fair_value_per_share": row.get("fair_value_per_share"),
        "fallback_reason": row.get("fallback_reason"),
        "missing_inputs": row.get("missing_inputs", []),
        "status": row.get("status"),
        "source_record_ids": row.get("source_record_ids", []),
    }


def _enrich_records(path: Path, strategies: dict[str, dict[str, Any]]) -> int:
    records = _read(path, default=[])
    if not isinstance(records, list):
        raise ProductionOrchestratorError(f"expected JSON array: {path}")
    enriched = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        cid = _company_id(record)
        strategy = strategies.get(cid or "")
        if strategy:
            record["valuation_strategy"] = _strategy_payload(strategy)
            enriched += 1
    _write(path, records)
    return enriched


def run_production_orchestrator(
    *,
    registry_dir: str | Path = "data/company_registry",
    financial_dir: str | Path = "data/financial_data",
    estimate_dir: str | Path = "data/estimate_data",
    market_dir: str | Path = "data/market_data",
    valuation_dir: str | Path = "data/valuation_data",
    output_dir: str | Path = "data/production_orchestrator",
    company: str | None = None,
    batch_size: int = 100,
    resume: bool = False,
    retry_failed: bool = False,
    write: bool = False,
) -> dict[str, Any]:
    if batch_size < 1:
        raise ProductionOrchestratorError("batch_size must be at least 1")

    out = Path(output_dir)
    strategy_dir = out / "valuation_strategy"
    pipeline_dir = out / "canonical_pipeline"
    audit_dir = out / "coverage_audit"
    generated_at = datetime.now(timezone.utc).isoformat()
    stages: list[dict[str, Any]] = []

    strategy_result = build_valuation_strategies(
        registry_dir=registry_dir,
        financial_dir=financial_dir,
        estimate_dir=estimate_dir,
        market_dir=market_dir,
        output_dir=strategy_dir,
        company=company,
        write=write,
    )
    stages.append({"stage": "valuation_strategy", "status": "completed" if strategy_result.get("valid") else "failed", "result": strategy_result})

    pipeline_result = run_batch_pipeline(
        registry_dir=registry_dir,
        financial_dir=financial_dir,
        estimate_dir=estimate_dir,
        market_dir=market_dir,
        valuation_dir=valuation_dir,
        output_dir=pipeline_dir,
        company=company,
        resume=resume,
        retry_failed=retry_failed,
        batch_size=batch_size,
        write=write,
    )
    stages.append({"stage": "canonical_pipeline", "status": "completed" if pipeline_result.get("valid") else "failed", "result": pipeline_result})

    research_enriched = 0
    cards_enriched = 0
    if write:
        strategy_document = _read(strategy_dir / "valuation_strategies.json", default={})
        rows = strategy_document.get("strategies", []) if isinstance(strategy_document, dict) else []
        strategies = {str(row.get("company_id")): row for row in rows if isinstance(row, dict) and row.get("company_id")}
        research_enriched = _enrich_records(pipeline_dir / "research_data" / "company_research.json", strategies)
        cards_enriched = _enrich_records(pipeline_dir / "valuation_card" / "valuation_cards.json", strategies)
    stages.append({
        "stage": "strategy_enrichment",
        "status": "completed" if (not write or research_enriched == cards_enriched) else "failed",
        "result": {"research_bundles_enriched": research_enriched, "valuation_cards_enriched": cards_enriched},
    })

    audit_result = build_coverage_audit(
        registry_path=registry_dir,
        financial_path=financial_dir,
        estimate_path=estimate_dir,
        market_path=market_dir,
        valuation_path=valuation_dir,
        research_path=pipeline_dir / "research_data" if write else None,
        output_dir=audit_dir,
        write=write,
    )
    stages.append({"stage": "coverage_audit", "status": "completed" if audit_result.get("valid") else "failed", "result": audit_result})

    valid = bool(strategy_result.get("valid") and pipeline_result.get("valid") and audit_result.get("valid"))
    state = {
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "orchestrator_version": "V027.3",
        "valid": valid,
        "resume_enabled": resume,
        "retry_failed": retry_failed,
        "batch_size": batch_size,
        "company_filter": company,
        "company_count": pipeline_result.get("company_count", 0),
        "completed": pipeline_result.get("completed", 0),
        "failed": pipeline_result.get("failed", 0),
        "stages": stages,
    }
    if write:
        _write(out / "orchestrator_state.json", state)
        _write(out / "orchestrator_diagnostics.json", [
            {"severity": "error", "code": "orchestrator_stage_failed", "stage": stage["stage"], "message": "stage did not complete successfully"}
            for stage in stages if stage["status"] == "failed"
        ])
        _write(out / "orchestrator_manifest.json", {
            "schema_version": "1.0.0",
            "generated_at": generated_at,
            "orchestrator_version": "V027.3",
            "company_count": state["company_count"],
            "completed": state["completed"],
            "failed": state["failed"],
            "outputs": [
                "orchestrator_state.json",
                "orchestrator_diagnostics.json",
                "orchestrator_manifest.json",
                "valuation_strategy/valuation_strategies.json",
                "canonical_pipeline/research_data/company_research.json",
                "canonical_pipeline/valuation_card/valuation_cards.json",
                "coverage_audit/coverage_report.json",
            ],
        })
    return {
        "valid": valid,
        "company_count": state["company_count"],
        "completed": state["completed"],
        "failed": state["failed"],
        "research_bundles_enriched": research_enriched,
        "valuation_cards_enriched": cards_enriched,
        "output_dir": str(out),
        "dry_run": not write,
    }


def validate_production_orchestrator(*, output_dir: str | Path = "data/production_orchestrator") -> dict[str, Any]:
    out = Path(output_dir)
    errors: list[str] = []
    state = _read(out / "orchestrator_state.json", default={})
    manifest = _read(out / "orchestrator_manifest.json", default={})
    diagnostics = _read(out / "orchestrator_diagnostics.json", default=[])
    if not isinstance(state, dict) or state.get("orchestrator_version") != "V027.3":
        errors.append("invalid or missing V027.3 orchestrator state")
    if not isinstance(manifest, dict):
        errors.append("orchestrator_manifest.json must be a JSON object")
    if not isinstance(diagnostics, list):
        errors.append("orchestrator_diagnostics.json must be a JSON array")

    validators = [
        ("valuation_strategy", validate_valuation_strategies(output_dir=out / "valuation_strategy")),
        ("canonical_pipeline", validate_batch_pipeline(output_dir=out / "canonical_pipeline")),
        ("coverage_audit", validate_coverage_audit(output_dir=out / "coverage_audit")),
    ]
    for name, result in validators:
        if not result.get("valid"):
            errors.extend(f"{name}: {item}" for item in result.get("errors", ["validation failed"]))

    strategies_document = _read(out / "valuation_strategy" / "valuation_strategies.json", default={})
    strategy_rows = strategies_document.get("strategies", []) if isinstance(strategies_document, dict) else []
    selected_ids = {str(row.get("company_id")) for row in strategy_rows if isinstance(row, dict) and row.get("status") == "selected"}
    bundles = _read(out / "canonical_pipeline" / "research_data" / "company_research.json", default=[])
    cards = _read(out / "canonical_pipeline" / "valuation_card" / "valuation_cards.json", default=[])
    for label, records in (("research bundle", bundles), ("valuation card", cards)):
        if not isinstance(records, list):
            errors.append(f"{label} output must be a JSON array")
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            cid = _company_id(record)
            if cid in selected_ids and not isinstance(record.get("valuation_strategy"), dict):
                errors.append(f"{label} missing valuation_strategy: {cid}")

    completed = int(state.get("completed", 0)) if isinstance(state, dict) else 0
    return {
        "valid": not errors and completed > 0,
        "errors": errors,
        "output_dir": str(out),
        "company_count": int(state.get("company_count", 0)) if isinstance(state, dict) else 0,
        "completed": completed,
        "failed": int(state.get("failed", 0)) if isinstance(state, dict) else 0,
        "research_bundles": len(bundles) if isinstance(bundles, list) else 0,
        "valuation_cards": len(cards) if isinstance(cards, list) else 0,
    }
