from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


class ProductionEstimateError(RuntimeError):
    """Raised when canonical production estimate import cannot complete."""


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ProductionEstimateError(f"missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProductionEstimateError(f"invalid JSON: {path}: {exc}") from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _diag(severity: str, code: str, message: str, **context: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, "context": context}


def _decimal(value: Any, field: str, diagnostics: list[dict[str, Any]], index: int) -> str | None:
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        diagnostics.append(_diag("error", "invalid_decimal", f"{field} must be decimal-compatible", index=index, field=field, value=value))
        return None
    if not number.is_finite():
        diagnostics.append(_diag("error", "non_finite_decimal", f"{field} must be finite", index=index, field=field, value=value))
        return None
    normalized = format(number.normalize(), "f")
    return "0" if normalized in {"-0", ""} else normalized


def _timestamp(value: Any, diagnostics: list[dict[str, Any]], index: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        diagnostics.append(_diag("error", "missing_as_of", "as_of is required", index=index))
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        diagnostics.append(_diag("error", "invalid_as_of", "as_of must be ISO-8601", index=index, value=value))
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        diagnostics.append(_diag("error", "naive_as_of", "as_of must include timezone", index=index, value=value))
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _registry(registry_dir: Path) -> tuple[set[str], dict[str, str]]:
    companies = _load(registry_dir / "companies.json")
    securities_path = registry_dir / "securities.json"
    securities = _load(securities_path) if securities_path.exists() else []
    if not isinstance(companies, list) or not isinstance(securities, list):
        raise ProductionEstimateError("registry companies.json and securities.json must be arrays")
    company_ids = {str(row.get("company_id")) for row in companies if isinstance(row, dict) and row.get("company_id")}
    security_company = {str(row.get("security_id")): str(row.get("company_id")) for row in securities if isinstance(row, dict) and row.get("security_id") and row.get("company_id")}
    return company_ids, security_company


def _estimate_id(row: dict[str, Any]) -> str:
    key = "|".join(str(row.get(k) or "") for k in ("company_id", "security_id", "provider", "metric", "fiscal_year", "fiscal_period", "as_of"))
    return "estimate:" + sha256(key.encode("utf-8")).hexdigest()[:24]


def build_production_estimates(
    *, source_dir: str | Path, output_dir: str | Path = "data/estimates",
    registry_dir: str | Path = "data/company_registry", strict: bool = False,
    write: bool = False,
) -> dict[str, Any]:
    source = Path(source_dir)
    raw_estimates = _load(source / "consensus_estimates.json")
    provenance = _load(source / "provenance.json")
    if not isinstance(raw_estimates, list) or not isinstance(provenance, list):
        raise ProductionEstimateError("consensus_estimates.json and provenance.json must be arrays")
    company_ids, security_company = _registry(Path(registry_dir))
    provenance_ids = {str(row.get("provenance_id")) for row in provenance if isinstance(row, dict) and row.get("provenance_id")}
    diagnostics: list[dict[str, Any]] = []
    estimates: list[dict[str, Any]] = []
    natural_keys: Counter[tuple[str, str, str, int, str, str]] = Counter()
    seen_ids: set[str] = set()
    allowed_periods = {"FY", "Q1", "Q2", "Q3", "Q4", "TTM"}
    allowed_metrics = {"revenue", "eps", "ebitda", "ebit", "net_income", "free_cash_flow", "operating_cash_flow", "gross_profit", "target_price"}
    for index, raw in enumerate(raw_estimates):
        if not isinstance(raw, dict):
            diagnostics.append(_diag("error", "invalid_estimate_shape", "estimate must be an object", index=index)); continue
        company_id = str(raw.get("company_id") or "").strip()
        security_id = str(raw.get("security_id") or "").strip() or None
        provider = str(raw.get("provider") or "").strip().lower()
        metric = str(raw.get("metric") or "").strip().lower()
        fiscal_period = str(raw.get("fiscal_period") or "").strip().upper()
        as_of = _timestamp(raw.get("as_of"), diagnostics, index)
        try: fiscal_year = int(raw.get("fiscal_year"))
        except (TypeError, ValueError):
            fiscal_year = 0; diagnostics.append(_diag("error", "invalid_fiscal_year", "fiscal_year must be integer", index=index, value=raw.get("fiscal_year")))
        if not company_id: diagnostics.append(_diag("error", "missing_company_id", "company_id is required", index=index))
        elif company_id not in company_ids: diagnostics.append(_diag("error", "unknown_company_id", "company_id not found in registry", index=index, company_id=company_id))
        if security_id:
            if security_id not in security_company: diagnostics.append(_diag("error", "unknown_security_id", "security_id not found in registry", index=index, security_id=security_id))
            elif security_company[security_id] != company_id: diagnostics.append(_diag("error", "security_company_mismatch", "security_id belongs to a different company", index=index, security_id=security_id, company_id=company_id))
        if not provider: diagnostics.append(_diag("error", "missing_provider", "provider is required", index=index))
        if metric not in allowed_metrics: diagnostics.append(_diag("error", "invalid_metric", "metric is not canonical", index=index, metric=metric))
        if fiscal_period not in allowed_periods: diagnostics.append(_diag("error", "invalid_fiscal_period", "fiscal_period is invalid", index=index, fiscal_period=fiscal_period))
        currency = str(raw.get("currency") or "").strip().upper() or None
        if currency is not None and (len(currency) != 3 or not currency.isalpha()): diagnostics.append(_diag("error", "invalid_currency", "currency must be a three-letter code", index=index, currency=currency))
        unit = str(raw.get("unit") or "").strip().lower() or None
        if metric in {"revenue", "ebitda", "ebit", "net_income", "free_cash_flow", "operating_cash_flow", "gross_profit", "target_price"} and currency is None:
            diagnostics.append(_diag("warning", "missing_currency", "monetary estimate has no currency", index=index, metric=metric))
        values = {field: _decimal(raw.get(field), field, diagnostics, index) for field in ("mean", "median", "high", "low")}
        if values["mean"] is None: diagnostics.append(_diag("error", "missing_mean", "mean consensus is required", index=index))
        if values["low"] is not None and values["high"] is not None and Decimal(values["low"]) > Decimal(values["high"]): diagnostics.append(_diag("error", "invalid_consensus_range", "low exceeds high", index=index))
        if values["mean"] is not None and values["low"] is not None and Decimal(values["mean"]) < Decimal(values["low"]): diagnostics.append(_diag("error", "mean_below_low", "mean is below low", index=index))
        if values["mean"] is not None and values["high"] is not None and Decimal(values["mean"]) > Decimal(values["high"]): diagnostics.append(_diag("error", "mean_above_high", "mean is above high", index=index))
        try: analyst_count = int(raw.get("analyst_count")) if raw.get("analyst_count") not in (None, "") else None
        except (TypeError, ValueError): analyst_count = None; diagnostics.append(_diag("error", "invalid_analyst_count", "analyst_count must be integer", index=index))
        if analyst_count is not None and analyst_count < 0: diagnostics.append(_diag("error", "negative_analyst_count", "analyst_count cannot be negative", index=index))
        pids = sorted({str(x) for x in (raw.get("provenance_ids") or []) if str(x).strip()})
        if not pids: diagnostics.append(_diag("warning", "missing_provenance", "estimate has no provenance_ids", index=index))
        missing = [pid for pid in pids if pid not in provenance_ids]
        if missing: diagnostics.append(_diag("error", "unknown_provenance", "estimate references unknown provenance", index=index, provenance_ids=missing))
        normalized = {"estimate_id":"", "company_id":company_id, "security_id":security_id, "provider":provider, "metric":metric, "source_metric":str(raw.get("source_metric") or "").strip() or None, "fiscal_year":fiscal_year, "fiscal_period":fiscal_period, "as_of":as_of, "currency":currency, "unit":unit, **values, "analyst_count":analyst_count, "provenance_ids":pids, "metadata":raw.get("metadata") or {}}
        normalized["estimate_id"] = str(raw.get("estimate_id") or "").strip() or _estimate_id(normalized)
        if normalized["estimate_id"] in seen_ids: diagnostics.append(_diag("error", "duplicate_estimate_id", "duplicate estimate_id", index=index, estimate_id=normalized["estimate_id"]))
        seen_ids.add(normalized["estimate_id"])
        natural_keys[(company_id, provider, metric, fiscal_year, fiscal_period, as_of or "")] += 1
        estimates.append(normalized)
    for key,count in natural_keys.items():
        if count > 1: diagnostics.append(_diag("error", "duplicate_consensus_estimate", "multiple estimates share company/provider/metric/period/as_of", key=list(key), count=count))
    estimates.sort(key=lambda row:(str(row["company_id"]), int(row["fiscal_year"]), str(row["fiscal_period"]), str(row["metric"]), str(row["provider"])))
    errors=sum(d["severity"]=="error" for d in diagnostics); warnings=sum(d["severity"]=="warning" for d in diagnostics); valid=errors==0
    if strict and not valid: raise ProductionEstimateError(f"production estimate import failed with {errors} error(s)")
    manifest={"schema_version":"1.0.0","estimate_version":"V028.3","generated_at":_now(),"source_dir":str(source),"registry_dir":str(registry_dir),"estimate_count":len(estimates),"company_count":len({r["company_id"] for r in estimates if r["company_id"]}),"security_count":len({r["security_id"] for r in estimates if r["security_id"]}),"provider_count":len({r["provider"] for r in estimates if r["provider"]}),"metric_count":len({r["metric"] for r in estimates if r["metric"]}),"errors":errors,"warnings":warnings,"valid":valid,"files":["consensus_estimates.json","provenance.json","estimate_diagnostics.json","estimate_manifest.json"]}
    out=Path(output_dir)
    if write:
        out.mkdir(parents=True,exist_ok=True)
        for name,payload in (("consensus_estimates.json",estimates),("provenance.json",provenance),("estimate_diagnostics.json",diagnostics),("estimate_manifest.json",manifest)):
            (out/name).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return {**manifest,"output_dir":str(out),"dry_run":not write}


def validate_production_estimates(*, output_dir: str | Path = "data/estimates", registry_dir: str | Path = "data/company_registry") -> dict[str, Any]:
    root=Path(output_dir); required=["consensus_estimates.json","provenance.json","estimate_diagnostics.json","estimate_manifest.json"]
    missing=[n for n in required if not (root/n).exists()]
    if missing: return {"valid":False,"errors":[f"missing file: {n}" for n in missing],"output_dir":str(root)}
    estimates=_load(root/"consensus_estimates.json"); diagnostics=_load(root/"estimate_diagnostics.json"); manifest=_load(root/"estimate_manifest.json")
    if not isinstance(estimates,list) or not isinstance(diagnostics,list) or not isinstance(manifest,dict): return {"valid":False,"errors":["invalid_output_shape"],"output_dir":str(root)}
    company_ids,security_company=_registry(Path(registry_dir))
    invalid_companies=[r.get("estimate_id") for r in estimates if r.get("company_id") not in company_ids]
    invalid_securities=[r.get("estimate_id") for r in estimates if r.get("security_id") and r.get("security_id") not in security_company]
    mismatches=[r.get("estimate_id") for r in estimates if r.get("security_id") and security_company.get(r.get("security_id")) not in (None,r.get("company_id"))]
    ids=[r.get("estimate_id") for r in estimates]; duplicate_ids=sorted(k for k,c in Counter(ids).items() if k and c>1)
    errors=[d.get("code") for d in diagnostics if d.get("severity")=="error"]
    if invalid_companies: errors.append("invalid_company_links")
    if invalid_securities: errors.append("invalid_security_links")
    if mismatches: errors.append("security_company_mismatches")
    if duplicate_ids: errors.append("duplicate_estimate_ids")
    if manifest.get("estimate_count") != len(estimates): errors.append("manifest_mismatch")
    return {"valid":not errors,"errors":errors,"estimate_count":len(estimates),"company_count":len({r.get("company_id") for r in estimates if r.get("company_id")}),"security_count":len({r.get("security_id") for r in estimates if r.get("security_id")}),"invalid_company_links":invalid_companies,"invalid_security_links":invalid_securities,"security_company_mismatches":mismatches,"duplicate_estimate_ids":duplicate_ids,"output_dir":str(root)}
