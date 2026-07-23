from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import FinancialDataSource, FinancialImportReport

OUTPUT_FILES = ("financial_facts.json", "provenance.json", "manifest.json")
FORBIDDEN_SOURCE_KEYS = frozenset({
    "current_price", "analyst_target", "growth_estimate", "logic_type",
    "default_params", "valuation", "valuation_result", "research_report",
    "theme", "theme_ids", "classification_ids", "exposure",
})


class FinancialDataImportError(RuntimeError):
    pass


def _walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key).lower())
            keys.update(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_walk_keys(child))
    return keys


def load_financial_data_source(source: str | Path) -> FinancialDataSource:
    path = Path(source)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FinancialDataImportError(f"cannot read financial data source: {path}") from exc
    forbidden = sorted(FORBIDDEN_SOURCE_KEYS.intersection(_walk_keys(raw)))
    if forbidden:
        raise FinancialDataImportError("source contains forbidden fields: " + ", ".join(forbidden))
    try:
        return FinancialDataSource.model_validate(raw)
    except ValidationError as exc:
        raise FinancialDataImportError(f"invalid financial data source: {exc}") from exc


def _load_company_ids(registry_dir: str | Path | None) -> set[str] | None:
    if registry_dir is None:
        return None
    path = Path(registry_dir) / "companies.json"
    if not path.exists():
        raise FinancialDataImportError(f"company registry not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FinancialDataImportError(f"cannot read company registry: {path}") from exc
    return {str(item["company_id"]) for item in payload}


def import_financial_data(
    source: str | Path,
    *,
    output_dir: str | Path = "data/financial_data",
    company_registry_dir: str | Path | None = "data/company_registry",
    dry_run: bool = True,
) -> FinancialImportReport:
    payload = load_financial_data_source(source)
    known_companies = _load_company_ids(company_registry_dir) if company_registry_dir else None
    if known_companies is not None:
        missing = sorted({fact.company_id for fact in payload.facts} - known_companies)
        if missing:
            raise FinancialDataImportError("facts reference companies missing from registry: " + ", ".join(missing))

    facts = [x.model_dump(mode="json", exclude_none=True) for x in payload.facts]
    facts.sort(key=lambda x: (x["company_id"], x["metric"], x["period_end"], x["financial_fact_id"]))
    provenance = [x.model_dump(mode="json", exclude_none=True) for x in payload.provenance]
    provenance.sort(key=lambda x: x["provenance_id"])
    manifest = {
        "schema_version": payload.schema_version,
        "provider_id": payload.provider_id,
        "provider_name": payload.provider_name,
        "as_of_date": payload.as_of_date.isoformat(),
        "fact_count": len(facts),
        "company_count": len({x["company_id"] for x in facts}),
        "metric_count": len({x["metric"] for x in facts}),
        "provenance_count": len(provenance),
        "data_scope": "reported_financial_facts_only",
        "derived_metrics_included": False,
        "estimates_included": False,
        "valuation_outputs_included": False,
    }
    outputs = {"financial_facts.json": facts, "provenance.json": provenance, "manifest.json": manifest}
    target = Path(output_dir)
    written: list[str] = []
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
        for filename, value in outputs.items():
            _atomic_write_json(target / filename, value)
            written.append(str(target / filename))
    return FinancialImportReport(
        provider_id=payload.provider_id,
        as_of_date=payload.as_of_date,
        dry_run=dry_run,
        facts_found=len(facts),
        companies_found=len({x["company_id"] for x in facts}),
        metrics_found=len({x["metric"] for x in facts}),
        provenance_records=len(provenance),
        output_directory=str(target),
        written_files=written,
    )


def _atomic_write_json(path: Path, payload: Any) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
