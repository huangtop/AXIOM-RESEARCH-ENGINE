from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import CompanyUniverseSource, RegistryImportReport

OUTPUT_FILES = (
    "companies.json",
    "securities.json",
    "official_classifications.json",
    "business_descriptions.json",
    "provenance.json",
    "manifest.json",
)

FORBIDDEN_SOURCE_KEYS = frozenset({
    "current_price", "revenue_ttm", "eps", "analyst_target", "growth_estimate",
    "shares_outstanding", "enterprise_value", "logic_type", "default_params",
    "valuation", "valuation_result", "research_report",
})


class CompanyRegistryImportError(RuntimeError):
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


def load_company_universe_source(source: str | Path) -> CompanyUniverseSource:
    path = Path(source)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompanyRegistryImportError(f"cannot read company universe source: {path}") from exc
    forbidden = sorted(FORBIDDEN_SOURCE_KEYS.intersection(_walk_keys(raw)))
    if forbidden:
        raise CompanyRegistryImportError(
            "source contains forbidden legacy market/financial/valuation fields: "
            + ", ".join(forbidden)
        )
    try:
        return CompanyUniverseSource.model_validate(raw)
    except ValidationError as exc:
        raise CompanyRegistryImportError(f"invalid company universe source: {exc}") from exc


def import_company_universe(
    source: str | Path,
    *,
    output_dir: str | Path = "data/company_registry",
    dry_run: bool = True,
) -> RegistryImportReport:
    payload = load_company_universe_source(source)
    target = Path(output_dir)
    companies = [item.model_dump(mode="json", exclude_none=True) for item in payload.companies]
    securities = [item.model_dump(mode="json", exclude_none=True) for item in payload.securities]
    classifications = [
        {
            "company_id": item.company_id,
            "official_sector": item.official_sector,
            "official_industry": item.official_industry,
            "provenance_ids": item.provenance_ids,
        }
        for item in payload.companies
        if item.official_sector or item.official_industry
    ]
    descriptions = [
        {
            "company_id": item.company_id,
            "business_description": item.business_description,
            "provenance_ids": item.provenance_ids,
        }
        for item in payload.companies
        if item.business_description
    ]
    provenance = [item.model_dump(mode="json", exclude_none=True) for item in payload.provenance]
    manifest = {
        "schema_version": payload.schema_version,
        "as_of_date": payload.as_of_date.isoformat(),
        "source_name": payload.source_name,
        "company_count": len(companies),
        "security_count": len(securities),
        "official_classification_count": len(classifications),
        "business_description_count": len(descriptions),
        "provenance_count": len(provenance),
        "data_scope": "company_identity_and_business_metadata_only",
    }
    outputs = {
        "companies.json": companies,
        "securities.json": securities,
        "official_classifications.json": classifications,
        "business_descriptions.json": descriptions,
        "provenance.json": provenance,
        "manifest.json": manifest,
    }
    written: list[str] = []
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
        for filename, value in outputs.items():
            _atomic_write_json(target / filename, value)
            written.append(str(target / filename))
    return RegistryImportReport(
        source_name=payload.source_name,
        as_of_date=payload.as_of_date,
        dry_run=dry_run,
        companies_found=len(companies),
        securities_found=len(securities),
        companies_with_official_sector=sum(bool(item.official_sector) for item in payload.companies),
        companies_with_official_industry=sum(bool(item.official_industry) for item in payload.companies),
        companies_with_business_description=sum(bool(item.business_description) for item in payload.companies),
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
