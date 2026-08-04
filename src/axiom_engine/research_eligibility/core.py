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
            raise ResearchEligibilityError(
                "ticker/company membership is forbidden in eligibility policy"
            )
    universe = policy.get("research_universe") or {}
    if universe.get("selection_mode") != "evidence_ranked_actions":
        raise ResearchEligibilityError("research universe must use evidence-ranked actions")


def _validate_theme_catalog(catalog: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if catalog.get("schema_version") != "research-theme-catalog.v031c.5.1":
        raise ResearchEligibilityError("unsupported research theme catalog")
    serialized = json.dumps(catalog)
    for key in FORBIDDEN_MEMBERSHIP_KEYS:
        if f'"{key}"' in serialized:
            raise ResearchEligibilityError(
                "ticker/company membership is forbidden in theme catalog"
            )
    themes = catalog.get("themes")
    if not isinstance(themes, list):
        raise ResearchEligibilityError("theme catalog themes must be an array")
    ids: set[str] = set()
    for theme in themes:
        theme_id = str(theme.get("theme_id") or "")
        if not theme_id or theme_id in ids or not isinstance(theme.get("actions"), Mapping):
            raise ResearchEligibilityError(f"invalid or duplicate catalog theme: {theme_id}")
        ids.add(theme_id)
    limits = catalog.get("tier_limits") or {}
    if any(int(limits.get(key) or 0) < 1 for key in ("active_intelligence", "supply_chain")):
        raise ResearchEligibilityError("theme catalog tier limits must be positive")
    minimum_scores = catalog.get("tier_minimum_scores") or {}
    if any(
        not 0 <= float(minimum_scores.get(key, -1)) <= 1
        for key in ("active_intelligence", "supply_chain", "deep_research")
    ):
        raise ResearchEligibilityError(
            "theme catalog tier minimum scores must be between zero and one"
        )
    return themes


def _event_triggers(root: Path) -> dict[str, list[dict[str, str]]]:
    sources = (
        ("sec_filing", root / "data/generated/sec_filing_refresh/refresh_plan.json", "worklist"),
        ("news", root / "data/generated/research_events/news_events.json", "events"),
        ("etf_change", root / "data/generated/canonical_etf_change_events/events.json", "events"),
    )
    triggers: dict[str, list[dict[str, str]]] = {}
    for event_type, path, field in sources:
        if not path.is_file():
            continue
        payload = _load(path)
        rows = payload.get(field) if isinstance(payload, Mapping) else []
        for row in rows or []:
            company_id = str(row.get("company_id") or "")
            if not company_id:
                continue
            trigger_id = str(
                row.get("event_id")
                or row.get("accession_number")
                or (row.get("latest_financial_filing") or {}).get("accession_number")
                or f"{event_type}:{company_id}"
            )
            triggers.setdefault(company_id, []).append(
                {"trigger_type": event_type, "trigger_id": trigger_id}
            )
    return triggers


def _catalog_matches(
    knowledge_ids: set[str], themes: list[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    matches = []
    for theme in themes:
        if theme["theme_id"] not in knowledge_ids:
            continue
        required = set(theme.get("required_any_knowledge") or [])
        if required and not required.intersection(knowledge_ids):
            continue
        matches.append(theme)
    return matches


def _max_score(knowledge: list[Mapping[str, Any]], dimension: str) -> float:
    return max(
        (
            float(item.get("confidence") or 0)
            for item in knowledge
            if item.get("dimension") == dimension
        ),
        default=0.0,
    )


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
    relevance_gate_path: str = "data/generated/research_relevance_gate/research_relevance_gate.json",
    theme_catalog_path: str = "config/research_theme_catalog.v031c.5.1.json",
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    policy = _load(root / policy_path)
    knowledge_payload = _load(root / knowledge_path)
    securities = _load(root / securities_path)
    identity = _load(root / identity_path)
    theme_catalog = _load(root / theme_catalog_path)
    gate_file = root / relevance_gate_path
    gate_payload = _load(gate_file) if gate_file.is_file() else {"records": []}
    gate_by_company = {
        str(row["company_id"]): row
        for row in gate_payload.get("records") or []
        if row.get("company_id")
    }
    _validate_policy(policy)
    catalog_themes = _validate_theme_catalog(theme_catalog)
    event_triggers = _event_triggers(root)
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
        for row in identity["companies"]
        if row.get("company_id")
    }
    weights = policy["score_weights"]
    thresholds = policy["decisions"]
    records: list[dict[str, Any]] = []
    for source in knowledge_payload["records"]:
        company_id = str(source["company_id"])
        knowledge = list(source.get("knowledge") or [])
        scores = {
            dimension: _max_score(knowledge, dimension)
            for dimension in ("theme", "sector", "cluster", "product", "supply_chain_role")
        }
        evidence_ids = sorted(
            {
                value
                for item in knowledge
                for value in item.get("source_business_evidence_ids") or []
            }
        )
        source_signal_ids = sorted(
            {value for item in knowledge for value in item.get("source_signal_ids") or []}
        )
        inferred_dimensions = {
            str(item["dimension"])
            for item in knowledge
            if item.get("derivation_type") == "rule_inference"
        }
        knowledge_ids = {str(item.get("knowledge_id")) for item in knowledge}
        matched_catalog_themes = _catalog_matches(knowledge_ids, catalog_themes)
        allowed_actions = {
            action: any(
                bool((theme.get("actions") or {}).get(action)) for theme in matched_catalog_themes
            )
            for action in ("news", "etf", "supply_chain", "deep_research")
        }
        catalog_priority = max(
            (float(theme.get("priority") or 0) for theme in matched_catalog_themes), default=0.0
        )
        gate = gate_by_company.get(company_id)
        research_irrelevant = bool(gate and gate.get("deep_inference_required") is False)
        breadth = min(1.0, len(evidence_ids) / 5.0)
        research_score = round(
            scores["theme"] * float(weights["theme"])
            + scores["sector"] * float(weights["sector"])
            + scores["cluster"] * float(weights["cluster"])
            + scores["supply_chain_role"] * float(weights["supply_chain_role"])
            + breadth * float(weights["evidence_breadth"]),
            4,
        )
        tier_rank_score = round(research_score * (0.8 + 0.2 * catalog_priority), 4)

        news_missing = []
        if not allowed_actions["news"]:
            news_missing.append("NO_ENABLED_CATALOG_THEME")
        if scores["theme"] < float(thresholds["news"]["minimum_theme_score"]):
            news_missing.append("THEME_SCORE_BELOW_THRESHOLD")
        if scores["sector"] < float(thresholds["news"]["minimum_sector_score"]):
            news_missing.append("SECTOR_SCORE_BELOW_THRESHOLD")
        etf_missing = []
        if not allowed_actions["etf"]:
            etf_missing.append("NO_ENABLED_CATALOG_THEME")
        if scores["theme"] < float(thresholds["etf"]["minimum_theme_score"]):
            etf_missing.append("THEME_SCORE_BELOW_THRESHOLD")
        if scores["sector"] < float(thresholds["etf"]["minimum_sector_score"]):
            etf_missing.append("SECTOR_SCORE_BELOW_THRESHOLD")
        if thresholds["etf"].get("requires_active_common_equity") and not listed.get(
            company_id, False
        ):
            etf_missing.append("ACTIVE_COMMON_EQUITY_UNAVAILABLE")
        chain_missing = []
        if not allowed_actions["supply_chain"]:
            chain_missing.append("NO_ENABLED_CATALOG_THEME")
        if scores["theme"] < float(thresholds["supply_chain"]["minimum_theme_score"]):
            chain_missing.append("THEME_SCORE_BELOW_THRESHOLD")
        if scores["sector"] < float(thresholds["supply_chain"]["minimum_sector_score"]):
            chain_missing.append("SECTOR_SCORE_BELOW_THRESHOLD")
        if max(scores["supply_chain_role"], scores["cluster"], scores["product"]) < float(
            thresholds["supply_chain"]["minimum_role_or_cluster_score"]
        ):
            chain_missing.append("ROLE_CLUSTER_OR_PRODUCT_SCORE_BELOW_THRESHOLD")
        deep_missing = []
        if not allowed_actions["deep_research"]:
            deep_missing.append("NO_ENABLED_CATALOG_THEME")
        deep_policy = thresholds["deep_research"]
        if scores["theme"] < float(deep_policy["minimum_theme_score"]):
            deep_missing.append("THEME_SCORE_BELOW_THRESHOLD")
        if scores["sector"] < float(deep_policy["minimum_sector_score"]):
            deep_missing.append("SECTOR_SCORE_BELOW_THRESHOLD")
        if scores["cluster"] < float(deep_policy["minimum_cluster_score"]):
            deep_missing.append("CLUSTER_SCORE_BELOW_THRESHOLD")
        if len(evidence_ids) < int(deep_policy["minimum_evidence_count"]):
            deep_missing.append("EVIDENCE_COUNT_BELOW_THRESHOLD")
        if len(source_signal_ids) < int(deep_policy["minimum_source_signal_count"]):
            deep_missing.append("SOURCE_SIGNAL_COUNT_BELOW_THRESHOLD")
        if len(inferred_dimensions) < int(deep_policy["minimum_derived_dimensions"]):
            deep_missing.append("DERIVED_DIMENSION_COUNT_BELOW_THRESHOLD")
        decisions = {
            "news": _decision(not news_missing, "THEME_EVIDENCE_QUALIFIED", news_missing),
            "etf": _decision(not etf_missing, "THEME_AND_SECURITY_IDENTITY_QUALIFIED", etf_missing),
            "supply_chain": _decision(
                not chain_missing, "THEME_AND_CHAIN_EVIDENCE_QUALIFIED", chain_missing
            ),
            "deep_research": _decision(
                not deep_missing, "MULTIDIMENSIONAL_EVIDENCE_QUALIFIED", deep_missing
            ),
        }
        if research_irrelevant:
            decisions = {
                action: _decision(False, "", ["RESEARCH_RELEVANCE_GATE_EXCLUDED"])
                for action in decisions
            }
        elif not listed.get(company_id, False):
            decisions = {
                action: _decision(False, "", ["OPERATING_COMPANY_COMMON_EQUITY_REQUIRED"])
                for action in decisions
            }
        records.append(
            {
                "company_id": company_id,
                "ticker": primary_ticker.get(company_id) or None,
                "knowledge_status": source["status"],
                "research_relevance": {
                    "status": (gate or {}).get("status"),
                    "upper_category": (gate or {}).get("upper_category"),
                    "reason_code": (gate or {}).get("reason_code"),
                },
                "instrument_scope": {
                    "operating_company_common_equity": bool(listed.get(company_id, False)),
                    "reason_code": "OPERATING_COMPANY_COMMON_EQUITY"
                    if listed.get(company_id, False)
                    else "NON_COMPANY_OR_NON_COMMON_EQUITY_EXCLUDED",
                },
                "research_score": research_score,
                "catalog_priority": catalog_priority,
                "tier_rank_score": tier_rank_score,
                "matched_catalog_theme_ids": sorted(
                    str(theme["theme_id"]) for theme in matched_catalog_themes
                ),
                "score_components": {**scores, "evidence_breadth": breadth},
                "evidence_summary": {
                    "business_evidence_ids": evidence_ids,
                    "source_signal_ids": source_signal_ids,
                    "derived_dimensions": sorted(inferred_dimensions),
                },
                "decisions": decisions,
                "deep_research_triggers": event_triggers.get(company_id, []),
            }
        )

    candidates = [
        row for row in records if any(item["qualified"] for item in row["decisions"].values())
    ]
    def rank_key(row: Mapping[str, Any]) -> tuple[float, float, str]:
        return (
            -float(row["tier_rank_score"]),
            -float(row["research_score"]),
            str(row["company_id"]),
        )
    limits = theme_catalog["tier_limits"]
    minimum_scores = theme_catalog["tier_minimum_scores"]
    active_candidates = sorted(
        (
            row
            for row in records
            if (row["decisions"]["news"]["qualified"] or row["decisions"]["etf"]["qualified"])
            and float(row["research_score"]) >= float(minimum_scores["active_intelligence"])
        ),
        key=rank_key,
    )
    chain_candidates = sorted(
        (
            row
            for row in records
            if row["decisions"]["supply_chain"]["qualified"]
            and float(row["research_score"]) >= float(minimum_scores["supply_chain"])
        ),
        key=rank_key,
    )
    deep_candidates = sorted(
        (
            row
            for row in records
            if row["decisions"]["deep_research"]["qualified"]
            and float(row["research_score"]) >= float(minimum_scores["deep_research"])
        ),
        key=rank_key,
    )
    active_ids = {
        row["company_id"] for row in active_candidates[: int(limits["active_intelligence"])]
    }
    chain_ids = {row["company_id"] for row in chain_candidates[: int(limits["supply_chain"])]}
    deep_ids = {row["company_id"] for row in deep_candidates if row.get("deep_research_triggers")}
    selected_ids = active_ids | chain_ids | deep_ids
    for row in records:
        selected = row["company_id"] in selected_ids
        qualified = any(item["qualified"] for item in row["decisions"].values())
        row["research_universe_status"] = (
            "selected" if selected else "eligible_not_selected" if qualified else "not_eligible"
        )
        action_membership = {
            "news": active_ids,
            "etf": active_ids,
            "supply_chain": chain_ids,
            "deep_research": deep_ids,
        }
        for action, decision in row["decisions"].items():
            decision["enabled"] = bool(
                decision["qualified"] and row["company_id"] in action_membership[action]
            )
            if decision["qualified"] and not decision["enabled"]:
                decision["reason_code"] = (
                    "AWAITING_EVENT_TRIGGER"
                    if action == "deep_research"
                    else "ACTION_TIER_RANK_LIMIT_EXCEEDED"
                )

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
            "active_intelligence_company_count": len(active_ids),
            "supply_chain_company_count": len(chain_ids),
            "deep_research_company_count": len(deep_ids),
            "qualified_action_counts": dict(sorted(qualified_counts.items())),
            "enabled_action_counts": dict(sorted(action_counts.items())),
        },
        "policy": {
            "policy_path": policy_path,
            "theme_catalog_path": theme_catalog_path,
            "tier_limits": limits,
            "tier_minimum_scores": minimum_scores,
            "deep_research_activation_mode": "event_driven",
            "deep_research_trigger_types": ["sec_filing", "news", "etf_change"],
            "contains_ticker_membership": False,
            "valuation_readiness_consumed": False,
        },
        "records": records,
        "indexes": {
            "company_id_to_position": {
                row["company_id"]: index for index, row in enumerate(records)
            },
            "ticker_to_position": {
                row["ticker"]: index for index, row in enumerate(records) if row["ticker"]
            },
        },
    }


def write_research_eligibility(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
