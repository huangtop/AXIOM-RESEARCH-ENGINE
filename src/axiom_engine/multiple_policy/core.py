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
    securities_file = root / "data/universe/securities.json"
    securities = json.loads(securities_file.read_text(encoding="utf-8")) if securities_file.is_file() else []
    company_by_symbol = {str(row.get("ticker") or "").upper(): str(row.get("company_id")) for row in securities if row.get("ticker") and row.get("company_id")}

    def number(value: Any) -> Decimal | None:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        return result if result.is_finite() else None

    # Preserve explicit company/scenario assumptions as independent model inputs.
    # Analyst target prices are deliberately excluded: reverse-engineering one
    # target into several multiples forces those models to return the same value.
    scenario_file = root / "data/valuation/valuation_scenarios.json"
    assumption_file = root / "data/valuation/valuation_assumptions.json"
    scenarios = json.loads(scenario_file.read_text(encoding="utf-8")) if scenario_file.is_file() else []
    scenario_company = {
        str(row.get("scenario_id")): str(row.get("company_id"))
        for row in scenarios
        if row.get("scenario_type") == "base"
    }
    key_map = {
        "target_pe": "target_forward_pe",
        "target_peg": "target_peg",
        "target_ps": "target_forward_ps",
        "target_pb": "target_forward_pb",
        "target_ev_ebitda": "target_ev_ebitda",
    }
    explicit = json.loads(assumption_file.read_text(encoding="utf-8")) if assumption_file.is_file() else []
    for row in explicit:
        target_key = key_map.get(str(row.get("key") or ""))
        legacy_company_id = scenario_company.get(str(row.get("scenario_id") or ""))
        symbol = str(legacy_company_id or "").rsplit("-", 1)[-1].upper()
        company_id = company_by_symbol.get(symbol)
        value = number(row.get("value"))
        if not target_key or not company_id or value is None or value <= 0:
            continue
        company = companies.setdefault(company_id, {
            "company_id": company_id,
            "policy_version": "explicit-base-scenario.v031v.7",
            "evidence_ids": [],
            "assumptions": {},
        })
        company["assumptions"][target_key] = float(value)
        company["evidence_ids"].extend(str(value) for value in row.get("source_ref_ids") or [])
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
            if company_id and company_id not in companies and row.get("policy_version") != "analyst-consensus-implied-multiple.v031v.6":
                companies[company_id] = dict(row)
    return {
        "schema_version": "valuation-multiple-policy.v031v.6",
        "version": "V031V.6",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": benchmark_path,
        "policy": {"minimum_confidence": minimum_confidence, "primary": "historical_median", "fallback": "explicit_company_base_scenario_only", "analyst_target_as_multiple_source": "forbidden", "current_spot_multiple_as_target": "forbidden", "peg_policy": "requires_independent_company_or_profile_evidence", "milestone_policy": "requires_separate_verified_event_evidence"},
        "companies": sorted(companies.values(), key=lambda row: row["company_id"]),
        "summary": {"company_count": len(companies), "assumption_count": sum(len(row["assumptions"]) for row in companies.values()), "rejected_count": len(rejected)},
        "diagnostics": {"rejected": rejected},
    }


def write_multiple_policy(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report["companies"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
