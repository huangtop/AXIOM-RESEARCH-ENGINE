from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from axiom_engine.research_engine import ResearchEngineError, build_research
from axiom_engine.valuation_card import build_valuation_cards


class BatchPipelineError(RuntimeError):
    pass


def _read(path: Path, default: Any = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise BatchPipelineError(f"required input not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchPipelineError(f"cannot read JSON: {path}") from exc


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


def _safe_company_id(company_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in company_id)


def _fingerprint(paths: list[Path], company_id: str) -> str:
    digest = hashlib.sha256(company_id.encode("utf-8"))
    for path in paths:
        digest.update(str(path).encode("utf-8"))
        if path.exists():
            stat = path.stat()
            digest.update(str(stat.st_size).encode("ascii"))
            digest.update(str(stat.st_mtime_ns).encode("ascii"))
    return digest.hexdigest()


def _company_ids(registry_dir: Path) -> tuple[list[str], dict[str, str]]:
    companies = _read(registry_dir / "companies.json")
    securities = _read(registry_dir / "securities.json", default=[])
    if not isinstance(companies, list) or not isinstance(securities, list):
        raise BatchPipelineError("registry companies and securities must be JSON arrays")
    ids = sorted(str(row["company_id"]) for row in companies if row.get("company_id"))
    tickers = {
        str(row.get("company_id")): str(row.get("ticker", "")).upper()
        for row in securities
        if row.get("company_id") and row.get("primary_listing", True)
    }
    return ids, tickers


def _merge_company_outputs(company_results: list[dict[str, Any]], output_dir: Path) -> None:
    bundles: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    for result in company_results:
        if result.get("status") not in {"completed", "resumed"}:
            continue
        research_dir = Path(result["research_dir"])
        bundles.extend(_read(research_dir / "company_research.json", default=[]))
        diagnostics.extend(_read(research_dir / "diagnostics.json", default=[]))
        provenance.extend(_read(research_dir / "provenance.json", default=[]))
    research_out = output_dir / "research_data"
    _write(research_out / "company_research.json", bundles)
    _write(research_out / "diagnostics.json", diagnostics)
    _write(research_out / "provenance.json", provenance)
    _write(research_out / "manifest.json", {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bundle_count": len(bundles),
        "diagnostic_count": len(diagnostics),
        "provenance_count": len(provenance),
        "source": "batch_canonical_pipeline",
    })
    if bundles:
        build_valuation_cards(research_dir=research_out, output_dir=output_dir / "valuation_card", write=True)


def run_batch_pipeline(
    *,
    registry_dir: str | Path = "data/company_registry",
    financial_dir: str | Path = "data/financial_data",
    estimate_dir: str | Path = "data/estimate_data",
    market_dir: str | Path = "data/market_data",
    valuation_dir: str | Path = "data/valuation_data",
    output_dir: str | Path = "data/production_pipeline",
    company: str | None = None,
    resume: bool = False,
    retry_failed: bool = False,
    batch_size: int = 100,
    write: bool = False,
) -> dict[str, Any]:
    if batch_size < 1:
        raise BatchPipelineError("batch_size must be at least 1")
    roots = {
        "registry": Path(registry_dir),
        "financial": Path(financial_dir),
        "estimate": Path(estimate_dir),
        "market": Path(market_dir),
        "valuation": Path(valuation_dir),
    }
    out = Path(output_dir)
    company_ids, tickers = _company_ids(roots["registry"])
    if company:
        token = company.strip()
        company_ids = [cid for cid in company_ids if cid == token or tickers.get(cid) == token.upper()]
        if not company_ids:
            raise BatchPipelineError(f"company not found in registry: {company}")
    state_path = out / "pipeline_state.json"
    previous = _read(state_path, default={}) if resume or retry_failed else {}
    previous_companies = previous.get("companies", {}) if isinstance(previous, dict) else {}
    now = datetime.now(timezone.utc).isoformat()
    results: list[dict[str, Any]] = []
    input_paths = [
        roots["registry"] / "companies.json",
        roots["registry"] / "securities.json",
        roots["financial"] / "financial_facts.json",
        roots["estimate"] / "estimates.json",
        roots["market"] / "observations.json",
        roots["valuation"] / "valuations.json",
    ]
    for offset in range(0, len(company_ids), batch_size):
        for company_id in company_ids[offset: offset + batch_size]:
            safe_id = _safe_company_id(company_id)
            company_out = out / "companies" / safe_id / "research_data"
            fingerprint = _fingerprint(input_paths, company_id)
            old = previous_companies.get(company_id, {}) if isinstance(previous_companies, dict) else {}
            if resume and old.get("status") == "completed" and old.get("fingerprint") == fingerprint and company_out.exists():
                results.append({
                    "company_id": company_id,
                    "ticker": tickers.get(company_id),
                    "status": "resumed",
                    "fingerprint": fingerprint,
                    "research_dir": str(company_out),
                    "error": None,
                })
                continue
            if retry_failed and old and old.get("status") != "failed":
                continue
            try:
                report = build_research(
                    registry_dir=roots["registry"],
                    financial_dir=roots["financial"],
                    estimate_dir=roots["estimate"],
                    market_dir=roots["market"],
                    valuation_dir=roots["valuation"],
                    output_dir=company_out,
                    company=company_id,
                    write=write,
                )
                status = "completed" if report.get("acceptance_passed") else "failed"
                error = None if status == "completed" else "research acceptance failed"
            except (ResearchEngineError, OSError, ValueError, TypeError) as exc:
                status = "failed"
                error = str(exc)
            results.append({
                "company_id": company_id,
                "ticker": tickers.get(company_id),
                "status": status,
                "fingerprint": fingerprint,
                "research_dir": str(company_out),
                "error": error,
            })
    if retry_failed:
        untouched = [
            {"company_id": cid, **row}
            for cid, row in previous_companies.items()
            if cid not in {item["company_id"] for item in results}
        ] if isinstance(previous_companies, dict) else []
        results.extend(untouched)
    completed = sum(1 for row in results if row.get("status") in {"completed", "resumed"})
    failed = sum(1 for row in results if row.get("status") == "failed")
    state = {
        "schema_version": "1.0.0",
        "generated_at": now,
        "pipeline_version": "V027.1",
        "company_count": len(results),
        "completed": completed,
        "failed": failed,
        "resume_enabled": resume,
        "retry_failed": retry_failed,
        "batch_size": batch_size,
        "companies": {row["company_id"]: {k: v for k, v in row.items() if k != "company_id"} for row in results},
    }
    diagnostics = [
        {
            "severity": "error",
            "code": "company_pipeline_failed",
            "company_id": row["company_id"],
            "ticker": row.get("ticker"),
            "message": row.get("error") or "company pipeline failed",
        }
        for row in results if row.get("status") == "failed"
    ]
    if write:
        _merge_company_outputs(results, out)
        _write(state_path, state)
        _write(out / "pipeline_diagnostics.json", diagnostics)
        _write(out / "pipeline_manifest.json", {
            "schema_version": "1.0.0",
            "generated_at": now,
            "pipeline_version": "V027.1",
            "company_count": len(results),
            "completed": completed,
            "failed": failed,
            "files": [
                "pipeline_state.json",
                "pipeline_diagnostics.json",
                "pipeline_manifest.json",
                "research_data/company_research.json",
                "valuation_card/valuation_cards.json",
            ],
        })
    return {
        "valid": completed > 0,
        "company_count": len(results),
        "completed": completed,
        "failed": failed,
        "output_dir": str(out),
        "dry_run": not write,
    }


def validate_batch_pipeline(*, output_dir: str | Path = "data/production_pipeline") -> dict[str, Any]:
    out = Path(output_dir)
    errors: list[str] = []
    state = _read(out / "pipeline_state.json", default={})
    diagnostics = _read(out / "pipeline_diagnostics.json", default=[])
    manifest = _read(out / "pipeline_manifest.json", default={})
    bundles = _read(out / "research_data" / "company_research.json", default=[])
    cards = _read(out / "valuation_card" / "valuation_cards.json", default=[])
    if not isinstance(state, dict) or state.get("pipeline_version") != "V027.1":
        errors.append("invalid or missing V027.1 pipeline state")
    if not isinstance(diagnostics, list):
        errors.append("pipeline_diagnostics.json must be a JSON array")
    if not isinstance(manifest, dict):
        errors.append("pipeline_manifest.json must be a JSON object")
    if not isinstance(bundles, list):
        errors.append("company_research.json must be a JSON array")
        bundles = []
    if not isinstance(cards, list):
        errors.append("valuation_cards.json must be a JSON array")
        cards = []
    completed = int(state.get("completed", 0)) if isinstance(state, dict) else 0
    if completed != len(bundles):
        errors.append(f"completed count {completed} does not match research bundles {len(bundles)}")
    if bundles and len(cards) != len(bundles):
        errors.append("valuation card count does not match research bundle count")
    return {
        "valid": not errors and completed > 0,
        "errors": errors,
        "output_dir": str(out),
        "company_count": int(state.get("company_count", 0)) if isinstance(state, dict) else 0,
        "completed": completed,
        "failed": int(state.get("failed", 0)) if isinstance(state, dict) else 0,
        "research_bundles": len(bundles),
        "valuation_cards": len(cards),
    }
