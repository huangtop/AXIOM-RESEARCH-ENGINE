from __future__ import annotations
from dataclasses import dataclass
from typing import Any

FIELD_ALIASES = {
    "company_id": ("company_id", "companyId"),
    "ticker": ("ticker", "symbol", "code"),
    "metric": ("metric", "estimate_metric", "field"),
    "value": ("value", "estimate", "consensus", "consensus_mean", "avg", "average"),
    "unit": ("unit",),
    "currency": ("currency", "reportedCurrency"),
    "period_end": ("period_end", "periodEnd", "date", "fiscalDateEnding", "target_date"),
    "fiscal_year": ("fiscal_year", "fiscalYear", "year"),
    "fiscal_period": ("fiscal_period", "fiscalPeriod", "period"),
    "estimate_kind": ("estimate_kind", "estimateKind", "kind"),
    "analyst_count": ("analyst_count", "analystCount", "numberOfAnalysts", "numAnalysts"),
    "source_record_id": ("source_record_id", "sourceRecordId", "id"),
    "template_status": ("template_status",),
}

METRIC_ALIASES = {
    "revenue": "revenue", "revenues": "revenue", "sales": "revenue", "revenueestimate": "revenue",
    "netincome": "net_income", "net_income": "net_income", "earnings": "net_income", "netincomeestimate": "net_income",
    "eps": "diluted_eps", "dilutedeps": "diluted_eps", "diluted_eps": "diluted_eps", "epsestimate": "diluted_eps",
}

@dataclass(frozen=True)
class AdapterResult:
    adapter_id: str
    rows: list[dict[str, Any]]


def _first(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return ""


def _canonicalize(row: dict[str, Any]) -> dict[str, Any]:
    out = {field: _first(row, aliases) for field, aliases in FIELD_ALIASES.items()}
    metric = str(out.get("metric") or "").strip()
    key = metric.replace(" ", "").replace("-", "").lower()
    out["metric"] = METRIC_ALIASES.get(key, metric.lower())
    return out


def adapt_rows(rows: list[dict[str, Any]], adapter: str = "auto") -> AdapterResult:
    requested = (adapter or "auto").strip().lower().replace("-", "_")
    supported = {"auto", "canonical", "generic", "fmp", "finnhub", "polygon", "yahoo", "alpha_vantage"}
    if requested not in supported:
        raise ValueError(f"unsupported provider adapter: {adapter}")
    adapter_id = "generic" if requested == "auto" else requested
    return AdapterResult(adapter_id=adapter_id, rows=[_canonicalize(dict(row)) for row in rows])
