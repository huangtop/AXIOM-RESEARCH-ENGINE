from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class CoveragePolicyError(RuntimeError):
    pass


FORBIDDEN_MEMBERSHIP_KEYS = {"ticker", "tickers", "symbol", "symbols", "company_id", "company_ids"}
TIERS = ("core", "coverage", "contextual", "candidate", "excluded")
ACTIONS = ("news", "etf", "supply_chain", "deep_research")


def _load(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoveragePolicyError(f"cannot read {label} at {path}: {exc}") from exc


def _validate_policy(policy: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != "coverage-policy-config.v031f.1":
        raise CoveragePolicyError("unsupported coverage policy")
    serialized = json.dumps(policy)
    if any(f'"{key}"' in serialized for key in FORBIDDEN_MEMBERSHIP_KEYS):
        raise CoveragePolicyError("ticker/company membership is forbidden in coverage policy")
    publication = policy.get("publication")
    if not isinstance(publication, Mapping) or set(publication) != set(TIERS):
        raise CoveragePolicyError("coverage policy must define every publication tier")
    derivation = policy.get("tier_derivation") or {}
    for key in ("core_requires_any_enabled_action", "coverage_requires_any_enabled_action"):
        values = derivation.get(key)
        if not isinstance(values, list) or not values or not set(values).issubset(ACTIONS):
            raise CoveragePolicyError(f"invalid action list: {key}")
    projection = policy.get("projection") or {}
    emit_tiers = projection.get("emit_tiers")
    if projection.get("default_unlisted_tier") != "contextual":
        raise CoveragePolicyError("sparse projection default must be contextual")
    if not isinstance(emit_tiers, list) or not set(emit_tiers).issubset(TIERS) or "contextual" in emit_tiers:
        raise CoveragePolicyError("sparse projection emit tiers are invalid")


def _enabled(record: Mapping[str, Any], actions: list[str]) -> bool:
    decisions = record.get("decisions") if isinstance(record.get("decisions"), Mapping) else {}
    return any(bool((decisions.get(action) or {}).get("enabled")) for action in actions)


def _tier(
    identity: Mapping[str, Any],
    research: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> tuple[str, str]:
    if identity.get("valuation_scope_status") != "included":
        return "excluded", "NON_OPERATING_COMPANY_INSTRUMENT"
    derivation = policy["tier_derivation"]
    if _enabled(research, list(derivation["core_requires_any_enabled_action"])):
        return "core", "ACTIVE_INTELLIGENCE_ENABLED"
    if _enabled(research, list(derivation["coverage_requires_any_enabled_action"])):
        return "coverage", "SUPPLY_CHAIN_OR_DEEP_RESEARCH_ENABLED"
    if research.get("research_universe_status") in set(derivation.get("candidate_universe_statuses") or []):
        return "candidate", "RESEARCH_ELIGIBLE_AWAITING_TIER_CAPACITY"
    relevance = research.get("research_relevance") if isinstance(research.get("research_relevance"), Mapping) else {}
    if relevance.get("status") in set(derivation.get("candidate_relevance_statuses") or []):
        return "candidate", "PRIORITY_COMPANY_AWAITING_EVIDENCE"
    return "contextual", "IDENTITY_RESOLVED_CONTEXT_ONLY"


def _valuation_projection(tier: str, card: Mapping[str, Any] | None) -> dict[str, Any]:
    data_status = str((card or {}).get("status") or "unavailable")
    models = ((card or {}).get("valuation") or {}).get("models") or {}
    eligible_methods = sorted(
        str(method) for method, result in models.items()
        if isinstance(result, Mapping) and result.get("status") == "calculated"
    )
    if tier in {"core", "coverage"}:
        scope_status, reason = "eligible", "PUBLIC_TIER_VALUATION_ELIGIBLE"
    elif tier == "candidate":
        scope_status, reason = "deferred", "CANDIDATE_NOT_YET_PUBLISHED"
    elif tier == "contextual":
        scope_status, reason = "not_covered", "CONTEXTUAL_COMPANY_NO_VALUATION_COMMITMENT"
    else:
        scope_status, reason = "not_applicable", "NON_OPERATING_COMPANY_INSTRUMENT"
    return {
        "scope_status": scope_status,
        "data_status": data_status,
        "eligible_methods": eligible_methods,
        "calculated_model_count": len(eligible_methods),
        "reason_code": reason,
    }


def build_coverage_policy(
    root: Path,
    *,
    policy_path: str = "config/coverage_policy.v031f.1.json",
    companies_path: str = "data/universe/companies.json",
    securities_path: str = "data/universe/securities.json",
    identity_path: str = "data/generated/security_identity/security_identity_normalization.json",
    research_path: str = "data/generated/research_eligibility/research_eligibility.json",
    valuation_path: str = "data/generated/full_market_coverage/full_market_coverage.json",
    etf_exposure_path: str = "data/generated/canonical_etf_exposure/etf_exposures.json",
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    policy = _load(root / policy_path, "coverage policy")
    companies = _load(root / companies_path, "companies")
    securities = _load(root / securities_path, "securities")
    identity_payload = _load(root / identity_path, "security identity")
    research_payload = _load(root / research_path, "research eligibility")
    valuation_payload = _load(root / valuation_path, "full-market valuation")
    exposure_rows = _load(root / etf_exposure_path, "ETF exposure") if (root / etf_exposure_path).is_file() else []
    _validate_policy(policy)
    if not isinstance(companies, list) or not isinstance(securities, list):
        raise CoveragePolicyError("company and security registries must be arrays")

    identity_by_company = {str(row["company_id"]): row for row in identity_payload.get("companies") or []}
    research_by_company = {str(row["company_id"]): row for row in research_payload.get("records") or []}
    valuation_by_company = {
        str((row.get("company") or {}).get("company_id")): row
        for row in valuation_payload.get("cards") or []
        if (row.get("company") or {}).get("company_id")
    }
    primary_security = {
        str(row.get("company_id")): row for row in securities
        if row.get("primary_listing") is True and row.get("company_id")
    }
    exposure_count: Counter[str] = Counter(
        str(row.get("company_id")) for row in exposure_rows if row.get("company_id")
    )
    records: list[dict[str, Any]] = []
    tier_counts: Counter[str] = Counter()
    valuation_scope_counts: Counter[str] = Counter()
    publication_counts: Counter[str] = Counter()
    for company in companies:
        company_id = str(company["company_id"])
        identity = identity_by_company.get(company_id, {})
        research = research_by_company.get(company_id, {})
        tier, tier_reason = _tier(identity, research, policy)
        publication = dict(policy["publication"][tier])
        valuation = _valuation_projection(tier, valuation_by_company.get(company_id))
        evidence = research.get("evidence_summary") if isinstance(research.get("evidence_summary"), Mapping) else {}
        security = primary_security.get(company_id, {})
        actions = {
            action: bool(((research.get("decisions") or {}).get(action) or {}).get("enabled"))
            for action in ACTIONS
        }
        reason_codes = [tier_reason, valuation["reason_code"]]
        relevance_reason = ((research.get("research_relevance") or {}).get("reason_code"))
        if relevance_reason:
            reason_codes.append(str(relevance_reason))
        record = {
            "company_id": company_id,
            "ticker": security.get("ticker"),
            "display_name": company.get("display_name"),
            "instrument_scope": {
                "status": "operating_company_equity" if identity.get("valuation_scope_status") == "included" else "excluded",
                "reason_code": identity.get("reason_code") or "IDENTITY_RECORD_UNAVAILABLE",
            },
            "research_scope": tier,
            "publication_tier": tier,
            "publication": publication,
            "valuation": valuation,
            "research_actions": actions,
            "context": {
                "etf_exposure_count": int(exposure_count[company_id]),
                "etf_exposure_used_for_tier": False,
                "research_score": research.get("research_score"),
                "matched_theme_ids": list(research.get("matched_catalog_theme_ids") or []),
            },
            "reason_codes": sorted(set(reason_codes)),
            "evidence_refs": sorted(set(evidence.get("business_evidence_ids") or [])),
            "review_status": "automatic",
        }
        records.append(record)
        tier_counts[tier] += 1
        valuation_scope_counts[valuation["scope_status"]] += 1
        publication_counts[str(publication["visibility"])] += 1

    records.sort(key=lambda row: row["company_id"])
    emit_tiers = set(policy["projection"]["emit_tiers"])
    emitted_records = [row for row in records if row["publication_tier"] in emit_tiers]
    return {
        "schema_version": "coverage-policy-projection.v031f.1",
        "version": "V031F.1",
        "generated_at": current.isoformat(),
        "summary": {
            "company_count": len(records),
            "explicit_record_count": len(emitted_records),
            "default_contextual_company_count": tier_counts["contextual"],
            "tier_counts": dict(sorted(tier_counts.items())),
            "valuation_scope_counts": dict(sorted(valuation_scope_counts.items())),
            "publication_visibility_counts": dict(sorted(publication_counts.items())),
            "public_company_page_count": sum(bool(row["publication"]["company_page"]) for row in records),
            "public_valuation_card_count": sum(bool(row["publication"]["valuation_card"]) for row in records),
            "etf_exposed_company_count": sum(row["context"]["etf_exposure_count"] > 0 for row in records),
        },
        "sources": {
            "policy_path": policy_path,
            "identity_path": identity_path,
            "research_path": research_path,
            "valuation_path": valuation_path,
            "etf_exposure_path": etf_exposure_path,
        },
        "contract": {
            "contains_ticker_membership": False,
            "etf_exposure_determines_tier": False,
            "valuation_readiness_determines_research_scope": False,
            "manual_editorial_override_enabled": False,
            "sparse_projection": True,
            "unlisted_company_default_tier": policy["projection"]["default_unlisted_tier"],
        },
        "records": emitted_records,
        "indexes": {
            "company_id_to_position": {row["company_id"]: index for index, row in enumerate(emitted_records)},
            "ticker_to_company_id": {row["ticker"]: row["company_id"] for row in emitted_records if row.get("ticker")},
        },
    }


def write_coverage_policy(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(output)
