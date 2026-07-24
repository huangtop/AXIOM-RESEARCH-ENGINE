from __future__ import annotations

import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable


class ResearchEngineError(RuntimeError):
    pass


def _read_json(path: Path, *, default: Any = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise ResearchEngineError(f"required canonical input not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchEngineError(f"cannot read JSON: {path}") from exc


def _write_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _latest(rows: Iterable[dict[str, Any]], date_keys: tuple[str, ...]) -> dict[str, Any] | None:
    values = list(rows)
    if not values:
        return None
    def key(row: dict[str, Any]) -> tuple[str, str]:
        date_value = next((str(row.get(name, "")) for name in date_keys if row.get(name)), "")
        record_id = str(row.get("financial_fact_id") or row.get("estimate_id") or row.get("market_observation_id") or row.get("valuation_id") or "")
        return date_value, record_id
    return sorted(values, key=key)[-1]


def _index(rows: list[dict[str, Any]], metric_key: str = "metric") -> dict[str, dict[str, list[dict[str, Any]]]]:
    result: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        company_id = str(row.get("company_id", ""))
        metric = str(row.get(metric_key, ""))
        if company_id and metric:
            result[company_id][metric].append(row)
    return result


def _value(row: dict[str, Any] | None) -> Any:
    return None if row is None else row.get("value")


def _record_id(row: dict[str, Any] | None) -> str | None:
    if row is None:
        return None
    return row.get("financial_fact_id") or row.get("estimate_id") or row.get("market_observation_id") or row.get("valuation_id")


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _summary(index: dict[str, list[dict[str, Any]]], metrics: tuple[str, ...], dates: tuple[str, ...]) -> tuple[dict[str, Any], list[str]]:
    values: dict[str, Any] = {}
    source_ids: list[str] = []
    for metric in metrics:
        row = _latest(index.get(metric, []), dates)
        if row is not None:
            values[metric] = {
                "value": row.get("value"),
                "unit": row.get("unit"),
                "currency": row.get("currency"),
                "as_of": next((row.get(name) for name in dates if row.get(name)), None),
            }
            record_id = _record_id(row)
            if record_id:
                source_ids.append(record_id)
    return values, source_ids


def _valuation_summary(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    by_scenario = {str(row.get("scenario")): row for row in rows if row.get("scenario")}
    result: dict[str, Any] = {}
    ids: list[str] = []
    for scenario in ("bear", "base", "bull"):
        row = by_scenario.get(scenario)
        if row:
            result[scenario] = {
                "status": row.get("status"),
                "fair_value_per_share": row.get("blended_fair_value_per_share"),
                "current_price": row.get("current_price"),
                "upside_downside": row.get("upside_downside"),
                "confidence": row.get("confidence"),
            }
            if row.get("valuation_id"):
                ids.append(str(row["valuation_id"]))
    return result, ids


def _valuation_completion(valuations: dict[str, Any]) -> tuple[int, list[str]]:
    weights = {"completed": Decimal("1"), "partial": Decimal("0.5"), "unavailable": Decimal("0")}
    scenario_scores: list[Decimal] = []
    incomplete: list[str] = []
    for scenario in ("bear", "base", "bull"):
        row = valuations.get(scenario)
        status = str(row.get("status", "unavailable")) if isinstance(row, dict) else "unavailable"
        scenario_scores.append(weights.get(status, Decimal("0")))
        if status != "completed":
            incomplete.append(scenario)
    score = int((Decimal("25") * sum(scenario_scores) / Decimal("3")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return score, incomplete


def _shares_quality(financial: dict[str, Any], market: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    financial_shares = _decimal(financial.get("diluted_shares_outstanding", {}).get("value"))
    market_shares = _decimal(market.get("shares_outstanding", {}).get("value"))
    if financial_shares is None or market_shares is None or max(abs(financial_shares), abs(market_shares)) == 0:
        return 0, None
    difference_ratio = abs(financial_shares - market_shares) / max(abs(financial_shares), abs(market_shares))
    if difference_ratio <= Decimal("0.10"):
        return 0, None
    diagnostic = {
        "severity": "warning",
        "code": "shares_outstanding_mismatch",
        "message": "Financial diluted shares and market shares differ by more than 10%",
        "details": {
            "financial_diluted_shares": str(financial_shares),
            "market_shares_outstanding": str(market_shares),
            "difference_ratio": str(difference_ratio.normalize()),
            "threshold": "0.10",
        },
    }
    return -10, diagnostic


def _confidence(financial: dict[str, Any], estimates: dict[str, Any], market: dict[str, Any], valuations: dict[str, Any]) -> tuple[dict[str, Any], list[str], dict[str, Any] | None]:
    financial_required = {"operating_cash_flow", "capital_expenditures", "cash_and_cash_equivalents", "total_debt", "diluted_shares_outstanding"}
    estimate_required = {"revenue", "diluted_eps"}
    market_required = {"current_price", "shares_outstanding", "market_cap", "enterprise_value", "beta"}
    financial_score = round(30 * len(financial_required & set(financial)) / len(financial_required))
    estimate_score = round(25 * len(estimate_required & set(estimates)) / len(estimate_required))
    market_score = round(20 * len(market_required & set(market)) / len(market_required))
    valuation_score, incomplete_scenarios = _valuation_completion(valuations)
    quality_penalty, shares_diagnostic = _shares_quality(financial, market)
    score = max(0, min(100, financial_score + estimate_score + market_score + valuation_score + quality_penalty))
    return {
        "score": score,
        "components": {
            "financial_completeness": financial_score,
            "estimate_completeness": estimate_score,
            "market_completeness": market_score,
            "valuation_completion": valuation_score,
            "quality_penalty": quality_penalty,
        },
    }, incomplete_scenarios, shares_diagnostic


def build_research(
    *,
    registry_dir: str | Path = "data/company_registry",
    financial_dir: str | Path = "data/financial_data",
    estimate_dir: str | Path = "data/estimate_data",
    market_dir: str | Path = "data/market_data",
    valuation_dir: str | Path = "data/valuation_data",
    output_dir: str | Path = "data/research_data",
    company: str | None = None,
    write: bool = False,
    compact: bool = False,
) -> dict[str, Any]:
    registry_root = Path(registry_dir)
    companies = _read_json(registry_root / "companies.json")
    securities = _read_json(registry_root / "securities.json", default=[])
    facts = _read_json(Path(financial_dir) / "financial_facts.json", default=[])
    estimates = _read_json(Path(estimate_dir) / "estimates.json", default=[])
    market = _read_json(Path(market_dir) / "observations.json", default=[])
    valuations = _read_json(Path(valuation_dir) / "valuations.json", default=[])
    for label, payload in (("companies", companies), ("securities", securities), ("financial facts", facts), ("estimates", estimates), ("market observations", market), ("valuations", valuations)):
        if not isinstance(payload, list):
            raise ResearchEngineError(f"canonical {label} input must be a JSON array")
    company_map = {str(row.get("company_id")): row for row in companies if row.get("company_id")}
    ticker_map = {str(row.get("company_id")): str(row.get("ticker", "")).upper() for row in securities if row.get("company_id") and row.get("primary_listing", True)}
    company_ids = sorted(company_map)
    if company:
        token = company.strip()
        company_ids = [cid for cid in company_ids if cid == token or ticker_map.get(cid) == token.upper()]
        if not company_ids:
            raise ResearchEngineError(f"company not found in registry: {company}")
    fact_index, estimate_index, market_index = _index(facts), _index(estimates), _index(market)
    valuation_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in valuations:
        if row.get("company_id"):
            valuation_index[str(row["company_id"])].append(row)
    bundles: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    for company_id in company_ids:
        profile = company_map[company_id]
        financial_summary, financial_ids = _summary(fact_index[company_id], ("revenue", "net_income", "operating_cash_flow", "capital_expenditures", "cash_and_cash_equivalents", "total_debt", "diluted_shares_outstanding"), ("period_end", "filed_at"))
        estimate_summary, estimate_ids = _summary(estimate_index[company_id], ("revenue", "net_income", "diluted_eps", "ebitda"), ("period_end", "as_of_date"))
        market_summary, market_ids = _summary(market_index[company_id], ("current_price", "previous_close", "market_cap", "enterprise_value", "shares_outstanding", "beta"), ("observed_at", "trading_date"))
        valuation_summary, valuation_ids = _valuation_summary(valuation_index[company_id])
        confidence, incomplete_valuation_scenarios, shares_diagnostic = _confidence(financial_summary, estimate_summary, market_summary, valuation_summary)
        missing_layers = [name for name, payload in (("financial", financial_summary), ("estimates", estimate_summary), ("market", market_summary), ("valuation", valuation_summary)) if not payload]
        status = "completed" if not missing_layers and not incomplete_valuation_scenarios else "partial"
        for layer in missing_layers:
            diagnostics.append({"company_id": company_id, "severity": "warning", "code": f"missing_{layer}_layer", "message": f"No canonical {layer} records were available"})
        if incomplete_valuation_scenarios and valuation_summary:
            diagnostics.append({
                "company_id": company_id,
                "severity": "warning",
                "code": "valuation_scenarios_incomplete",
                "message": "One or more valuation scenarios are not completed",
                "details": {"scenarios": incomplete_valuation_scenarios},
            })
        if shares_diagnostic is not None:
            diagnostics.append({"company_id": company_id, **shares_diagnostic})
        current = _decimal(market_summary.get("current_price", {}).get("value"))
        previous = _decimal(market_summary.get("previous_close", {}).get("value"))
        price_change = ((current / previous) - Decimal("1")) if current is not None and previous not in (None, Decimal("0")) else None
        bundle_id = f"research:{company_id.removeprefix('company:')}:{now[:10]}"
        bundles.append({
            "research_bundle_id": bundle_id,
            "company_id": company_id,
            "ticker": ticker_map.get(company_id),
            "status": status,
            "generated_at": now,
            "profile": {"legal_name": profile.get("legal_name"), "display_name": profile.get("display_name"), "country": profile.get("country"), "website": profile.get("website"), "official_sector": profile.get("official_sector"), "official_industry": profile.get("official_industry"), "business_description": profile.get("business_description")},
            "financial_summary": financial_summary,
            "estimate_summary": estimate_summary,
            "market_snapshot": {**market_summary, "price_change_from_previous_close": str(price_change.normalize()) if price_change is not None else None},
            "valuation_summary": valuation_summary,
            "confidence": confidence,
            "source_record_ids": financial_ids + estimate_ids + market_ids + valuation_ids,
        })
        provenance.append({"research_bundle_id": bundle_id, "company_id": company_id, "source_directories": {"registry": str(registry_dir), "financial": str(financial_dir), "estimates": str(estimate_dir), "market": str(market_dir), "valuation": str(valuation_dir)}, "source_record_ids": financial_ids + estimate_ids + market_ids + valuation_ids})
    report = {"companies_requested": len(company_ids), "research_bundles_built": len(bundles), "completed": sum(1 for row in bundles if row["status"] == "completed"), "partial": sum(1 for row in bundles if row["status"] == "partial"), "output_directory": str(output_dir), "dry_run": not write, "acceptance_passed": bool(bundles)}
    if compact:
        report["diagnostic_summary"] = {"errors": sum(1 for row in diagnostics if row["severity"] == "error"), "warnings": sum(1 for row in diagnostics if row["severity"] == "warning")}
    else:
        report["diagnostics"] = diagnostics
    if write:
        root = Path(output_dir)
        manifest = {"schema_version": "1.0.0", "generated_at": now, **{key: value for key, value in report.items() if key != "diagnostics"}, "files": ["company_research.json", "diagnostics.json", "provenance.json", "manifest.json"]}
        _write_atomic(root / "company_research.json", bundles)
        _write_atomic(root / "diagnostics.json", diagnostics)
        _write_atomic(root / "provenance.json", provenance)
        _write_atomic(root / "manifest.json", manifest)
    return report


def validate_research(output_dir: str | Path = "data/research_data") -> dict[str, Any]:
    root = Path(output_dir)
    bundles = _read_json(root / "company_research.json")
    diagnostics = _read_json(root / "diagnostics.json")
    provenance = _read_json(root / "provenance.json")
    manifest = _read_json(root / "manifest.json")
    errors: list[str] = []
    if not isinstance(bundles, list): errors.append("company_research.json must be an array")
    if not isinstance(diagnostics, list): errors.append("diagnostics.json must be an array")
    if not isinstance(provenance, list): errors.append("provenance.json must be an array")
    if not isinstance(manifest, dict): errors.append("manifest.json must be an object")
    required = {"research_bundle_id", "company_id", "status", "profile", "financial_summary", "estimate_summary", "market_snapshot", "valuation_summary", "confidence", "source_record_ids"}
    ids: list[str] = []
    for index, row in enumerate(bundles if isinstance(bundles, list) else []):
        if not isinstance(row, dict): errors.append(f"research[{index}] must be an object"); continue
        missing = required - set(row)
        if missing: errors.append(f"research[{index}] missing: {sorted(missing)}")
        if row.get("research_bundle_id"): ids.append(str(row["research_bundle_id"]))
    if len(ids) != len(set(ids)): errors.append("duplicate research_bundle_id")
    return {"output_directory": str(root), "research_bundles": len(bundles) if isinstance(bundles, list) else 0, "diagnostics": len(diagnostics) if isinstance(diagnostics, list) else 0, "valid": not errors, "errors": errors}
