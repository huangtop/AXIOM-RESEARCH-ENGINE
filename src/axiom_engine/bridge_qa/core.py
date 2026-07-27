from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BridgeQAError(RuntimeError):
    """Raised when a required bridge-layer snapshot is missing or invalid."""


def _load(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise BridgeQAError(f"{label} not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BridgeQAError(f"{label} must be a JSON object: {path}")
    return payload


def _companies(payload: dict[str, Any], label: str, key: str = "companies") -> list[dict[str, Any]]:
    rows = payload.get(key)
    if not isinstance(rows, list):
        raise BridgeQAError(f"{label} must contain a {key} array")
    return [row for row in rows if isinstance(row, dict)]


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _issue(layer: str, code: str, severity: str, **context: Any) -> dict[str, Any]:
    return {"layer": layer, "code": code, "severity": severity, **context}


def build_bridge_qa(
    repository_root: Path,
    *,
    identity_path: str = "data/generated/identity/company_identity_map.json",
    bridge_path: str = "data/generated/financial_bridge/canonical_financial_snapshot.json",
    timeline_path: str = "data/generated/financial_timeline/financial_timeline.json",
    router_path: str = "data/generated/source_router/financial_source_snapshot.json",
) -> dict[str, Any]:
    identity = _load(repository_root / identity_path, "identity map")
    bridge = _load(repository_root / bridge_path, "financial bridge")
    timeline = _load(repository_root / timeline_path, "financial timeline")
    router = _load(repository_root / router_path, "source router")

    identity_rows = _companies(identity, "identity map", "records")
    bridge_rows = _companies(bridge, "financial bridge")
    timeline_rows = _companies(timeline, "financial timeline")
    router_rows = _companies(router, "source router")

    identity_by_id = {str(r.get("company_id")): r for r in identity_rows if r.get("company_id")}
    bridge_by_id = {str(r.get("company_id")): r for r in bridge_rows if r.get("company_id")}
    timeline_by_id = {str(r.get("company_id")): r for r in timeline_rows if r.get("company_id")}
    router_by_id = {str(r.get("company_id")): r for r in router_rows if r.get("company_id")}

    issues: list[dict[str, Any]] = []
    checks = Counter()

    # Cross-layer company linkage and identity consistency.
    for layer, rows in (("financial_bridge", bridge_rows), ("financial_timeline", timeline_rows), ("source_router", router_rows)):
        for row in rows:
            checks["company_linkage"] += 1
            cid = str(row.get("company_id") or "")
            ident = identity_by_id.get(cid)
            if ident is None:
                issues.append(_issue(layer, "company_id_not_in_identity", "critical", company_id=cid or None))
                continue
            if row.get("cik") and str(row.get("cik")) != str(ident.get("cik")):
                issues.append(_issue(layer, "cik_mismatch", "critical", company_id=cid, expected=ident.get("cik"), actual=row.get("cik")))
            if row.get("primary_symbol") and str(row.get("primary_symbol")) != str(ident.get("primary_symbol")):
                issues.append(_issue(layer, "symbol_mismatch", "critical", company_id=cid, expected=ident.get("primary_symbol"), actual=row.get("primary_symbol")))

    for cid in sorted(set(bridge_by_id) - set(timeline_by_id)):
        issues.append(_issue("financial_timeline", "bridge_company_missing_from_timeline", "critical", company_id=cid))
    for cid in sorted(set(timeline_by_id) - set(router_by_id)):
        issues.append(_issue("source_router", "timeline_company_missing_from_router", "critical", company_id=cid))
    for cid in sorted(set(timeline_by_id) - set(bridge_by_id)):
        issues.append(_issue("financial_timeline", "timeline_company_missing_from_bridge", "critical", company_id=cid))

    # Financial Bridge structural and provenance checks.
    seen_fact_ids: set[str] = set()
    bridge_fact_count = 0
    for company in bridge_rows:
        cid = str(company.get("company_id") or "")
        facts = company.get("facts") or []
        if not isinstance(facts, list):
            issues.append(_issue("financial_bridge", "facts_not_array", "critical", company_id=cid))
            continue
        bridge_fact_count += len(facts)
        for fact in facts:
            checks["financial_fact"] += 1
            if not isinstance(fact, dict):
                issues.append(_issue("financial_bridge", "fact_not_object", "critical", company_id=cid))
                continue
            fid = str(fact.get("financial_fact_id") or "")
            if not fid:
                issues.append(_issue("financial_bridge", "missing_fact_id", "critical", company_id=cid))
            elif fid in seen_fact_ids:
                issues.append(_issue("financial_bridge", "duplicate_fact_id", "critical", company_id=cid, financial_fact_id=fid))
            else:
                seen_fact_ids.add(fid)
            if not _finite(fact.get("value")):
                issues.append(_issue("financial_bridge", "invalid_fact_value", "critical", company_id=cid, financial_fact_id=fid or None))
            source = fact.get("source") or {}
            if source.get("provider") != "sec_companyfacts":
                issues.append(_issue("financial_bridge", "invalid_fact_provider", "critical", company_id=cid, financial_fact_id=fid or None, provider=source.get("provider")))
            if not fact.get("period_end"):
                issues.append(_issue("financial_bridge", "missing_period_end", "critical", company_id=cid, financial_fact_id=fid or None))
            if not fact.get("unit"):
                issues.append(_issue("financial_bridge", "missing_unit", "warning", company_id=cid, financial_fact_id=fid or None))
            if fact.get("unit") == "currency" and not fact.get("currency"):
                issues.append(_issue("financial_bridge", "missing_currency", "warning", company_id=cid, financial_fact_id=fid or None))

    expected_bridge_facts = (bridge.get("summary") or {}).get("canonical_fact_count")
    if expected_bridge_facts != bridge_fact_count:
        issues.append(_issue("financial_bridge", "summary_fact_count_mismatch", "critical", expected=expected_bridge_facts, actual=bridge_fact_count))

    # Timeline period/freshness checks.
    for company in timeline_rows:
        cid = str(company.get("company_id") or "")
        checks["timeline_company"] += 1
        if company.get("freshness_state") not in {"fresh", "current", "stale", "missing"}:
            issues.append(_issue("financial_timeline", "invalid_freshness_state", "critical", company_id=cid, value=company.get("freshness_state")))
        ttm = company.get("ttm") or {}
        if ttm.get("state") not in {"four_quarter_sum", "annual_proxy", "missing"}:
            issues.append(_issue("financial_timeline", "invalid_ttm_state", "critical", company_id=cid, value=ttm.get("state")))
        for bucket in ("annual_periods", "quarterly_periods"):
            periods = company.get(bucket) or []
            if not isinstance(periods, list):
                issues.append(_issue("financial_timeline", "period_bucket_not_array", "critical", company_id=cid, bucket=bucket))
                continue
            previous = ""
            for period in periods:
                checks["timeline_period"] += 1
                end = str((period or {}).get("period_end") or "")
                if not end:
                    issues.append(_issue("financial_timeline", "missing_period_end", "critical", company_id=cid, bucket=bucket))
                if previous and end < previous:
                    issues.append(_issue("financial_timeline", "periods_not_sorted", "critical", company_id=cid, bucket=bucket, previous=previous, actual=end))
                previous = end

    # Router attribution, SEC precedence and missing-reason checks.
    allowed_confidence = {"high", "medium", "low"}
    allowed_provider = {"sec_companyfacts", "yahoo_finance"}
    routed_metric_count = 0
    provider_counts = Counter()
    for company in router_rows:
        cid = str(company.get("company_id") or "")
        timeline_company = timeline_by_id.get(cid) or {}
        sec_metrics = {
            **(((timeline_company.get("ttm") or {}).get("metrics")) or {}),
            **((timeline_company.get("instant_metrics")) or {}),
        }
        metrics = company.get("metrics") or {}
        if not isinstance(metrics, dict):
            issues.append(_issue("source_router", "metrics_not_object", "critical", company_id=cid))
            continue
        for name, metric in metrics.items():
            checks["routed_metric"] += 1
            routed_metric_count += 1
            if not isinstance(metric, dict):
                issues.append(_issue("source_router", "metric_not_object", "critical", company_id=cid, metric=name))
                continue
            provider = metric.get("provider")
            provider_counts[str(provider)] += 1
            if provider not in allowed_provider:
                issues.append(_issue("source_router", "invalid_provider", "critical", company_id=cid, metric=name, provider=provider))
            if metric.get("confidence") not in allowed_confidence:
                issues.append(_issue("source_router", "invalid_confidence", "critical", company_id=cid, metric=name, value=metric.get("confidence")))
            if not _finite(metric.get("value")):
                issues.append(_issue("source_router", "invalid_metric_value", "critical", company_id=cid, metric=name))
            if provider == "sec_companyfacts":
                if metric.get("source_state") != "primary" or metric.get("fallback_reason") is not None:
                    issues.append(_issue("source_router", "invalid_sec_attribution", "critical", company_id=cid, metric=name))
                if name not in sec_metrics:
                    issues.append(_issue("source_router", "sec_metric_missing_from_timeline", "critical", company_id=cid, metric=name))
            elif provider == "yahoo_finance":
                if metric.get("source_state") != "fallback" or metric.get("fallback_reason") != "sec_metric_missing" or not metric.get("source_field"):
                    issues.append(_issue("source_router", "invalid_yahoo_attribution", "critical", company_id=cid, metric=name))
                if name in sec_metrics and (sec_metrics.get(name) or {}).get("value") is not None:
                    issues.append(_issue("source_router", "sec_precedence_violation", "critical", company_id=cid, metric=name))

    expected_provider_counts = ((router.get("summary") or {}).get("provider_metric_counts") or {})
    for provider in allowed_provider:
        expected = int(expected_provider_counts.get(provider, 0) or 0)
        actual = provider_counts.get(provider, 0)
        if expected != actual:
            issues.append(_issue("source_router", "summary_provider_count_mismatch", "critical", provider=provider, expected=expected, actual=actual))

    missing_metrics = ((router.get("diagnostics") or {}).get("missing_metrics") or [])
    if not isinstance(missing_metrics, list):
        issues.append(_issue("source_router", "missing_metrics_not_array", "critical"))
        missing_metrics = []
    for row in missing_metrics:
        checks["missing_metric"] += 1
        if not isinstance(row, dict) or not row.get("company_id") or not row.get("metric") or not row.get("reason"):
            issues.append(_issue("source_router", "incomplete_missing_reason", "critical", record=row))

    expected_missing = (router.get("summary") or {}).get("missing_metric_count")
    if expected_missing != len(missing_metrics):
        issues.append(_issue("source_router", "summary_missing_count_mismatch", "critical", expected=expected_missing, actual=len(missing_metrics)))

    severity_counts = Counter(issue["severity"] for issue in issues)
    code_counts = Counter(issue["code"] for issue in issues)
    critical_count = severity_counts.get("critical", 0)
    warning_count = severity_counts.get("warning", 0)
    status = "pass" if critical_count == 0 else "fail"
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "bridge-qa-report.v030.11.3",
        "version": "V030.11.3",
        "generated_at": generated_at,
        "status": status,
        "sources": {
            "identity_path": identity_path,
            "bridge_path": bridge_path,
            "timeline_path": timeline_path,
            "router_path": router_path,
        },
        "summary": {
            "status": status,
            "critical_issue_count": critical_count,
            "warning_issue_count": warning_count,
            "identity_company_count": len(identity_rows),
            "bridge_company_count": len(bridge_rows),
            "timeline_company_count": len(timeline_rows),
            "router_company_count": len(router_rows),
            "bridge_fact_count": bridge_fact_count,
            "routed_metric_count": routed_metric_count,
            "missing_metric_count": len(missing_metrics),
            "check_counts": dict(sorted(checks.items())),
            "issue_code_counts": dict(sorted(code_counts.items())),
        },
        "gates": {
            "identity_linkage": "pass" if not any(i["severity"] == "critical" and i["code"] in {"company_id_not_in_identity", "cik_mismatch", "symbol_mismatch"} for i in issues) else "fail",
            "bridge_integrity": "pass" if not any(i["severity"] == "critical" and i["layer"] == "financial_bridge" for i in issues) else "fail",
            "timeline_integrity": "pass" if not any(i["severity"] == "critical" and i["layer"] == "financial_timeline" for i in issues) else "fail",
            "router_attribution": "pass" if not any(i["severity"] == "critical" and i["layer"] == "source_router" for i in issues) else "fail",
        },
        "issues": issues,
    }


def write_bridge_qa(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
