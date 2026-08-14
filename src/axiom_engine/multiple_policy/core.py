from __future__ import annotations

import json
import statistics
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


def _peer_assumptions(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Build cross-sectional peer medians for every classified operating company.

    A company's own observed multiple is never used in its target.  Sector peers
    are preferred, followed by theme peers and then the broader classified market
    when fewer than three valid peers exist.
    """
    overview_index = root / "data/generated/company_overview/index.json"
    coverage_index = root / "data/generated/full_market_coverage/full_market_coverage.json"
    if not overview_index.is_file() or not coverage_index.is_file():
        return {}, {"company_count": 0, "reason": "peer_inputs_unavailable"}
    overview = json.loads(overview_index.read_text(encoding="utf-8"))
    coverage = json.loads(coverage_index.read_text(encoding="utf-8"))
    ticker_files = overview.get("ticker_to_file") or {}
    coverage_files = (coverage.get("indexes") or {}).get("ticker_to_file") or {}
    profiles: dict[str, dict[str, Any]] = {}
    for ticker, card_file in coverage_files.items():
        filename = ticker_files.get(ticker)
        profile_path = overview_index.parent / str(filename) if filename else None
        if profile_path is not None and not profile_path.is_file():
            profile_path = overview_index.parent / "per-company" / str(filename)
        card_path = coverage_index.parent / str(card_file)
        if not card_path.is_file():
            continue
        profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path is not None and profile_path.is_file() else {}
        path = profile.get("path") or {}
        theme = str(((path.get("theme") or {}).get("id") or "theme:unclassified"))
        sector = str(((path.get("sector") or {}).get("id") or "sector:unclassified"))
        card = json.loads(card_path.read_text(encoding="utf-8"))
        company_id = str(card.get("company_id") or (card.get("company") or {}).get("company_id") or "")
        if not company_id:
            continue
        profiles[company_id] = {
            "ticker": ticker,
            "theme": theme,
            "sector": sector,
            "card": card,
        }

    def value(layer: Mapping[str, Any], key: str) -> float | None:
        try:
            result = float(((layer.get(key) or {}).get("value")))
        except (TypeError, ValueError):
            return None
        return result if result > 0 else None

    observed: dict[str, dict[str, float]] = {}
    bounds = {
        "target_forward_pe": (1.0, 250.0),
        "target_peg": (0.05, 5.0),
        "target_forward_ps": (0.05, 100.0),
        "target_ev_ebitda": (0.5, 100.0),
        "target_forward_pb": (0.1, 100.0),
    }
    for company_id, profile in profiles.items():
        card = profile["card"]
        market, fin, est = card.get("market") or {}, card.get("financials") or {}, card.get("estimates") or {}
        try:
            price = float(market.get("current_price"))
        except (TypeError, ValueError):
            continue
        eps, growth = value(est, "forward_eps"), value(est, "forward_eps_growth")
        revenue, ebitda = value(est, "forward_revenue"), value(est, "forward_ebitda") or value(est, "ebitda_ttm")
        shares, cash, debt = value(fin, "diluted_shares_outstanding"), value(fin, "cash_and_cash_equivalents"), value(fin, "total_debt")
        bvps = value(fin, "book_value_per_share")
        candidates: dict[str, float] = {}
        if eps:
            candidates["target_forward_pe"] = price / eps
            if growth:
                candidates["target_peg"] = price / eps / (growth * 100.0)
        if shares and revenue:
            candidates["target_forward_ps"] = price * shares / revenue
        if shares and ebitda and cash is not None and debt is not None:
            candidates["target_ev_ebitda"] = (price * shares + debt - cash) / ebitda
        if bvps:
            candidates["target_forward_pb"] = price / bvps
        observed[company_id] = {
            key: number for key, number in candidates.items()
            if bounds[key][0] <= number <= bounds[key][1]
        }

    output: dict[str, dict[str, Any]] = {}
    method_counts: dict[str, int] = {key: 0 for key in bounds}
    for company_id, profile in profiles.items():
        assumptions: dict[str, float] = {}
        evidence_ids: list[str] = []
        for key in bounds:
            sector_peers = [
                values[key] for peer_id, values in observed.items()
                if peer_id != company_id and profiles[peer_id]["sector"] == profile["sector"] and key in values
            ]
            theme_peers = [
                values[key] for peer_id, values in observed.items()
                if peer_id != company_id and profiles[peer_id]["theme"] == profile["theme"] and key in values
            ]
            if profile["sector"] != "sector:unclassified" and len(sector_peers) >= 3:
                peers, scope = sector_peers, profile["sector"]
            elif profile["theme"] != "theme:unclassified" and len(theme_peers) >= 3:
                peers, scope = theme_peers, profile["theme"]
            else:
                peers = [values[key] for peer_id, values in observed.items() if peer_id != company_id and key in values]
                scope = "operating-market"
            if len(peers) < 3:
                continue
            assumptions[key] = statistics.median(peers)
            evidence_ids.append(f"peer-median:{scope}:{key}:n{len(peers)}")
            method_counts[key] += 1
        if assumptions:
            output[company_id] = {
                "company_id": company_id,
                "policy_version": "classified-peer-cross-sectional-median.v031v.9",
                "evidence_ids": evidence_ids,
                "assumptions": assumptions,
            }
    return output, {
        "company_count": len(profiles),
        "policy_company_count": len(output),
        "observed_company_count": len(observed),
        "assumption_company_counts": method_counts,
    }


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
    companies, peer_summary = _peer_assumptions(root)
    existing_file = root / existing_policy_path
    existing = json.loads(existing_file.read_text(encoding="utf-8")) if existing_file.is_file() else []
    for prior in existing:
        company_id = str(prior.get("company_id") or "")
        assumptions = prior.get("assumptions") or {}
        if not company_id or not assumptions:
            continue
        company = companies.setdefault(company_id, {
            "company_id": company_id,
            "policy_version": str(prior.get("policy_version") or "preserved-existing-policy.v031v.9"),
            "evidence_ids": list(prior.get("evidence_ids") or []),
            "assumptions": {},
        })
        # A refresh fills missing keys; it never silently rewrites an already
        # published target multiple merely because today's stock price moved.
        company["assumptions"].update(assumptions)
        company["evidence_ids"] = sorted(set(company.get("evidence_ids") or []) | set(prior.get("evidence_ids") or []))
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

    def positive(value: Any) -> Decimal | None:
        result = number(value)
        return result if result is not None and result > 0 else None

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

    # Market roll-forward is the production default used by the original
    # valuation module: apply the subject company's observable Yahoo multiple
    # to forward fundamentals.  These are market-anchored scenarios, not an
    # analyst target-price reverse engineering.  PEG, DCF, and milestone remain
    # independent and are intentionally not populated here.
    snapshot_file = root / company_snapshot_path
    snapshot_payload = json.loads(snapshot_file.read_text(encoding="utf-8")) if snapshot_file.is_file() else {}
    roll_forward_bounds = {
        "target_forward_pe": (1.0, 500.0),
        "target_forward_ps": (0.05, 100.0),
        "target_ev_ebitda": (0.5, 250.0),
        "target_forward_pb": (0.1, 100.0),
    }
    market_roll_forward_count = 0
    for symbol, snapshot in (snapshot_payload.get("symbols") or {}).items():
        if not isinstance(snapshot, Mapping):
            continue
        company_id = company_by_symbol.get(str(symbol).upper())
        if not company_id:
            continue
        price = positive(snapshot.get("previous_close"))
        shares = positive(snapshot.get("shares_outstanding"))
        revenue_ttm = positive(snapshot.get("revenue_ttm"))
        forward_eps = positive(snapshot.get("forward_eps"))
        analyst_target = positive(snapshot.get("analyst_target_mean"))
        consensus_target_pe = analyst_target / forward_eps if analyst_target and forward_eps else None
        observed = {
            # The legacy module's Target P/E is Yahoo consensus target divided
            # by forward EPS.  Falling back to trailing P/E preserves a market
            # roll-forward when consensus is unavailable.
            "target_forward_pe": consensus_target_pe or positive(snapshot.get("trailing_pe")),
            "target_forward_ps": (price * shares / revenue_ttm) if price and shares and revenue_ttm else None,
            "target_ev_ebitda": positive(snapshot.get("enterprise_to_ebitda")),
            "target_forward_pb": positive(snapshot.get("price_to_book")),
        }
        bounded = {
            key: float(value)
            for key, value in observed.items()
            if value is not None and roll_forward_bounds[key][0] <= float(value) <= roll_forward_bounds[key][1]
        }
        if not bounded:
            continue
        company = companies.setdefault(company_id, {
            "company_id": company_id,
            "policy_version": "yahoo-market-roll-forward.v031v.10",
            "evidence_ids": [],
            "assumptions": {},
        })
        company["assumptions"].update(bounded)
        fetched_at = str(snapshot.get("fetched_at") or snapshot.get("last_refresh") or "undated")
        company["evidence_ids"] = sorted(set(company.get("evidence_ids") or []) | {
            f"yahoo-market-multiple:{str(symbol).upper()}:{key}:{fetched_at}"
            for key in bounded
        })
        company["policy_version"] = "yahoo-consensus-and-market-roll-forward.v031v.10"
        market_roll_forward_count += 1
    return {
        "schema_version": "valuation-multiple-policy.v031v.6",
        "version": "V031V.6",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": benchmark_path,
        "policy": {"minimum_confidence": minimum_confidence, "primary": "yahoo_consensus_pe_and_subject_market_multiple_roll_forward", "fallback": "historical_then_classified_peer_median", "analyst_target_as_multiple_source": "allowed_for_forward_pe_consensus_scenario_only", "current_spot_multiple_as_target": "allowed_for_explicit_market_roll_forward_models", "own_current_spot_multiple_as_target": "allowed_with_yahoo_observation_provenance", "peer_current_multiple_policy": "fallback_only_exclude_subject_company_and_require_at_least_three_peers", "peg_policy": "independent_classified_peer_profile_median", "milestone_policy": "requires_separate_verified_event_evidence"},
        "companies": sorted(companies.values(), key=lambda row: row["company_id"]),
        "summary": {"company_count": len(companies), "assumption_count": sum(len(row["assumptions"]) for row in companies.values()), "market_roll_forward_company_count": market_roll_forward_count, "rejected_count": len(rejected), "ai_peer_policy": peer_summary},
        "diagnostics": {"rejected": rejected},
    }


def write_multiple_policy(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report["companies"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
