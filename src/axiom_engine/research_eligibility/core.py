from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class ResearchEligibilityError(RuntimeError):
    pass


FORBIDDEN_MEMBERSHIP_KEYS = {"ticker", "tickers", "symbol", "symbols", "company_id", "company_ids"}


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchEligibilityError(f"cannot read {path}: {exc}") from exc


def _validate_policy(policy: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != "research-eligibility-policy.v031c.4":
        raise ResearchEligibilityError("unsupported research eligibility policy")
    serialized = json.dumps(policy)
    for key in FORBIDDEN_MEMBERSHIP_KEYS:
        if f'"{key}"' in serialized:
            raise ResearchEligibilityError("ticker/company membership is forbidden in eligibility policy")
    if int((policy.get("research_universe") or {}).get("maximum_selected_companies") or 0) < 1:
        raise ResearchEligibilityError("maximum_selected_companies must be positive")


def _max_score(knowledge: list[Mapping[str, Any]], dimension: str) -> float:
    return max((float(item.get("confidence") or 0) for item in knowledge if item.get("dimension") == dimension), default=0.0)


def _decision(qualified: bool, met_reason: str, unmet_reasons: list[str]) -> dict[str, Any]:
    return {
        "qualified": qualified,
        "enabled": False,
        "reason_code": met_reason if qualified else unmet_reasons[0],
        "unmet_reason_codes": [] if qualified else unmet_reasons,
    }


def build_research_eligibility(
    root: Path,
    *,
    policy_path: str = "config/research_eligibility.v031c.4.json",
    knowledge_path: str = "data/generated/knowledge_inference/knowledge_inference.json",
    securities_path: str = "data/universe/securities.json",
    identity_path: str = "data/generated/security_identity/security_identity_normalization.json",
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    policy = _load(root / policy_path)
    knowledge_payload = _load(root / knowledge_path)
    securities = _load(root / securities_path)
    identity = _load(root / identity_path)
    _validate_policy(policy)
    if knowledge_payload.get("schema_version") != "multidimensional-knowledge-inference.v031c.3":
        raise ResearchEligibilityError("V031C.3 knowledge inference input is required")
    if not isinstance(securities, list) or not isinstance(identity.get("companies"), list):
        raise ResearchEligibilityError("security identity inputs are invalid")

    primary_ticker: dict[str, str] = {}
    for security in securities:
        company_id = str(security.get("company_id") or "")
        if security.get("primary_listing") is True or company_id not in primary_ticker:
            primary_ticker[company_id] = str(security.get("ticker") or "").upper()
    listed = {
        str(row.get("company_id")): row.get("valuation_scope_status") == "included"
        for row in identity["companies"] if row.get("company_id")
    }
    weights = policy["score_weights"]
    thresholds = policy["decisions"]
    records: list[dict[str, Any]] = []
    for source in knowledge_payload["records"]:
        company_id = str(source["company_id"])
        knowledge = list(source.get("knowledge") or [])
        scores = {dimension: _max_score(knowledge, dimension) for dimension in ("theme", "sector", "cluster", "supply_chain_role")}
        evidence_ids = sorted({value for item in knowledge for value in item.get("source_business_evidence_ids") or []})
        source_signal_ids = sorted({value for item in knowledge for value in item.get("source_signal_ids") or []})
        inferred_dimensions = {str(item["dimension"]) for item in knowledge if item.get("derivation_type") == "rule_inference"}
        breadth = min(1.0, len(evidence_ids) / 5.0)
        research_score = round(
            scores["theme"] * float(weights["theme"])
            + scores["sector"] * float(weights["sector"])
            + scores["cluster"] * float(weights["cluster"])
            + scores["supply_chain_role"] * float(weights["supply_chain_role"])
            + breadth * float(weights["evidence_breadth"]), 4
        )

        news_missing = []
        if scores["theme"] < float(thresholds["news"]["minimum_theme_score"]): news_missing.append("THEME_SCORE_BELOW_THRESHOLD")
        if scores["sector"] < float(thresholds["news"]["minimum_sector_score"]): news_missing.append("SECTOR_SCORE_BELOW_THRESHOLD")
        etf_missing = []
        if scores["theme"] < float(thresholds["etf"]["minimum_theme_score"]): etf_missing.append("THEME_SCORE_BELOW_THRESHOLD")
        if scores["sector"] < float(thresholds["etf"]["minimum_sector_score"]): etf_missing.append("SECTOR_SCORE_BELOW_THRESHOLD")
        if thresholds["etf"].get("requires_active_common_equity") and not listed.get(company_id, False): etf_missing.append("ACTIVE_COMMON_EQUITY_UNAVAILABLE")
        chain_missing = []
        if scores["theme"] < float(thresholds["supply_chain"]["minimum_theme_score"]): chain_missing.append("THEME_SCORE_BELOW_THRESHOLD")
        if scores["sector"] < float(thresholds["supply_chain"]["minimum_sector_score"]): chain_missing.append("SECTOR_SCORE_BELOW_THRESHOLD")
        if max(scores["supply_chain_role"], scores["cluster"]) < float(thresholds["supply_chain"]["minimum_role_or_cluster_score"]): chain_missing.append("ROLE_OR_CLUSTER_SCORE_BELOW_THRESHOLD")
        deep_missing = []
        deep_policy = thresholds["deep_research"]
        if scores["theme"] < float(deep_policy["minimum_theme_score"]): deep_missing.append("THEME_SCORE_BELOW_THRESHOLD")
        if scores["sector"] < float(deep_policy["minimum_sector_score"]): deep_missing.append("SECTOR_SCORE_BELOW_THRESHOLD")
        if scores["cluster"] < float(deep_policy["minimum_cluster_score"]): deep_missing.append("CLUSTER_SCORE_BELOW_THRESHOLD")
        if len(evidence_ids) < int(deep_policy["minimum_evidence_count"]): deep_missing.append("EVIDENCE_COUNT_BELOW_THRESHOLD")
        if len(source_signal_ids) < int(deep_policy["minimum_source_signal_count"]): deep_missing.append("SOURCE_SIGNAL_COUNT_BELOW_THRESHOLD")
        if len(inferred_dimensions) < int(deep_policy["minimum_derived_dimensions"]): deep_missing.append("DERIVED_DIMENSION_COUNT_BELOW_THRESHOLD")
        decisions = {
            "news": _decision(not news_missing, "THEME_EVIDENCE_QUALIFIED", news_missing),
            "etf": _decision(not etf_missing, "THEME_AND_SECURITY_IDENTITY_QUALIFIED", etf_missing),
            "supply_chain": _decision(not chain_missing, "THEME_AND_CHAIN_EVIDENCE_QUALIFIED", chain_missing),
            "deep_research": _decision(not deep_missing, "MULTIDIMENSIONAL_EVIDENCE_QUALIFIED", deep_missing),
        }
        records.append({
            "company_id": company_id,
            "ticker": primary_ticker.get(company_id) or None,
            "knowledge_status": source["status"],
            "research_score": research_score,
            "score_components": {**scores, "evidence_breadth": breadth},
            "evidence_summary": {"business_evidence_ids": evidence_ids, "source_signal_ids": source_signal_ids, "derived_dimensions": sorted(inferred_dimensions)},
            "decisions": decisions,
        })

    candidates = sorted(
        (row for row in records if any(item["qualified"] for item in row["decisions"].values())),
        key=lambda row: (-row["research_score"], row["company_id"]),
    )
    maximum = int(policy["research_universe"]["maximum_selected_companies"])
    selected_ids = {row["company_id"] for row in candidates[:maximum]}
    for row in records:
        selected = row["company_id"] in selected_ids
        qualified = any(item["qualified"] for item in row["decisions"].values())
        row["research_universe_status"] = "selected" if selected else "eligible_not_selected" if qualified else "not_eligible"
        for decision in row["decisions"].values():
            decision["enabled"] = bool(decision["qualified"] and selected)
            if decision["qualified"] and not selected:
                decision["reason_code"] = "RESEARCH_UNIVERSE_RANK_LIMIT_EXCEEDED"

    action_counts = Counter()
    qualified_counts = Counter()
    for row in records:
        for action, decision in row["decisions"].items():
            qualified_counts[action] += int(decision["qualified"])
            action_counts[action] += int(decision["enabled"])
    return {
        "schema_version": "research-eligibility.v031c.4",
        "version": "V031C.4",
        "generated_at": current.isoformat(),
        "summary": {
            "company_count": len(records),
            "eligible_company_count": len(candidates),
            "selected_research_company_count": len(selected_ids),
            "qualified_action_counts": dict(sorted(qualified_counts.items())),
            "enabled_action_counts": dict(sorted(action_counts.items())),
        },
        "policy": {"policy_path": policy_path, "contains_ticker_membership": False, "valuation_readiness_consumed": False},
        "records": records,
        "indexes": {
            "company_id_to_position": {row["company_id"]: index for index, row in enumerate(records)},
            "ticker_to_position": {row["ticker"]: index for index, row in enumerate(records) if row["ticker"]},
        },
    }


def write_research_eligibility(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
