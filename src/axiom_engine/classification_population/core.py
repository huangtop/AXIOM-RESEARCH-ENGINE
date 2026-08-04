from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class ClassificationPopulationError(RuntimeError):
    pass


FORBIDDEN_MEMBERSHIP_KEYS = {"ticker", "tickers", "symbol", "symbols", "company_id", "company_ids"}


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClassificationPopulationError(f"cannot read {path}: {exc}") from exc


def _matches(code: str, specifications: list[str]) -> bool:
    if not code.isdigit():
        return False
    value = int(code)
    for specification in specifications:
        if "-" in specification:
            lower, upper = specification.split("-", 1)
            if int(lower) <= value <= int(upper):
                return True
        elif code == specification:
            return True
    return False


def _validate(policy: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != "research-relevance-gate-policy.v031c.5":
        raise ClassificationPopulationError("unsupported relevance gate policy")
    serialized = json.dumps(policy)
    if any(f'"{key}"' in serialized for key in FORBIDDEN_MEMBERSHIP_KEYS):
        raise ClassificationPopulationError("ticker/company membership is forbidden in relevance policy")
    ids: set[str] = set()
    for group in ("priority_sic_rules", "deprioritized_sic_rules"):
        for rule in policy.get(group) or []:
            rule_id = str(rule.get("rule_id") or "")
            if not rule_id or rule_id in ids or not rule.get("codes") or not rule.get("category"):
                raise ClassificationPopulationError(f"invalid or duplicate relevance rule: {rule_id}")
            ids.add(rule_id)
    category_overrides = policy.get("research_override_signal_ids_by_category") or {}
    if not isinstance(category_overrides, Mapping) or any(not isinstance(value, list) for value in category_overrides.values()):
        raise ClassificationPopulationError("category-specific signal overrides must be arrays")


def build_research_relevance_gate(
    root: Path,
    *,
    policy_path: str = "config/research_relevance_gate.v031c.5.json",
    companies_path: str = "data/universe/companies.json",
    classifications_path: str = "data/generated/canonical_company_evidence/official_classifications.json",
    signals_path: str = "data/generated/company_signals/company_signals.json",
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    policy = _load(root / policy_path)
    companies = _load(root / companies_path)
    classifications = _load(root / classifications_path)
    signals_payload = _load(root / signals_path) if (root / signals_path).is_file() else {"records": []}
    _validate(policy)
    if not isinstance(companies, list) or not isinstance(classifications, list):
        raise ClassificationPopulationError("company and classification inputs must be arrays")

    sic_by_company = {
        str(row["company_id"]): row for row in classifications
        if row.get("company_id") and row.get("classification_scheme") == "SEC_SIC"
    }
    signals_by_company = {
        str(row["company_id"]): list(row.get("signals") or [])
        for row in signals_payload.get("records") or [] if row.get("company_id")
    }
    override_dimensions = set(policy.get("research_override_dimensions") or [])
    override_ids = set(policy.get("research_override_signal_ids") or [])
    category_override_ids = {
        str(category): set(values)
        for category, values in (policy.get("research_override_signal_ids_by_category") or {}).items()
    }
    records: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    overrides = 0
    for company in companies:
        company_id = str(company["company_id"])
        classification = sic_by_company.get(company_id)
        code = str((classification or {}).get("classification_code") or "")
        matched: Mapping[str, Any] | None = None
        status = "evidence_required"
        reason = "SIC_NOT_DECISIVE" if code else "OFFICIAL_SIC_UNAVAILABLE"
        for rule in policy.get("priority_sic_rules") or []:
            if _matches(code, list(rule["codes"])):
                matched, status, reason = rule, "priority_candidate", "RESEARCH_RELEVANT_SIC"
                break
        if matched is None:
            for rule in policy.get("deprioritized_sic_rules") or []:
                if _matches(code, list(rule["codes"])):
                    matched, status, reason = rule, "deprioritized_non_research", "NON_RESEARCH_SIC"
                    break
        category = str((matched or {}).get("category") or "unclassified")
        effective_override_ids = category_override_ids.get(category, override_ids)
        signals = signals_by_company.get(company_id, [])
        override_signals = sorted({
            str(signal.get("signal_id")) for signal in signals
            if signal.get("dimension") in override_dimensions or signal.get("signal_id") in effective_override_ids
        })
        if status == "deprioritized_non_research" and override_signals:
            status, reason = "priority_candidate", "VERIFIED_RESEARCH_SIGNAL_OVERRIDE"
            overrides += 1
        status_counts[status] += 1
        category_counts[category] += 1
        records.append({
            "company_id": company_id,
            "status": status,
            "upper_category": category,
            "reason_code": reason,
            "official_classification": {
                "scheme": (classification or {}).get("classification_scheme"),
                "code": code or None,
                "label": (classification or {}).get("classification_label"),
                "classification_id": (classification or {}).get("classification_id"),
            },
            "matched_rule_id": (matched or {}).get("rule_id"),
            "research_override_signal_ids": override_signals,
            "deep_inference_required": status != "deprioritized_non_research",
        })
    return {
        "schema_version": "research-relevance-gate.v031c.5",
        "version": "V031C.5",
        "generated_at": current.isoformat(),
        "summary": {
            "company_count": len(records),
            "official_sic_company_count": len(sic_by_company),
            "status_counts": dict(sorted(status_counts.items())),
            "upper_category_counts": dict(sorted(category_counts.items())),
            "signal_override_count": overrides,
        },
        "policy": {"policy_path": policy_path, "contains_ticker_membership": False},
        "records": records,
        "indexes": {"company_id_to_position": {row["company_id"]: index for index, row in enumerate(records)}},
    }


def write_research_relevance_gate(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
