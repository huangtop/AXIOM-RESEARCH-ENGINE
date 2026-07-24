from __future__ import annotations

import csv
import json
import os
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from axiom_engine.estimate_data import import_estimate_data, validate_estimate_data
from .adapters import adapt_rows

REQUIRED_METRICS = ("revenue", "net_income", "diluted_eps")
SUPPORTED_KINDS = {"consensus_mean", "consensus_median", "high", "low", "company_guidance"}

class Real100EstimateError(RuntimeError):
    pass


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Real100EstimateError(f"cannot read JSON: {path}") from exc


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _registry(registry_dir: str | Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    root = Path(registry_dir)
    companies = _read_json(root / "companies.json")
    securities = _read_json(root / "securities.json")
    if not isinstance(companies, list) or not isinstance(securities, list):
        raise Real100EstimateError("registry files must contain JSON arrays")
    aliases: dict[str, str] = {}
    for company in companies:
        cid = str(company["company_id"])
        aliases[cid.upper()] = cid
    for security in securities:
        cid = str(security["company_id"])
        ticker = str(security.get("ticker", "")).strip().upper()
        exchange = str(security.get("exchange", "")).strip().upper()
        if ticker:
            aliases.setdefault(ticker, cid)
            if exchange:
                aliases.setdefault(f"{exchange}:{ticker}", cid)
    return companies, aliases


def _records(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return {}, list(csv.DictReader(handle))
    payload = _read_json(path)
    if isinstance(payload, list):
        return {}, payload
    if not isinstance(payload, dict) or not isinstance(payload.get("estimates"), list):
        raise Real100EstimateError("source must be CSV, a JSON array, or an object containing estimates[]")
    return payload, payload["estimates"]


def build_real_100_estimate_template(*, registry_dir: str | Path = "data/company_registry", output: str | Path = "data/onboarding/generated/real_100_estimate_template.csv", fiscal_year: int | None = None, period_end: str | None = None) -> dict[str, Any]:
    companies, _ = _registry(registry_dir)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["company_id", "ticker", "metric", "value", "unit", "currency", "period_end", "fiscal_year", "fiscal_period", "estimate_kind", "analyst_count", "source_record_id", "template_status"]
    fiscal_year = fiscal_year or (date.today().year + 1)
    period_end = period_end or f"{fiscal_year}-12-31"
    securities = _read_json(Path(registry_dir) / "securities.json")
    primary = {str(x["company_id"]): str(x.get("ticker", "")) for x in securities if x.get("primary_listing")}
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for company in companies:
            cid = str(company["company_id"])
            for metric in REQUIRED_METRICS:
                writer.writerow({"company_id": cid, "ticker": primary.get(cid, ""), "metric": metric, "unit": "currency", "currency": "USD", "period_end": period_end, "fiscal_year": fiscal_year, "fiscal_period": "FY", "estimate_kind": "consensus_mean", "template_status": "pending"})
    return {"companies": len(companies), "rows": len(companies) * len(REQUIRED_METRICS), "output": str(output)}


def _is_blank_template_row(raw: dict[str, Any]) -> bool:
    """Return True when a template row has no estimate payload yet."""
    return str(raw.get("template_status") or "").strip().lower() == "pending" and not str(raw.get("value") or "").strip()


def _normalize(raw: dict[str, Any], aliases: dict[str, str], provider_id: str, provenance_id: str, as_of: str) -> dict[str, Any]:
    locator = str(raw.get("company_id") or raw.get("ticker") or "").strip().upper()
    if not locator or locator not in aliases:
        raise Real100EstimateError(f"unknown company locator: {locator or '<empty>'}")
    metric = str(raw.get("metric", "")).strip().lower()
    if not metric:
        raise Real100EstimateError("metric is required")
    try:
        value = str(Decimal(str(raw.get("value", ""))))
    except (InvalidOperation, ValueError):
        raise Real100EstimateError(f"invalid value for {locator}/{metric}")
    period_end = str(raw.get("period_end", "")).strip()
    fiscal_year = int(raw.get("fiscal_year") or period_end[:4])
    if not period_end:
        period_end = f"{fiscal_year}-12-31"
    kind = str(raw.get("estimate_kind") or "consensus_mean")
    if kind not in SUPPORTED_KINDS:
        raise Real100EstimateError(f"unsupported estimate_kind: {kind}")
    unit = str(raw.get("unit") or "currency")
    if unit == "currency_per_share":
        unit = "currency"
    currency = str(raw.get("currency") or "USD").upper() if unit == "currency" else None
    cid = aliases[locator]
    source_record_id = str(raw.get("source_record_id") or f"{cid}:{metric}:{fiscal_year}:{kind}")
    item = {
        "estimate_id": f"estimate:{provider_id.removeprefix('provider:')}:{cid.removeprefix('company:')}:{metric}:{fiscal_year}:{kind}",
        "company_id": cid,
        "metric": metric,
        "value": value,
        "unit": unit,
        "period_end": period_end,
        "fiscal_year": fiscal_year,
        "fiscal_period": str(raw.get("fiscal_period") or "FY"),
        "estimate_kind": kind,
        "provenance_ids": [provenance_id],
        "metadata": {"source_record_id": source_record_id, "as_of_date": as_of, "per_share": metric.endswith("eps")},
    }
    if currency:
        item["currency"] = currency
    analyst_count = raw.get("analyst_count")
    if analyst_count not in (None, ""):
        item["analyst_count"] = int(analyst_count)
    return item


def build_real_100_estimates(source: str | Path, *, registry_dir: str | Path = "data/company_registry", output_dir: str | Path = "data/estimate_data", diagnostics_file: str | Path = "data/onboarding/generated/v024_estimate_diagnostics.json", write: bool = False, adapter: str = "auto", provider_id: str | None = None, provider_name: str | None = None, as_of_date: str | None = None, compact: bool = False) -> dict[str, Any]:
    companies, aliases = _registry(registry_dir)
    header, rows = _records(source)
    try:
        adapted = adapt_rows(rows, adapter)
    except ValueError as exc:
        raise Real100EstimateError(str(exc)) from exc
    rows = adapted.rows
    provider_id = str(provider_id or header.get("provider_id") or "provider:external-consensus")
    if not provider_id.startswith("provider:"):
        provider_id = "provider:" + provider_id
    provider_name = str(provider_name or header.get("provider_name") or provider_id.removeprefix("provider:"))
    as_of = str(as_of_date or header.get("as_of_date") or date.today().isoformat())
    provenance_id = f"provenance:{provider_id.removeprefix('provider:')}:{as_of}"
    blank_rows = [row for row in rows if _is_blank_template_row(row)]
    populated_rows = [row for row in rows if not _is_blank_template_row(row)]
    normalized = [_normalize(row, aliases, provider_id, provenance_id, as_of) for row in populated_rows]
    keys = [(x["company_id"], x["metric"], x["period_end"], x["estimate_kind"]) for x in normalized]
    duplicates = [list(k) for k, n in Counter(keys).items() if n > 1]
    if duplicates:
        raise Real100EstimateError(f"duplicate estimate keys: {duplicates[:5]}")
    company_ids = [str(x["company_id"]) for x in companies]
    if not normalized:
        coverage_by_metric = {metric: 0 for metric in REQUIRED_METRICS}
        input_status = "empty_template" if rows and len(blank_rows) == len(rows) else "no_estimates"
        report = {"companies_requested": len(company_ids), "companies_with_estimates": 0, "estimates_built": 0, "rows_received": len(rows), "rows_skipped_blank": len(blank_rows), "rows_valid": 0, "rows_invalid": 0, "provider_id": provider_id, "provider_name": provider_name, "provider_adapter": adapted.adapter_id, "as_of_date": as_of, "metric_company_coverage": coverage_by_metric, "summary": {"blank_rows": len(blank_rows), "valid_rows": 0, "invalid_rows": 0}, "reason": "Template contains no populated estimate rows." if input_status == "empty_template" else "Source contains no estimate rows.", "diagnostics": "template_not_filled" if input_status == "empty_template" else "no_estimates", "output_directory": str(output_dir), "dry_run": not write, "input_status": input_status, "acceptance_passed": False}
        if not compact:
            report["missing_metrics_by_company"] = {cid: list(REQUIRED_METRICS) for cid in company_ids}
        if write:
            _atomic_write(Path(diagnostics_file), report)
        return report
    source_payload = {
        "schema_version": "1.0.0",
        "provider_id": provider_id,
        "provider_name": provider_name,
        "as_of_date": as_of,
        "provenance": [{"provenance_id": provenance_id, "provider_id": provider_id, "source_type": "analyst_consensus", "source_name": provider_name, "source_record_id": Path(source).name, "retrieved_at": datetime.now(timezone.utc).isoformat(), "metadata": {"record_count": len(normalized)}}],
        "estimates": normalized,
        "forward_assumptions": [],
    }
    with tempfile.TemporaryDirectory() as temp:
        normalized_path = Path(temp) / "normalized.json"
        _atomic_write(normalized_path, source_payload)
        import_report = import_estimate_data(normalized_path, output_dir=output_dir, company_registry_dir=registry_dir, dry_run=not write)
    coverage_by_metric: dict[str, int] = {}
    present_by_company: dict[str, set[str]] = defaultdict(set)
    for item in normalized:
        present_by_company[item["company_id"]].add(item["metric"])
    for metric in sorted({*REQUIRED_METRICS, *(x["metric"] for x in normalized)}):
        coverage_by_metric[metric] = sum(metric in present_by_company[cid] for cid in company_ids)
    missing = {cid: [m for m in REQUIRED_METRICS if m not in present_by_company[cid]] for cid in company_ids}
    missing = {cid: vals for cid, vals in missing.items() if vals}
    companies_with_estimates = sum(bool(present_by_company[cid]) for cid in company_ids)
    acceptance = companies_with_estimates >= 90 and all(coverage_by_metric.get(m, 0) >= 80 for m in REQUIRED_METRICS)
    report = {
        "companies_requested": len(company_ids),
        "companies_with_estimates": companies_with_estimates,
        "estimates_built": len(normalized),
        "rows_received": len(rows),
        "rows_skipped_blank": len(blank_rows),
        "rows_valid": len(normalized),
        "rows_invalid": 0,
        "summary": {"blank_rows": len(blank_rows), "valid_rows": len(normalized), "invalid_rows": 0},
        "provider_id": provider_id,
        "provider_name": provider_name,
        "provider_adapter": adapted.adapter_id,
        "as_of_date": as_of,
        "metric_company_coverage": coverage_by_metric,
        "output_directory": str(output_dir),
        "dry_run": not write,
        "acceptance_passed": acceptance,
    }
    if not compact:
        report["missing_metrics_by_company"] = missing
    if write:
        _atomic_write(Path(diagnostics_file), report)
    return report


def validate_real_100_estimates(*, estimate_dir: str | Path = "data/estimate_data", registry_dir: str | Path = "data/company_registry") -> dict[str, Any]:
    stats = validate_estimate_data(estimate_dir)
    companies, _ = _registry(registry_dir)
    estimates = _read_json(Path(estimate_dir) / "estimates.json")
    company_ids = [str(x["company_id"]) for x in companies]
    present: dict[str, set[str]] = defaultdict(set)
    for item in estimates:
        present[str(item["company_id"])].add(str(item["metric"]))
    coverage = {metric: sum(metric in present[cid] for cid in company_ids) for metric in REQUIRED_METRICS}
    missing = {cid: [m for m in REQUIRED_METRICS if m not in present[cid]] for cid in company_ids}
    missing = {cid: vals for cid, vals in missing.items() if vals}
    companies_with = sum(bool(present[cid]) for cid in company_ids)
    return {"companies_requested": len(company_ids), "companies_with_estimates": companies_with, "estimates_loaded": stats["estimate_count"], "metric_company_coverage": coverage, "missing_metrics_by_company": missing, "acceptance_passed": companies_with >= 90 and all(coverage[m] >= 80 for m in REQUIRED_METRICS)}
