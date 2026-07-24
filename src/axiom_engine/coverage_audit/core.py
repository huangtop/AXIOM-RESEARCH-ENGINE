from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "1.0.0"
REQUIRED_OUTPUTS = (
    "coverage_report.json",
    "coverage_failures.json",
    "company_readiness.json",
    "manifest.json",
)


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _json_files(path: str | Path | None) -> list[Path]:
    if path is None:
        return []
    candidate = Path(path)
    if not candidate.exists():
        return []
    if candidate.is_file():
        return [candidate] if candidate.suffix.lower() == ".json" else []
    return sorted(item for item in candidate.rglob("*.json") if item.is_file())


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in (
        "companies",
        "securities",
        "records",
        "items",
        "facts",
        "estimates",
        "observations",
        "valuations",
        "results",
        "bundles",
        "cards",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]


def _first(record: Mapping[str, Any], *paths: str) -> Any:
    for path in paths:
        current: Any = record
        found = True
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                found = False
                break
            current = current[part]
        if found and current not in (None, "", [], {}):
            return current
    return None


def _normalise_ticker(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _record_identity(record: Mapping[str, Any]) -> tuple[str | None, str | None]:
    company_id = _first(record, "company_id", "company.company_id", "issuer.company_id")
    ticker = _first(
        record,
        "ticker",
        "symbol",
        "security.ticker",
        "primary_security.ticker",
        "profile.ticker",
    )
    return (str(company_id) if company_id else None, _normalise_ticker(ticker))


def _metric_name(record: Mapping[str, Any]) -> str:
    value = _first(record, "metric", "concept", "field", "name", "canonical_name", "data_type")
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _has_value(record: Mapping[str, Any]) -> bool:
    value = _first(record, "value", "amount", "reported_value", "normalized_value", "fair_value")
    return value is not None


@dataclass
class CompanyState:
    company_id: str
    ticker: str | None
    display_name: str | None = None
    registry: bool = True
    financial: bool = False
    revenue: bool = False
    market_price: bool = False
    market_shares: bool = False
    estimates: bool = False
    valuation: bool = False
    research: bool = False

    def missing_inputs(self) -> list[str]:
        missing: list[str] = []
        if not self.revenue:
            missing.append("revenue")
        if not self.market_price:
            missing.append("market_price")
        if not self.market_shares:
            missing.append("shares_outstanding")
        if not self.valuation:
            missing.append("valuation")
        return missing

    def readiness(self) -> str:
        if self.revenue and self.market_price and self.market_shares and self.valuation:
            return "ready"
        if self.revenue or self.market_price or self.market_shares or self.valuation or self.financial:
            return "partial"
        return "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "company_id": self.company_id,
            "ticker": self.ticker,
            "display_name": self.display_name,
            "status": self.readiness(),
            "coverage": {
                "registry": self.registry,
                "financial": self.financial,
                "revenue": self.revenue,
                "market_price": self.market_price,
                "market_shares": self.market_shares,
                "estimates": self.estimates,
                "valuation": self.valuation,
                "research": self.research,
            },
            "valuation_eligible": self.revenue and self.market_price and self.market_shares,
            "missing_inputs": self.missing_inputs(),
        }


def _load_layer(path: str | Path | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for file_path in _json_files(path):
        try:
            records.extend(_records(_load_json(file_path)))
        except (OSError, json.JSONDecodeError):
            continue
    return records


def _index_companies(registry_records: Iterable[dict[str, Any]]) -> tuple[dict[str, CompanyState], dict[str, str]]:
    companies: dict[str, CompanyState] = {}
    ticker_to_company: dict[str, str] = {}
    for record in registry_records:
        company_id, ticker = _record_identity(record)
        if company_id is None:
            company_id = f"ticker:{ticker}" if ticker else None
        if company_id is None:
            continue
        display_name = _first(record, "display_name", "legal_name", "name", "company.display_name")
        state = companies.setdefault(
            company_id,
            CompanyState(company_id=company_id, ticker=ticker, display_name=str(display_name) if display_name else None),
        )
        if state.ticker is None and ticker:
            state.ticker = ticker
        if state.display_name is None and display_name:
            state.display_name = str(display_name)
        if ticker:
            ticker_to_company[ticker] = company_id
    return companies, ticker_to_company


def _resolve_company(record: Mapping[str, Any], companies: dict[str, CompanyState], ticker_map: dict[str, str]) -> CompanyState | None:
    company_id, ticker = _record_identity(record)
    key = company_id or (ticker_map.get(ticker) if ticker else None)
    if key is None and ticker:
        key = f"ticker:{ticker}"
    if key is None:
        return None
    if key not in companies:
        companies[key] = CompanyState(company_id=key, ticker=ticker, registry=False)
    if ticker and not companies[key].ticker:
        companies[key].ticker = ticker
    if ticker:
        ticker_map.setdefault(ticker, key)
    return companies[key]


def _mark_financial(records: Iterable[dict[str, Any]], companies: dict[str, CompanyState], ticker_map: dict[str, str]) -> None:
    revenue_tokens = {"revenue", "revenues", "sales", "total_revenue", "revenue_ttm"}
    for record in records:
        state = _resolve_company(record, companies, ticker_map)
        if state is None:
            continue
        state.financial = True
        metric = _metric_name(record)
        if metric in revenue_tokens and _has_value(record):
            state.revenue = True
        if _first(record, "revenue", "financials.revenue", "income_statement.revenue") is not None:
            state.revenue = True


def _mark_estimates(records: Iterable[dict[str, Any]], companies: dict[str, CompanyState], ticker_map: dict[str, str]) -> None:
    for record in records:
        state = _resolve_company(record, companies, ticker_map)
        if state is not None:
            state.estimates = True


def _mark_market(records: Iterable[dict[str, Any]], companies: dict[str, CompanyState], ticker_map: dict[str, str]) -> None:
    price_tokens = {"price", "current_price", "last_price", "close", "previous_close"}
    share_tokens = {"shares", "shares_outstanding", "diluted_shares_outstanding"}
    for record in records:
        state = _resolve_company(record, companies, ticker_map)
        if state is None:
            continue
        metric = _metric_name(record)
        if metric in price_tokens and _has_value(record):
            state.market_price = True
        if metric in share_tokens and _has_value(record):
            state.market_shares = True
        if _first(record, "current_price", "market.current_price.value", "price") is not None:
            state.market_price = True
        if _first(record, "shares_outstanding", "market.shares_outstanding.value") is not None:
            state.market_shares = True


def _mark_valuation(records: Iterable[dict[str, Any]], companies: dict[str, CompanyState], ticker_map: dict[str, str]) -> None:
    for record in records:
        state = _resolve_company(record, companies, ticker_map)
        if state is None:
            continue
        status = str(_first(record, "status", "valuation.status") or "").lower()
        fair_value = _first(
            record,
            "fair_value",
            "valuation.base.fair_value",
            "base.fair_value",
            "scenarios.base.fair_value",
        )
        if fair_value is not None or status in {"completed", "partial", "available", "ready"}:
            state.valuation = True


def _mark_research(records: Iterable[dict[str, Any]], companies: dict[str, CompanyState], ticker_map: dict[str, str]) -> None:
    for record in records:
        state = _resolve_company(record, companies, ticker_map)
        if state is not None:
            state.research = True


def _coverage_metric(states: list[CompanyState], attr: str) -> dict[str, Any]:
    total = len(states)
    covered = sum(1 for state in states if bool(getattr(state, attr)))
    return {
        "covered": covered,
        "total": total,
        "coverage_rate": round(covered / total, 6) if total else 0.0,
    }


def build_coverage_audit(
    *,
    registry_path: str | Path,
    financial_path: str | Path | None = None,
    estimate_path: str | Path | None = None,
    market_path: str | Path | None = None,
    valuation_path: str | Path | None = None,
    research_path: str | Path | None = None,
    output_dir: str | Path = "data/coverage_audit",
    write: bool = False,
) -> dict[str, Any]:
    registry_records = _load_layer(registry_path)
    companies, ticker_map = _index_companies(registry_records)
    _mark_financial(_load_layer(financial_path), companies, ticker_map)
    _mark_estimates(_load_layer(estimate_path), companies, ticker_map)
    _mark_market(_load_layer(market_path), companies, ticker_map)
    _mark_valuation(_load_layer(valuation_path), companies, ticker_map)
    _mark_research(_load_layer(research_path), companies, ticker_map)

    states = sorted(companies.values(), key=lambda item: (item.ticker or "", item.company_id))
    readiness_counts = Counter(state.readiness() for state in states)
    now = datetime.now(timezone.utc).isoformat()

    metrics = {
        "registry": _coverage_metric(states, "registry"),
        "financial": _coverage_metric(states, "financial"),
        "revenue": _coverage_metric(states, "revenue"),
        "market_price": _coverage_metric(states, "market_price"),
        "market_shares": _coverage_metric(states, "market_shares"),
        "estimates": _coverage_metric(states, "estimates"),
        "valuation": _coverage_metric(states, "valuation"),
        "research": _coverage_metric(states, "research"),
    }
    eligible = sum(1 for state in states if state.revenue and state.market_price and state.market_shares)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now,
        "company_count": len(states),
        "readiness": {
            "ready": readiness_counts.get("ready", 0),
            "partial": readiness_counts.get("partial", 0),
            "blocked": readiness_counts.get("blocked", 0),
        },
        "valuation_eligibility": {
            "eligible": eligible,
            "total": len(states),
            "coverage_rate": round(eligible / len(states), 6) if states else 0.0,
        },
        "coverage": metrics,
    }
    readiness = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now,
        "companies": [state.to_dict() for state in states],
    }
    failures = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now,
        "failure_count": sum(1 for state in states if state.readiness() != "ready"),
        "failures": [state.to_dict() for state in states if state.readiness() != "ready"],
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now,
        "source": "canonical_coverage_audit",
        "outputs": list(REQUIRED_OUTPUTS[:-1]),
        "company_count": len(states),
    }

    result = {
        "valid": bool(states),
        "company_count": len(states),
        "ready": readiness_counts.get("ready", 0),
        "partial": readiness_counts.get("partial", 0),
        "blocked": readiness_counts.get("blocked", 0),
        "output_dir": str(output_dir),
    }
    if write:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        payloads = {
            "coverage_report.json": report,
            "coverage_failures.json": failures,
            "company_readiness.json": readiness,
            "manifest.json": manifest,
        }
        for filename, payload in payloads.items():
            with (output / filename).open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
    return result


def validate_coverage_audit(output_dir: str | Path = "data/coverage_audit") -> dict[str, Any]:
    output = Path(output_dir)
    errors: list[str] = []
    payloads: dict[str, Any] = {}
    for filename in REQUIRED_OUTPUTS:
        path = output / filename
        if not path.exists():
            errors.append(f"missing output: {filename}")
            continue
        try:
            payloads[filename] = _load_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid JSON: {filename}: {exc}")
    report = payloads.get("coverage_report.json")
    readiness = payloads.get("company_readiness.json")
    failures = payloads.get("coverage_failures.json")
    if isinstance(report, dict) and isinstance(readiness, dict):
        companies = readiness.get("companies", [])
        if report.get("company_count") != len(companies):
            errors.append("company_count does not match company_readiness")
        statuses = Counter(item.get("status") for item in companies if isinstance(item, dict))
        for status in ("ready", "partial", "blocked"):
            if report.get("readiness", {}).get(status, 0) != statuses.get(status, 0):
                errors.append(f"readiness count mismatch: {status}")
    if isinstance(failures, dict) and isinstance(readiness, dict):
        expected = sum(1 for item in readiness.get("companies", []) if item.get("status") != "ready")
        if failures.get("failure_count") != expected:
            errors.append("failure_count mismatch")
    return {
        "valid": not errors,
        "errors": errors,
        "output_dir": str(output),
        "company_count": report.get("company_count", 0) if isinstance(report, dict) else 0,
    }
