from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import MarketDataSource, MarketImportReport

FORBIDDEN_SOURCE_KEYS = frozenset({
    "fair_value", "intrinsic_value", "analyst_target", "price_target", "upside",
    "downside", "margin_of_safety", "valuation", "valuation_result", "research_report",
    "theme", "theme_ids", "classification_ids", "exposure", "forward_pe_assumption",
})


class MarketDataImportError(RuntimeError):
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


def load_market_data_source(source: str | Path) -> MarketDataSource:
    path = Path(source)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketDataImportError(f"cannot read market data source: {path}") from exc
    forbidden = sorted(FORBIDDEN_SOURCE_KEYS.intersection(_walk_keys(raw)))
    if forbidden:
        raise MarketDataImportError("source contains forbidden fields: " + ", ".join(forbidden))
    try:
        return MarketDataSource.model_validate(raw)
    except ValidationError as exc:
        raise MarketDataImportError(f"invalid market data source: {exc}") from exc


def _load_registry(registry_dir: str | Path | None) -> tuple[set[str], set[str]] | None:
    if registry_dir is None:
        return None
    root = Path(registry_dir)
    try:
        companies = json.loads((root / "companies.json").read_text(encoding="utf-8"))
        securities = json.loads((root / "securities.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketDataImportError(f"cannot read company registry: {root}") from exc
    return ({str(x["company_id"]) for x in companies}, {str(x["security_id"]) for x in securities})


def import_market_data(
    source: str | Path,
    *,
    output_dir: str | Path = "data/market_data",
    company_registry_dir: str | Path | None = "data/company_registry",
    dry_run: bool = True,
) -> MarketImportReport:
    payload = load_market_data_source(source)
    registry = _load_registry(company_registry_dir)
    if registry is not None:
        company_ids, security_ids = registry
        referenced_companies = {x.company_id for x in [*payload.observations, *payload.trading_statuses]}
        referenced_securities = {x.security_id for x in [*payload.observations, *payload.trading_statuses]}
        missing_companies = sorted(referenced_companies - company_ids)
        missing_securities = sorted(referenced_securities - security_ids)
        if missing_companies:
            raise MarketDataImportError("market data references companies missing from registry: " + ", ".join(missing_companies))
        if missing_securities:
            raise MarketDataImportError("market data references securities missing from registry: " + ", ".join(missing_securities))

    observations = [x.model_dump(mode="json", exclude_none=True) for x in payload.observations]
    observations.sort(key=lambda x: (x["company_id"], x["security_id"], x["metric"], x["observed_at"], x["market_observation_id"]))
    statuses = [x.model_dump(mode="json", exclude_none=True) for x in payload.trading_statuses]
    statuses.sort(key=lambda x: (x["company_id"], x["security_id"], x["observed_at"], x["trading_status_id"]))
    provenance = [x.model_dump(mode="json", exclude_none=True) for x in payload.provenance]
    provenance.sort(key=lambda x: x["provenance_id"])
    manifest = {
        "schema_version": payload.schema_version,
        "provider_id": payload.provider_id,
        "provider_name": payload.provider_name,
        "as_of_date": payload.as_of_date.isoformat(),
        "observation_count": len(observations),
        "trading_status_count": len(statuses),
        "company_count": len({x["company_id"] for x in [*observations, *statuses]}),
        "security_count": len({x["security_id"] for x in [*observations, *statuses]}),
        "metric_count": len({x["metric"] for x in observations}),
        "provenance_count": len(provenance),
        "data_scope": "point_in_time_market_data_only",
        "valuation_outputs_included": False,
        "analyst_estimates_included": False,
    }
    outputs = {
        "market_observations.json": observations,
        "trading_statuses.json": statuses,
        "provenance.json": provenance,
        "manifest.json": manifest,
    }
    target = Path(output_dir)
    written: list[str] = []
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
        for filename, value in outputs.items():
            _atomic_write_json(target / filename, value)
            written.append(str(target / filename))
    return MarketImportReport(
        provider_id=payload.provider_id,
        as_of_date=payload.as_of_date,
        dry_run=dry_run,
        observations_found=len(observations),
        trading_statuses_found=len(statuses),
        companies_found=manifest["company_count"],
        securities_found=manifest["security_count"],
        metrics_found=manifest["metric_count"],
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
