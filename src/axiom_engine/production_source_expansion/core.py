from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from axiom_engine.production_population.core import build_indexes, load_registry, resolve_company_id

LAYERS = ("financial", "market", "estimate")
BLANK = {None, "", "-", "--", "N/A", "NA", "NULL", "NONE", "PENDING", "TBD"}
VALUE_ALIASES = {
    "financial": {
        "revenue": ("revenue", "revenues", "sales"),
        "net_income": ("net_income",),
        "ebit": ("ebit", "operating_income"),
        "ebitda": ("ebitda",),
        "eps": ("eps", "diluted_eps"),
        "free_cash_flow": ("free_cash_flow", "fcf"),
    },
    "market": {
        "price": ("price", "last_price", "market_price", "close", "previous_close"),
        "volume": ("volume",),
        "market_cap": ("market_cap",),
        "shares_outstanding": ("shares_outstanding",),
        "beta": ("beta",),
    },
    "estimate": {
        "forward_eps": ("forward_eps", "eps_estimate", "eps_fy1", "consensus_eps"),
        "forward_revenue": ("forward_revenue", "revenue_estimate", "revenue_fy1"),
        "forward_ebit": ("forward_ebit", "ebit_estimate", "ebit_fy1"),
        "forward_ebitda": ("forward_ebitda", "ebitda_estimate"),
        "target_price": ("target_price",),
        "analyst_count": ("analyst_count",),
    },
}
DATE_KEYS = {
    "financial": ("period_end", "filing_date", "as_of_date"),
    "market": ("observed_at", "quote_time", "trade_date", "market_date", "session_date", "as_of"),
    "estimate": ("estimate_date", "as_of_date", "as_of"),
}
FINANCIAL_METRIC_MAP = {
    "revenue": "revenue",
    "revenues": "revenue",
    "sales": "revenue",
    "net_income": "net_income",
    "netincomeloss": "net_income",
    "operating_income": "ebit",
    "ebit": "ebit",
    "ebitda": "ebitda",
    "eps": "eps",
    "diluted_eps": "eps",
    "free_cash_flow": "free_cash_flow",
    "fcf": "free_cash_flow",
    "capital_expenditures": "capital_expenditures",
    "cash_and_cash_equivalents": "cash_and_cash_equivalents",
    "total_assets": "total_assets",
    "total_liabilities": "total_liabilities",
    "shareholders_equity": "shareholders_equity",
    "operating_cash_flow": "operating_cash_flow",
    "diluted_shares_outstanding": "diluted_shares_outstanding",
    "total_debt": "total_debt",
}

ESTIMATE_METRIC_MAP = {
    "eps": "forward_eps",
    "diluted_eps": "forward_eps",
    "revenue": "forward_revenue",
    "sales": "forward_revenue",
    "ebit": "forward_ebit",
    "ebitda": "forward_ebitda",
    "target_price": "target_price",
}


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return [dict(x) for x in csv.DictReader(fh)]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("records", "rows", "items", "data", "facts", "observations", "estimates"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        # Market caches commonly store observations as a symbol-keyed mapping.
        symbols = payload.get("symbols")
        if isinstance(symbols, dict):
            return [dict(value, symbol=value.get("symbol") or symbol) for symbol, value in symbols.items() if isinstance(value, dict)]
    return []


def _present(value: Any) -> bool:
    return value not in BLANK and not (isinstance(value, str) and value.strip().upper() in BLANK)


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if _present(row.get(key)):
            return row[key]
    return None


def _coerce_number(value: Any) -> Any:
    if isinstance(value, str):
        token = value.strip().replace(",", "")
        try:
            return float(token)
        except ValueError:
            return value
    return value


def _normalise_values(layer: str, row: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for canonical, aliases in VALUE_ALIASES[layer].items():
        value = _first(row, aliases)
        if _present(value):
            values[canonical] = _coerce_number(value)
    # SEC/XBRL financial exports commonly use metric/value rows.
    if layer == "financial" and _present(row.get("metric")) and _present(row.get("value")):
        metric = FINANCIAL_METRIC_MAP.get(str(row["metric"]).strip().lower())
        if metric:
            values[metric] = _coerce_number(row["value"])
    # Consensus exports commonly use metric/value rows instead of wide columns.
    if layer == "estimate" and _present(row.get("metric")) and _present(row.get("value")):
        metric = ESTIMATE_METRIC_MAP.get(str(row["metric"]).strip().lower())
        if metric:
            values[metric] = _coerce_number(row["value"])
    return values


def _record_id(layer: str, company_id: str, date_value: Any, values: dict[str, Any], provider: str) -> str:
    raw = json.dumps([layer, company_id, str(date_value or ""), provider, values], sort_keys=True, default=str)
    return f"{layer}_fact:" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def _normalise_row(
    layer: str,
    row: dict[str, Any],
    indexes: dict[str, dict[str, str]],
    source_path: str,
    provider: str,
    source_spec: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    company_id, method = resolve_company_id(row, indexes)
    if not company_id:
        return None, "unresolved_identity"
    values = _normalise_values(layer, row)
    if not values:
        return None, "no_usable_values"
    source_spec = source_spec or {}
    observed_at = _first(row, DATE_KEYS[layer]) or source_spec.get("as_of_date")
    if layer == "market" and not observed_at:
        return None, "missing_market_date"
    security_id = row.get("security_id")
    ticker = row.get("ticker") or row.get("symbol")
    result = {
        "record_id": _record_id(layer, company_id, observed_at, values, provider),
        "semantic_type": f"{layer}_fact",
        "company_id": company_id,
        "security_id": security_id,
        "ticker": ticker,
        "observed_at": observed_at,
        "provider": provider,
        "source_path": source_path,
        "linkage_method": method,
        "values": values,
        **values,
    }
    if layer == "estimate":
        result["fiscal_period"] = row.get("fiscal_period") or row.get("forecast_period")
        result["fiscal_year"] = row.get("fiscal_year")
        result["period_end"] = row.get("period_end")
        result["estimate_type"] = row.get("estimate_type") or row.get("estimate_kind") or "provider"
        result["estimate_kind"] = row.get("estimate_kind")
        result["unit"] = row.get("unit")
        result["currency"] = row.get("currency") or source_spec.get("currency")
        result["analyst_count"] = _coerce_number(row.get("analyst_count")) if _present(row.get("analyst_count")) else None
        result["source_record_id"] = row.get("source_record_id") or row.get("estimate_id")
        result["record_state"] = "complete"
    if layer == "financial":
        result["financial_fact_id"] = row.get("financial_fact_id") or row.get("fact_id")
        result["metric"] = row.get("metric")
        result["value"] = _coerce_number(row.get("value")) if _present(row.get("value")) else None
        result["unit"] = row.get("unit")
        result["currency"] = row.get("currency") or source_spec.get("currency")
        result["period_type"] = row.get("period_type")
        result["period_start"] = row.get("period_start")
        result["fiscal_year"] = row.get("fiscal_year")
        result["fiscal_period"] = row.get("fiscal_period")
        result["period_end"] = row.get("period_end") or observed_at
        result["statement"] = row.get("statement")
        result["form_type"] = row.get("form_type")
        result["accession_number"] = row.get("accession_number")
        result["audited"] = row.get("audited")
        result["provenance_ids"] = row.get("provenance_ids") or row.get("source_ids") or []
        result["metadata"] = row.get("metadata") or {}
        result["record_state"] = "official" if row.get("audited") is True else "partial"
    if layer == "market":
        result["currency"] = row.get("currency") or source_spec.get("currency")
        result["market_state"] = row.get("market_state") or source_spec.get("market_state") or "historical"
        result["exchange_timezone"] = row.get("exchange_timezone")
        result["session_date"] = row.get("session_date") or observed_at
    return result, None


def expand_production_sources(repository_root: Path, population_dir: Path = Path("data/universe"), config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    companies, securities = load_registry(repository_root, population_dir)
    indexes = build_indexes(companies, securities)
    outputs: dict[str, list[dict[str, Any]]] = {layer: [] for layer in LAYERS}
    rejected: list[dict[str, Any]] = []
    source_summaries: list[dict[str, Any]] = []

    for layer in LAYERS:
        for spec in config.get("sources", {}).get(layer, []):
            source_path = str(spec["path"])
            provider = str(spec.get("provider") or "unknown")
            rows = _rows(repository_root / source_path)
            accepted = 0
            reasons: Counter[str] = Counter()
            for index, row in enumerate(rows):
                normalised, reason = _normalise_row(layer, row, indexes, source_path, provider, spec)
                if normalised:
                    outputs[layer].append(normalised)
                    accepted += 1
                else:
                    reasons[str(reason)] += 1
                    rejected.append({"layer": layer, "source_path": source_path, "row_index": index, "reason": reason})
            source_summaries.append({
                "layer": layer, "source_path": source_path, "provider": provider,
                "input_rows": len(rows), "accepted_rows": accepted,
                "rejected_rows": len(rows) - accepted, "rejection_reasons": dict(reasons),
            })

    # Stable dedupe by canonical record id.
    for layer in LAYERS:
        deduped = {row["record_id"]: row for row in outputs[layer]}
        outputs[layer] = sorted(deduped.values(), key=lambda x: x["record_id"])

    company_counts = {layer: len({x["company_id"] for x in outputs[layer]}) for layer in LAYERS}
    universe = len(companies)
    return {
        "schema_version": "production-source-expansion-summary.v030.6.4",
        "version": "V030.6.4",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe_company_count": universe,
        "outputs": outputs,
        "rejected_records": rejected,
        "source_summaries": source_summaries,
        "coverage": {
            layer: {
                "record_count": len(outputs[layer]),
                "company_count": company_counts[layer],
                "company_coverage_pct": round(company_counts[layer] / universe * 100, 4) if universe else 0.0,
            } for layer in LAYERS
        },
    }


def write_expansion_outputs(payload: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    names = {"financial": "financial_facts.json", "market": "market_facts.json", "estimate": "estimate_facts.json"}
    for layer, filename in names.items():
        (output_dir / filename).write_text(json.dumps(payload["outputs"][layer], ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {k: v for k, v in payload.items() if k not in {"outputs", "rejected_records"}}
    (output_dir / "expansion_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "rejected_records.json").write_text(json.dumps(payload["rejected_records"], ensure_ascii=False, indent=2), encoding="utf-8")
