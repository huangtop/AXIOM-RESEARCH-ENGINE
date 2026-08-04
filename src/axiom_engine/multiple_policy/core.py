from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping


METHOD_TO_ASSUMPTION = {
    "forward_pe": "target_forward_pe",
    "price_to_sales": "target_forward_ps",
    "ev_to_ebitda": "target_ev_ebitda",
    "price_to_book": "target_forward_pb",
}
CONFIDENCE = {"none": 0, "low": 1, "medium": 2, "high": 3}


def build_multiple_policy(
    root: Path,
    *,
    benchmark_path: str = "data/generated/historical_multiple_benchmark/historical_multiple_benchmark.json",
    company_snapshot_path: str = "data/generated/company/yahoo_company_snapshot.json",
    existing_policy_path: str = "data/knowledge/valuation_assumptions.json",
    minimum_confidence: str = "medium",
) -> dict[str, Any]:
    benchmark_file = root / benchmark_path
    payload = json.loads(benchmark_file.read_text(encoding="utf-8")) if benchmark_file.is_file() else {"schema_version": "historical-multiple-benchmark.v030.13.3", "benchmarks": []}
    if payload.get("schema_version") != "historical-multiple-benchmark.v030.13.3":
        raise ValueError("unsupported historical multiple benchmark")
    threshold = CONFIDENCE[minimum_confidence]
    companies: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    snapshot_file = root / company_snapshot_path
    snapshot = json.loads(snapshot_file.read_text(encoding="utf-8")) if snapshot_file.is_file() else {"symbols": {}}
    securities_file = root / "data/universe/securities.json"
    securities = json.loads(securities_file.read_text(encoding="utf-8")) if securities_file.is_file() else []
    company_by_symbol = {str(row.get("ticker") or "").upper(): str(row.get("company_id")) for row in securities if row.get("ticker") and row.get("company_id")}

    def number(value: Any) -> Decimal | None:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        return result if result.is_finite() else None

    for symbol, raw in (snapshot.get("symbols") or {}).items():
        if not isinstance(raw, Mapping) or not raw.get("analyst_count") or int(raw["analyst_count"]) <= 0:
            continue
        company_id = company_by_symbol.get(str(symbol).upper())
        target, eps, growth = number(raw.get("analyst_target_mean")), number(raw.get("forward_eps")), number(raw.get("forward_eps_growth"))
        if eps is not None and eps == number(raw.get("trailing_eps")):
            eps = None
        revenue, shares = number(raw.get("forward_revenue")), number(raw.get("shares_outstanding"))
        ebitda, debt, cash = number(raw.get("ebitda_ttm")), number(raw.get("total_debt")), number(raw.get("total_cash"))
        close, current_pb = number(raw.get("previous_close")), number(raw.get("price_to_book"))
        if not company_id or target is None or target <= 0:
            continue
        candidates = {
            "target_forward_pe": target / eps if eps and eps > 0 else None,
            "target_peg": target / eps / (growth * 100) if eps and eps > 0 and growth and growth > 0 else None,
            "target_forward_ps": target * shares / revenue if shares and shares > 0 and revenue and revenue > 0 else None,
            "target_ev_ebitda": (target * shares + debt - cash) / ebitda if shares and shares > 0 and ebitda and ebitda > 0 and debt is not None and cash is not None else None,
            "target_forward_pb": target / (close / current_pb) if close and close > 0 and current_pb and current_pb > 0 else None,
        }
        usable = {key: float(value) for key, value in candidates.items() if value is not None and value > 0}
        if not usable:
            continue
        evidence_id = f"yahoo-analyst-consensus:{str(symbol).upper()}:{raw.get('fetched_at') or raw.get('last_refresh')}"
        companies[company_id] = {"company_id": company_id, "policy_version": "analyst-consensus-implied-multiple.v031v.6", "evidence_ids": [evidence_id], "assumptions": usable}
    for row in payload.get("benchmarks", []):
        method = row.get("method")
        target = METHOD_TO_ASSUMPTION.get(str(method))
        value = (row.get("benchmark") or {}).get("target_multiple")
        if target is None or row.get("status") != "ready" or CONFIDENCE.get(str(row.get("confidence")), 0) < threshold or not isinstance(value, (int, float)) or value <= 0:
            rejected.append({"company_id": row.get("company_id"), "method": method, "reason": "benchmark_not_policy_eligible"})
            continue
        company_id = str(row["company_id"])
        company = companies.setdefault(company_id, {"company_id": company_id, "policy_version": "historical-median-multiple.v031v.6", "evidence_ids": [], "assumptions": {}})
        evidence_id = f"historical-multiple-benchmark:{company_id}:{method}:{row.get('selected_window')}:{row.get('latest_observation_date')}"
        company["evidence_ids"].append(evidence_id)
        company["assumptions"][target] = value
        company["policy_version"] = "historical-median-over-analyst-consensus.v031v.6"
    existing_file = root / existing_policy_path
    existing = json.loads(existing_file.read_text(encoding="utf-8")) if existing_file.is_file() else []
    if isinstance(existing, list):
        for row in existing:
            company_id = str(row.get("company_id") or "") if isinstance(row, Mapping) else ""
            if company_id and company_id not in companies:
                companies[company_id] = dict(row)
    return {
        "schema_version": "valuation-multiple-policy.v031v.6",
        "version": "V031V.6",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": benchmark_path,
        "policy": {"minimum_confidence": minimum_confidence, "primary": "historical_median", "fallback": "analyst_consensus_target_implied_multiple", "current_spot_multiple_as_target": "forbidden", "milestone_policy": "requires_separate_verified_event_evidence"},
        "companies": sorted(companies.values(), key=lambda row: row["company_id"]),
        "summary": {"company_count": len(companies), "assumption_count": sum(len(row["assumptions"]) for row in companies.values()), "rejected_count": len(rejected)},
        "diagnostics": {"rejected": rejected},
    }


def write_multiple_policy(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report["companies"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
