from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping


FIELD_METRICS = {
    "forward_eps": ("forward_eps", "USD/share"),
    "forward_eps_growth": ("forward_eps_growth", "ratio"),
    "forward_revenue": ("forward_revenue", "currency"),
    "ebitda_ttm": ("ebitda_ttm", "currency"),
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _number(value: Any) -> str | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return format(number, "f") if number.is_finite() else None


def _per_share_inputs_are_consistent(raw: Mapping[str, Any]) -> bool:
    try:
        market_cap = Decimal(str(raw.get("market_cap")))
        shares = Decimal(str(raw.get("shares_outstanding")))
        forward_eps = Decimal(str(raw.get("forward_eps")))
        forward_pe = Decimal(str(raw.get("forward_pe")))
    except (InvalidOperation, TypeError, ValueError):
        return True
    if min(market_cap, shares, forward_eps, forward_pe) <= 0:
        return True
    ratio = (market_cap / shares) / (forward_eps * forward_pe)
    return Decimal("0.50") <= ratio <= Decimal("2.00")


def build_estimate_population(
    root: Path,
    *,
    snapshot_path: str = "data/generated/company/yahoo_company_snapshot.json",
    securities_path: str = "data/universe/securities.json",
    existing_path: str = "data/estimate_data/consensus_estimates.json",
) -> dict[str, Any]:
    snapshot = _load(root / snapshot_path)
    securities = _load(root / securities_path)
    symbols = snapshot.get("symbols") if isinstance(snapshot, Mapping) else None
    if not isinstance(symbols, Mapping) or not isinstance(securities, list):
        raise ValueError("Yahoo snapshot symbols and Registry securities are required")
    identity = {
        str(row.get("ticker") or "").upper(): (row.get("company_id"), row.get("security_id"))
        for row in securities if row.get("ticker")
    }
    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    observed_keys: set[tuple[str, str]] = set()
    for symbol, raw in sorted(symbols.items()):
        if not isinstance(raw, Mapping) or str(symbol).upper() not in identity:
            rejected.append({"symbol": str(symbol), "reason": "registry_identity_not_found"})
            continue
        company_id, security_id = identity[str(symbol).upper()]
        observed_at = raw.get("fetched_at") or raw.get("last_refresh")
        per_share_consistent = _per_share_inputs_are_consistent(raw)
        for field, (metric, unit) in FIELD_METRICS.items():
            observed_keys.add((str(company_id), metric))
            value = _number(raw.get(field))
            if field == "forward_eps" and value is not None and value == _number(raw.get("trailing_eps")):
                value = None
            if field in {"forward_eps", "forward_eps_growth"} and not per_share_consistent:
                value = None
                rejected.append({"symbol": str(symbol).upper(), "reason": f"{field}_per_share_basis_inconsistent"})
            if field == "forward_eps_growth" and value is not None and Decimal(value) > Decimal("1"):
                value = None
                rejected.append({"symbol": str(symbol).upper(), "reason": "forward_eps_growth_above_sustainable_peg_bound"})
            if value is None:
                continue
            record_key = f"{company_id}|{metric}|{observed_at}|yahoo_finance"
            rows.append({
                "estimate_id": "estimate:" + hashlib.sha256(record_key.encode()).hexdigest()[:24],
                "company_id": company_id,
                "security_id": security_id,
                "ticker": str(symbol).upper(),
                "metric": metric,
                "value": value,
                "unit": raw.get("currency") if unit == "currency" else unit,
                "currency": raw.get("currency"),
                "fiscal_period": "Forward",
                "as_of_date": observed_at,
                "provider": "yahoo_finance",
                "source_record_id": f"yahoo-company-snapshot:{str(symbol).upper()}:{observed_at}",
                "source_path": snapshot_path,
                "record_state": "provider_observation",
            })
    existing_file = root / existing_path
    existing = _load(existing_file) if existing_file.is_file() else []
    if isinstance(existing, list):
        rows.extend(
            row for row in existing
            if isinstance(row, Mapping)
            and (str(row.get("company_id")), str(row.get("metric"))) not in observed_keys
        )
    rows.sort(key=lambda row: (str(row["company_id"]), str(row["metric"]), str(row.get("as_of_date") or "")))
    return {
        "schema_version": "canonical-estimate-population.v031v.6",
        "version": "V031V.6",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "estimates": rows,
        "summary": {"estimate_count": len(rows), "company_count": len({row["company_id"] for row in rows}), "metric_counts": {metric: sum(row["metric"] == metric for row in rows) for metric, _ in FIELD_METRICS.values()}, "rejected_symbol_count": len(rejected)},
        "diagnostics": {"rejected_symbols": rejected},
    }


def write_estimate_population(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report["estimates"], ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
