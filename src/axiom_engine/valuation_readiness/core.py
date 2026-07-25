from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class ReadinessError(ValueError):
    pass


VERSION = "V030.3"
SCHEMA_VERSION = "valuation-readiness.v030.3"
MODELS = (
    "forward_pe",
    "peg",
    "forward_ps",
    "ev_ebitda",
    "forward_pb",
    "milestone",
)
STATUSES = {"ready", "partial", "blocked"}

FINANCIAL_ALIASES: dict[str, set[str]] = {
    "revenue": {"revenue", "revenues", "sales", "total_revenue"},
    "ebitda": {"ebitda", "adjusted_ebitda"},
    "equity": {"stockholders_equity", "shareholders_equity", "total_equity", "book_value"},
    "debt": {"total_debt", "debt", "long_term_debt", "short_term_debt"},
    "cash": {"cash", "cash_and_cash_equivalents", "cash_equivalents"},
    "shares": {"shares_outstanding", "weighted_average_shares", "diluted_shares"},
    "eps": {"eps", "diluted_eps", "earnings_per_share"},
}
ESTIMATE_ALIASES: dict[str, set[str]] = {
    "forward_eps": {"forward_eps", "eps_forward", "next_year_eps", "eps_ntm", "eps_fy1"},
    "forward_eps_growth": {"forward_eps_growth", "eps_growth", "next_year_eps_growth", "eps_growth_fy1"},
    "forward_revenue": {"forward_revenue", "revenue_forward", "next_year_revenue", "revenue_ntm", "revenue_fy1"},
    "forward_ebitda": {"forward_ebitda", "ebitda_forward", "next_year_ebitda", "ebitda_ntm", "ebitda_fy1"},
    "milestone_probability": {"milestone_probability", "success_probability", "probability_of_success"},
    "milestone_value": {"milestone_value", "scenario_value", "risk_adjusted_value"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"cannot read {path}: {exc}") from exc


def _rows(payload: Any, keys: Iterable[str]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def _first_existing(root: Path, candidates: Iterable[str]) -> Path | None:
    for relative in candidates:
        path = root / relative
        if path.is_file():
            return path
    return None


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _company_id(row: dict[str, Any], security_to_company: dict[str, str], ticker_to_company: dict[str, str]) -> str | None:
    direct = str(row.get("company_id") or "").strip()
    if direct:
        return direct
    sid = str(row.get("security_id") or "").strip()
    if sid and sid in security_to_company:
        return security_to_company[sid]
    ticker = str(row.get("ticker") or row.get("symbol") or "").strip().upper()
    return ticker_to_company.get(ticker) if ticker else None


def _latest_numeric(rows: list[dict[str, Any]], key_fields: tuple[str, ...]) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in rows:
        key = ""
        for field in key_fields:
            if row.get(field) not in (None, ""):
                key = _norm(row.get(field))
                break
        value = _number(row.get("value"))
        if value is None:
            for field in ("consensus", "estimate", "mean", "price", "previous_close", "close", "market_cap", "shares_outstanding"):
                value = _number(row.get(field))
                if value is not None:
                    break
        if key and value is not None:
            result[key] = value
    return result


def _alias_value(values: dict[str, float], aliases: set[str]) -> float | None:
    for alias in aliases:
        if alias in values:
            return values[alias]
    return None


def _market_values(rows: list[dict[str, Any]]) -> dict[str, float]:
    values = _latest_numeric(rows, ("metric", "concept", "field"))
    for row in rows:
        for key in ("previous_close", "price", "close", "last_price"):
            value = _number(row.get(key))
            if value is not None:
                values.setdefault("price", value)
                break
        for key in ("shares_outstanding", "shares"):
            value = _number(row.get(key))
            if value is not None:
                values.setdefault("shares", value)
                break
        value = _number(row.get("market_cap"))
        if value is not None:
            values.setdefault("market_cap", value)
    return values


def _reason(code: str, requirement: str, source_layer: str) -> dict[str, str]:
    return {"code": code, "requirement": requirement, "source_layer": source_layer}


def _model_checks(fin: dict[str, float], est: dict[str, float], market: dict[str, float]) -> dict[str, tuple[bool, list[dict[str, str]]]]:
    price = market.get("price")
    shares = market.get("shares") or _alias_value(fin, FINANCIAL_ALIASES["shares"])
    market_cap = market.get("market_cap")
    has_equity_value = market_cap is not None or (price is not None and shares is not None)
    forward_eps = _alias_value(est, ESTIMATE_ALIASES["forward_eps"])
    eps_growth = _alias_value(est, ESTIMATE_ALIASES["forward_eps_growth"])
    forward_revenue = _alias_value(est, ESTIMATE_ALIASES["forward_revenue"])
    forward_ebitda = _alias_value(est, ESTIMATE_ALIASES["forward_ebitda"])
    ebitda = forward_ebitda or _alias_value(fin, FINANCIAL_ALIASES["ebitda"])
    equity = _alias_value(fin, FINANCIAL_ALIASES["equity"])
    milestone_probability = _alias_value(est, ESTIMATE_ALIASES["milestone_probability"])
    milestone_value = _alias_value(est, ESTIMATE_ALIASES["milestone_value"])

    checks: dict[str, tuple[bool, list[dict[str, str]]]] = {}

    def require(items: list[tuple[bool, dict[str, str]]]) -> tuple[bool, list[dict[str, str]]]:
        missing = [reason for ok, reason in items if not ok]
        return (not missing, missing)

    checks["forward_pe"] = require([
        (price is not None, _reason("MISSING_MARKET_PRICE", "market price", "market")),
        (forward_eps is not None and forward_eps > 0, _reason("MISSING_POSITIVE_FORWARD_EPS", "positive forward EPS", "estimate")),
    ])
    checks["peg"] = require([
        (price is not None, _reason("MISSING_MARKET_PRICE", "market price", "market")),
        (forward_eps is not None and forward_eps > 0, _reason("MISSING_POSITIVE_FORWARD_EPS", "positive forward EPS", "estimate")),
        (eps_growth is not None and eps_growth > 0, _reason("MISSING_POSITIVE_FORWARD_EPS_GROWTH", "positive forward EPS growth", "estimate")),
    ])
    checks["forward_ps"] = require([
        (has_equity_value, _reason("MISSING_EQUITY_VALUE_INPUT", "market cap or price plus shares", "market")),
        (forward_revenue is not None and forward_revenue > 0, _reason("MISSING_POSITIVE_FORWARD_REVENUE", "positive forward revenue", "estimate")),
    ])
    checks["ev_ebitda"] = require([
        (has_equity_value, _reason("MISSING_EQUITY_VALUE_INPUT", "market cap or price plus shares", "market")),
        (ebitda is not None and ebitda > 0, _reason("MISSING_POSITIVE_EBITDA", "positive EBITDA or forward EBITDA", "financial_or_estimate")),
    ])
    checks["forward_pb"] = require([
        (has_equity_value, _reason("MISSING_EQUITY_VALUE_INPUT", "market cap or price plus shares", "market")),
        (equity is not None and equity > 0, _reason("MISSING_POSITIVE_BOOK_VALUE", "positive shareholders equity", "financial")),
    ])
    checks["milestone"] = require([
        (milestone_probability is not None, _reason("MISSING_MILESTONE_PROBABILITY", "milestone probability", "estimate")),
        (milestone_value is not None, _reason("MISSING_MILESTONE_VALUE", "milestone or scenario value", "estimate")),
    ])
    return checks


def build_valuation_readiness(
    *,
    repository_root: str | Path = ".",
    population_dir: str | Path = "data/universe",
    output_dir: str | Path = "data/generated/valuation_readiness",
    write: bool = False,
    strict: bool = False,
) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    population = root / Path(population_dir)
    output = root / Path(output_dir)
    companies_path = population / "companies.json"
    securities_path = population / "securities.json"
    if not companies_path.is_file() or not securities_path.is_file():
        raise ReadinessError(f"population registry incomplete under {population}")
    companies = _rows(_load(companies_path), ("companies",))
    securities = _rows(_load(securities_path), ("securities",))
    company_ids = {str(row.get("company_id")) for row in companies if row.get("company_id")}
    if not company_ids:
        raise ReadinessError("population contains no company_id")

    security_to_company = {str(row.get("security_id")): str(row.get("company_id")) for row in securities if row.get("security_id") and row.get("company_id")}
    ticker_to_company: dict[str, str] = {}
    primary_security: dict[str, dict[str, Any]] = {}
    for row in securities:
        cid = str(row.get("company_id") or "")
        ticker = str(row.get("ticker") or "").upper()
        if ticker and cid:
            ticker_to_company.setdefault(ticker, cid)
        if cid and (row.get("primary_listing") is True or cid not in primary_security):
            primary_security[cid] = row

    source_paths = {
        "financial": _first_existing(root, (
            "data/financials/financial_facts.json",
            "data/financial_population_baseline/financial_source/financial_facts.json",
            "data/valuation/financial_facts.json",
            "data/onboarding/generated/financial_facts.json",
        )),
        "market": _first_existing(root, (
            "data/market/market_snapshots.json",
            "data/market_data/market_snapshots.json",
            "data/generated/market_snapshots.json",
        )),
        "estimate": _first_existing(root, (
            "data/estimates/consensus_estimates.json",
            "data/estimate_data/consensus_estimates.json",
            "data/valuation/estimates.json",
        )),
    }
    source_keys = {
        "financial": ("financial_facts", "facts", "data"),
        "market": ("market_snapshots", "snapshots", "data"),
        "estimate": ("consensus_estimates", "estimates", "data"),
    }
    layer_rows: dict[str, list[dict[str, Any]]] = {}
    for layer, path in source_paths.items():
        layer_rows[layer] = _rows(_load(path), source_keys[layer]) if path else []

    indexed: dict[str, dict[str, list[dict[str, Any]]]] = {
        layer: defaultdict(list) for layer in source_paths
    }
    diagnostics: list[dict[str, Any]] = []
    for layer, rows in layer_rows.items():
        for index, row in enumerate(rows):
            cid = _company_id(row, security_to_company, ticker_to_company)
            if cid in company_ids:
                indexed[layer][cid].append(row)
            else:
                diagnostics.append({"severity": "warning", "code": "UNRESOLVED_COMPANY_LINK", "layer": layer, "row": index, "company_id": cid})

    company_by_id = {str(row.get("company_id")): row for row in companies if row.get("company_id")}
    records: list[dict[str, Any]] = []
    status_counter: Counter[str] = Counter()
    model_eligible_counter: Counter[str] = Counter()
    reason_counter: Counter[str] = Counter()

    for cid in sorted(company_ids):
        fin = _latest_numeric(indexed["financial"].get(cid, []), ("concept", "metric", "canonical_metric"))
        est = _latest_numeric(indexed["estimate"].get(cid, []), ("metric", "concept", "canonical_metric"))
        market = _market_values(indexed["market"].get(cid, []))
        checks = _model_checks(fin, est, market)
        eligible = [model for model in MODELS if checks[model][0]]
        blocked = [{"model": model, "reasons": checks[model][1]} for model in MODELS if not checks[model][0]]
        if len(eligible) >= 2:
            status = "ready"
        elif len(eligible) == 1:
            status = "partial"
        else:
            status = "blocked"
        status_counter[status] += 1
        model_eligible_counter.update(eligible)
        for item in blocked:
            reason_counter.update(reason["code"] for reason in item["reasons"])
        company = company_by_id[cid]
        security = primary_security.get(cid, {})
        records.append({
            "schema_version": SCHEMA_VERSION,
            "company_id": cid,
            "security_id": security.get("security_id") or company.get("primary_security_id"),
            "ticker": security.get("ticker"),
            "display_name": company.get("display_name") or company.get("legal_name"),
            "status": status,
            "valuation_ready": bool(eligible),
            "eligible_models": eligible,
            "blocked_models": blocked,
            "data_presence": {
                "financial": bool(indexed["financial"].get(cid)),
                "market": bool(indexed["market"].get(cid)),
                "estimate": bool(indexed["estimate"].get(cid)),
            },
            "input_counts": {
                "financial_facts": len(indexed["financial"].get(cid, [])),
                "market_snapshots": len(indexed["market"].get(cid, [])),
                "estimates": len(indexed["estimate"].get(cid, [])),
            },
        })

    source_inventory = {
        layer: {
            "path": str(path.relative_to(root)) if path else None,
            "found": path is not None,
            "row_count": len(layer_rows[layer]),
            "linked_company_count": len(indexed[layer]),
        }
        for layer, path in source_paths.items()
    }
    total = len(records)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "generated_at": _now(),
        "universe_company_count": total,
        "status_counts": {status: status_counter.get(status, 0) for status in ("ready", "partial", "blocked")},
        "displayable_company_count": status_counter["ready"] + status_counter["partial"],
        "displayable_pct": round((status_counter["ready"] + status_counter["partial"]) * 100 / total, 4) if total else 0.0,
        "model_eligible_counts": {model: model_eligible_counter.get(model, 0) for model in MODELS},
        "top_blocking_reasons": dict(reason_counter.most_common()),
        "source_inventory": source_inventory,
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "generated_at": summary["generated_at"],
        "valid": total == len(company_ids),
        "universe_company_count": len(company_ids),
        "readiness_record_count": total,
        "diagnostic_count": len(diagnostics),
        "files": ["company_readiness.json", "readiness_summary.json", "readiness_diagnostics.json", "readiness_manifest.json"],
        "status_definition": {"ready": "two or more eligible models", "partial": "one eligible model", "blocked": "no eligible models"},
    }
    if strict and not manifest["valid"]:
        raise ReadinessError("readiness record count does not match universe")
    if write:
        output.mkdir(parents=True, exist_ok=True)
        for name, payload in (
            ("company_readiness.json", records),
            ("readiness_summary.json", summary),
            ("readiness_diagnostics.json", diagnostics),
            ("readiness_manifest.json", manifest),
        ):
            (output / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**summary, "output_dir": str(output), "dry_run": not write, "valid": manifest["valid"]}


def validate_valuation_readiness(
    *,
    repository_root: str | Path = ".",
    population_dir: str | Path = "data/universe",
    output_dir: str | Path = "data/generated/valuation_readiness",
    strict: bool = False,
) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    population = root / Path(population_dir)
    output = root / Path(output_dir)
    required = ["company_readiness.json", "readiness_summary.json", "readiness_diagnostics.json", "readiness_manifest.json"]
    errors: list[str] = []
    for name in required:
        if not (output / name).is_file():
            errors.append(f"MISSING_OUTPUT:{name}")
    if errors:
        result = {"valid": False, "errors": errors, "output_dir": str(output)}
        if strict:
            raise ReadinessError("; ".join(errors))
        return result
    records = _rows(_load(output / "company_readiness.json"), ("records",))
    summary = _load(output / "readiness_summary.json")
    manifest = _load(output / "readiness_manifest.json")
    companies = _rows(_load(population / "companies.json"), ("companies",))
    universe_ids = {str(row.get("company_id")) for row in companies if row.get("company_id")}
    record_ids = [str(row.get("company_id") or "") for row in records]
    duplicate_ids = sorted(cid for cid, count in Counter(record_ids).items() if cid and count > 1)
    missing_ids = sorted(universe_ids - set(record_ids))
    extra_ids = sorted(set(record_ids) - universe_ids)
    invalid_status = [row.get("company_id") for row in records if row.get("status") not in STATUSES]
    invalid_models: list[str] = []
    malformed_blocked: list[str] = []
    for row in records:
        cid = str(row.get("company_id") or "")
        eligible = row.get("eligible_models")
        blocked = row.get("blocked_models")
        if not isinstance(eligible, list) or any(model not in MODELS for model in eligible):
            invalid_models.append(cid)
        if not isinstance(blocked, list):
            malformed_blocked.append(cid)
            continue
        for item in blocked:
            if not isinstance(item, dict) or item.get("model") not in MODELS or not isinstance(item.get("reasons"), list) or not item.get("reasons"):
                malformed_blocked.append(cid)
                break
            if any(not isinstance(reason, dict) or not reason.get("code") for reason in item["reasons"]):
                malformed_blocked.append(cid)
                break
    if duplicate_ids: errors.append(f"DUPLICATE_COMPANY_IDS:{len(duplicate_ids)}")
    if missing_ids: errors.append(f"MISSING_COMPANIES:{len(missing_ids)}")
    if extra_ids: errors.append(f"UNKNOWN_COMPANIES:{len(extra_ids)}")
    if invalid_status: errors.append(f"INVALID_STATUS:{len(invalid_status)}")
    if invalid_models: errors.append(f"INVALID_ELIGIBLE_MODELS:{len(invalid_models)}")
    if malformed_blocked: errors.append(f"MALFORMED_BLOCKED_MODELS:{len(set(malformed_blocked))}")
    if not isinstance(summary, dict) or summary.get("universe_company_count") != len(universe_ids):
        errors.append("SUMMARY_UNIVERSE_COUNT_MISMATCH")
    if not isinstance(manifest, dict) or manifest.get("readiness_record_count") != len(records):
        errors.append("MANIFEST_RECORD_COUNT_MISMATCH")
    result = {
        "valid": not errors,
        "errors": errors,
        "universe_company_count": len(universe_ids),
        "readiness_record_count": len(records),
        "duplicate_company_count": len(duplicate_ids),
        "missing_company_count": len(missing_ids),
        "unknown_company_count": len(extra_ids),
        "invalid_status_count": len(invalid_status),
        "invalid_model_count": len(invalid_models),
        "malformed_blocked_model_count": len(set(malformed_blocked)),
        "status_counts": summary.get("status_counts") if isinstance(summary, dict) else None,
        "displayable_company_count": summary.get("displayable_company_count") if isinstance(summary, dict) else None,
        "output_dir": str(output),
    }
    if strict and errors:
        raise ReadinessError("; ".join(errors))
    return result
