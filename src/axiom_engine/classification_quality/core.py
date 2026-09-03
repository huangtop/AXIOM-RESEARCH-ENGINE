from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from axiom_engine.business_evidence_store import load_business_evidence


class ClassificationQualityError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClassificationQualityError(f"cannot read {path}: {exc}") from exc


def build_classification_quality_audit(
    root: Path,
    *,
    policy_path: str = "config/classification_quality.v031c.5.json",
    evidence_path: str = "data/generated/canonical_business_evidence/business_evidence.json",
    signals_path: str = "data/generated/company_signals/company_signals.json",
    knowledge_path: str = "data/generated/knowledge_inference/knowledge_inference.json",
    gate_path: str = "data/generated/research_relevance_gate/research_relevance_gate.json",
    eligibility_path: str = "data/generated/research_eligibility/research_eligibility.json",
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    policy = _load(root / policy_path)
    if policy.get("schema_version") != "classification-quality-policy.v031c.5":
        raise ClassificationQualityError("unsupported classification quality policy")
    evidence = load_business_evidence(root / evidence_path)
    signals_payload = _load(root / signals_path)
    knowledge_payload = _load(root / knowledge_path)
    gate_payload = _load(root / gate_path)
    eligibility_payload = _load(root / eligibility_path)
    signals_by_company = {str(row["company_id"]): row for row in signals_payload["records"]}
    gate_by_company = {str(row["company_id"]): row for row in gate_payload["records"]}
    eligibility_by_company = {str(row["company_id"]): row for row in eligibility_payload["records"]}
    low_threshold = float(policy["low_confidence_threshold"])
    minimum_dimensions = int(policy["minimum_multidimensional_dimensions"])
    compatibility = policy.get("theme_sector_compatibility") or {}
    diagnostics: list[dict[str, Any]] = []
    flag_counts: Counter[str] = Counter()
    dimension_company_counts: Counter[str] = Counter()
    multidimensional_counts: Counter[str] = Counter()
    for record in knowledge_payload["records"]:
        company_id = str(record["company_id"])
        knowledge = list(record.get("knowledge") or [])
        signals = list((signals_by_company.get(company_id) or {}).get("signals") or [])
        gate = gate_by_company.get(company_id) or {}
        dimensions = sorted({str(item.get("dimension")) for item in knowledge})
        for dimension in dimensions:
            dimension_company_counts[dimension] += 1
        multidimensional_counts[str(len(dimensions))] += 1
        flags: list[dict[str, Any]] = []
        if gate.get("deep_inference_required") and not signals:
            flags.append({"code":"NO_SIGNALS","details":{}})
        if record.get("status") == "signals_only":
            flags.append({"code":"SIGNALS_WITHOUT_UPPER_CLASSIFICATION","details":{}})
        low = [item["knowledge_id"] for item in knowledge if item.get("derivation_type") == "rule_inference" and float(item.get("confidence") or 0) < low_threshold]
        if low:
            flags.append({"code":"LOW_CONFIDENCE_CLASSIFICATION","details":{"knowledge_ids":low}})
        ids = {str(item.get("knowledge_id")) for item in knowledge}
        sectors = {value for value in ids if value.startswith("sector:")}
        conflicts = {theme: required for theme, required in compatibility.items() if theme in ids and not sectors.intersection(required)}
        if conflicts:
            flags.append({"code":"THEME_SECTOR_CONFLICT","details":{"conflicts":conflicts}})
        if "theme:ai_infrastructure" in ids:
            support_dimensions = set(policy["ai_support_dimensions"])
            supported = any(item.get("dimension") in support_dimensions and item.get("knowledge_id") != policy["broad_ai_signal_id"] for item in knowledge)
            if not supported:
                flags.append({"code":"OVERBROAD_AI_CLASSIFICATION","details":{}})
        single_evidence = sorted({
            item["knowledge_id"] for item in knowledge
            if item.get("derivation_type") == "rule_inference" and len(item.get("source_business_evidence_ids") or []) == 1
        })
        if single_evidence:
            flags.append({"code":"SINGLE_EVIDENCE_CLASSIFICATION","details":{"knowledge_ids":single_evidence}})
        if record.get("status") == "knowledge_available" and len(dimensions) < minimum_dimensions:
            flags.append({"code":"INSUFFICIENT_DIMENSION_BREADTH","details":{"dimensions":dimensions}})
        if flags:
            for flag in flags:
                flag_counts[flag["code"]] += 1
            diagnostics.append({
                "company_id": company_id,
                "gate_status": gate.get("status"),
                "research_universe_status": (eligibility_by_company.get(company_id) or {}).get("research_universe_status"),
                "flags": flags,
            })
    company_count = len(knowledge_payload["records"])
    evidence_companies = len({str(row.get("company_id")) for row in evidence if row.get("company_id")})
    return {
        "schema_version": "classification-quality-audit.v031c.5",
        "version": "V031C.5",
        "generated_at": current.isoformat(),
        "summary": {
            "company_count": company_count,
            "business_evidence_company_count": evidence_companies,
            "business_evidence_coverage_ratio": round(evidence_companies / company_count, 6) if company_count else 0.0,
            "gate_status_counts": gate_payload.get("summary", {}).get("status_counts", {}),
            "knowledge_status_counts": dict(sorted(Counter(str(row.get("status")) for row in knowledge_payload["records"]).items())),
            "research_universe_count": eligibility_payload.get("summary", {}).get("selected_research_company_count", 0),
            "research_tier_counts": {
                "active_intelligence": eligibility_payload.get("summary", {}).get("active_intelligence_company_count", 0),
                "supply_chain": eligibility_payload.get("summary", {}).get("supply_chain_company_count", 0),
                "deep_research": eligibility_payload.get("summary", {}).get("deep_research_company_count", 0),
            },
            "flag_counts": dict(sorted(flag_counts.items())),
            "dimension_company_counts": dict(sorted(dimension_company_counts.items())),
            "dimension_breadth_company_counts": dict(sorted(multidimensional_counts.items(), key=lambda item: int(item[0]))),
        },
        "diagnostics": diagnostics,
    }


def write_classification_quality_audit(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
