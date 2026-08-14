from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from axiom_engine.business_evidence_store import load_business_evidence


class CompanyAnalysisError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompanyAnalysisError(f"cannot read {path}: {exc}") from exc


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _join_zh(values: list[str]) -> str:
    values = list(dict.fromkeys(value for value in values if value))
    if len(values) < 2:
        return values[0] if values else ""
    return "、".join(values[:-1]) + "與" + values[-1]


def _source_ids(signals: list[Mapping[str, Any]]) -> list[str]:
    return sorted({str(value) for signal in signals for value in signal.get("source_business_evidence_ids") or []})


def _claim(text: str, signals: list[Mapping[str, Any]], derivation: str) -> dict[str, Any]:
    return {
        "text": text,
        "evidence_ids": _source_ids(signals),
        "signal_ids": sorted(str(signal["signal_id"]) for signal in signals),
        "derivation": derivation,
    }


def build_company_analyses(
    root: Path,
    *,
    company_ids: set[str] | None = None,
    signals_payload: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    policy = _load(root / "config/company_analysis.v1.json")
    if policy.get("schema_version") != "company-analysis-policy.v1":
        raise CompanyAnalysisError("unsupported company analysis policy")
    forbidden = {"ticker", "tickers", "company_id", "company_ids", "symbols"}
    if any(forbidden.intersection(value) for value in policy.values() if isinstance(value, dict)):
        raise CompanyAnalysisError("company-specific membership is forbidden in analysis policy")

    eligibility = _load(
        root / "data/generated/research_eligibility/research_eligibility.json"
    )
    allowed_themes = set(policy["scope"]["allowed_theme_ids"])
    scoped_company_ids = {
        str(row["company_id"])
        for row in eligibility.get("records") or []
        if ((row.get("decisions") or {}).get("supply_chain") or {}).get("enabled") is True
        and allowed_themes.intersection(row.get("matched_catalog_theme_ids") or [])
    }

    companies = {str(row["company_id"]): row for row in _load(root / "data/universe/companies.json")}
    securities = _load(root / "data/universe/securities.json")
    ticker_by_company: dict[str, str] = {}
    for row in securities:
        company_id = str(row.get("company_id") or "")
        ticker = str(row.get("ticker") or "").upper()
        if company_id and ticker and (row.get("primary_listing") is True or company_id not in ticker_by_company):
            ticker_by_company[company_id] = ticker

    signals_report = signals_payload or _load(root / "data/generated/company_signals/company_signals.json")
    signal_by_company = {str(row["company_id"]): row for row in signals_report.get("records") or []}
    evidence = load_business_evidence(root / "data/generated/canonical_business_evidence")
    evidence_by_id = {str(row["business_evidence_id"]): row for row in evidence}
    overview_dir = root / "data/generated/company_overview/per-company"
    overview_by_company = {}
    for path in overview_dir.glob("*.json"):
        overview = _load(path)
        if overview.get("company_id"):
            overview_by_company[str(overview["company_id"])] = overview

    labels = policy["display_names_zh_tw"]
    kinds = policy["kind_by_dimension"]
    records = []
    for company_id, source in sorted(signal_by_company.items()):
        if company_id not in scoped_company_ids:
            continue
        if company_ids is not None and company_id not in company_ids:
            continue
        overview = overview_by_company.get(company_id)
        ticker = ticker_by_company.get(company_id)
        if not overview or not ticker or source.get("status") != "signals_available":
            continue
        lock = overview.get("classification_lock") or {}
        if policy["scope"].get("require_classification_lock") and (
            lock.get("status") != "locked"
            or lock.get("update_mode") != "manual_override_only"
        ):
            continue
        if overview.get("classification_source") not in set(
            policy["scope"]["allowed_classification_sources"]
        ):
            continue
        classification_evidence_ids = {
            str(row.get("business_evidence_id"))
            for row in overview.get("evidence") or []
            if row.get("business_evidence_id")
        }
        if not classification_evidence_ids:
            continue
        signals = list(source.get("signals") or [])
        primary_products = [
            signal for signal in signals
            if signal.get("dimension") in {"product", "capability", "infrastructure"}
            and int(signal.get("primary_business_score") or 0) >= 3
        ]
        supporting = [
            signal for signal in signals
            if signal.get("dimension") in {"capability", "infrastructure"}
            and int(signal.get("primary_business_score") or 0) >= 3
        ]
        offering_candidates = {
            str(signal["signal_id"]): signal
            for signal in [*primary_products, *supporting]
        }
        offering_signals = sorted(
            offering_candidates.values(),
            key=lambda row: (
                -int(row.get("primary_business_score") or 0),
                -int(row.get("offering_occurrence_count") or 0),
                -float(row.get("confidence") or 0),
                str(row["signal_id"]),
            ),
        )[: int(policy["maximum_offerings"])]
        # A company analysis without a verified offering would be technology-keyword prose,
        # not a description of what the company sells.
        if not primary_products:
            continue
        end_markets = sorted(
            [
                signal for signal in signals
                if signal.get("dimension") == "end_market"
                and int(signal.get("occurrence_count") or 0) >= int(policy["minimum_end_market_occurrences"])
            ],
            key=lambda row: (-int(row.get("occurrence_count") or 0), str(row["signal_id"])),
        )[: int(policy["maximum_end_markets"])]
        roles = sorted(
            [
                signal for signal in signals
                if signal.get("dimension") == "supply_chain_role"
                and int(signal.get("primary_business_score") or 0) >= 3
            ],
            key=lambda row: (-int(row.get("occurrence_count") or 0), str(row["signal_id"])),
        )[:2]
        offering_names = [labels.get(str(row["signal_id"]), str(row.get("canonical_name") or "")) for row in offering_signals]
        market_names = [labels.get(str(row["signal_id"]), str(row.get("canonical_name") or "")) for row in end_markets]
        role_names = [labels.get(str(row["signal_id"]), str(row.get("canonical_name") or "")) for row in roles]
        display_name = str((companies.get(company_id) or {}).get("display_name") or (companies.get(company_id) or {}).get("legal_name") or ticker)
        display_name = re.sub(
            r"\s+(?:Common Stock|- Ordinary Shares?)$", "", display_name, flags=re.IGNORECASE
        ).strip()
        sector = ((overview.get("path") or {}).get("sector") or {}).get("display_name_zh_tw") or "未分類產業"
        theme = ((overview.get("path") or {}).get("theme") or {}).get("display_name_zh_tw") or "未分類主題"

        summary_text = f"{display_name}是{sector}相關企業，主要提供{_join_zh(offering_names)}。"
        if role_names and market_names:
            summary_text += f"公司以{_join_zh(role_names)}參與{_join_zh(market_names)}市場。"
        elif market_names:
            summary_text += f"主要服務{_join_zh(market_names)}市場。"
        elif role_names:
            summary_text += f"公司在產業鏈中主要負責{_join_zh(role_names)}。"
        business_text = f"公司以{_join_zh(role_names) or '產品與服務交付'}為核心，提供{_join_zh(offering_names)}"
        business_text += f"，服務{_join_zh(market_names)}客戶。" if market_names else "。"

        used_signals = list({str(row["signal_id"]): row for row in [*offering_signals, *end_markets, *roles]}.values())
        evidence_ids = _source_ids(used_signals)
        # A lock alone is not evidence confirmation.  The reviewed
        # classification and generated prose must share a source filing.
        if not classification_evidence_ids.intersection(evidence_ids):
            continue
        evidence_rows = []
        for evidence_id in evidence_ids:
            row = evidence_by_id.get(evidence_id, {})
            evidence_rows.append({
                "evidence_id": evidence_id,
                "source_type": "sec_filing",
                "form": row.get("form"),
                "filing_date": row.get("filing_date"),
                "section": "Item 1. Business" if str(row.get("form") or "").startswith("10-K") else "Item 4. Information on the Company",
                "url": row.get("document_url"),
            })
        latest_date = max((str(row.get("filing_date") or "") for row in evidence_rows), default="")
        records.append({
            "schema_version": "axiom-company-analysis.v1",
            "generation_mode": "deterministic_evidence_template",
            "company_id": company_id,
            "ticker": ticker,
            "display_name": display_name,
            "as_of": latest_date,
            "classification": {
                "theme": theme,
                "sector": sector,
                "supply_chain_role": _join_zh(role_names) or "待更多證據確認",
            },
            "summary": _claim(summary_text, [*offering_signals, *end_markets, *roles], "deterministic_template"),
            "business_model": {
                "description": _claim(business_text, [*offering_signals, *end_markets, *roles], "deterministic_template"),
                "revenue_drivers": [_claim(name, [signal], "signal_translation") for name, signal in zip(offering_names, offering_signals)],
            },
            "offerings": [
                {
                    "name": name,
                    "kind": kinds.get(str(signal.get("dimension")), "offering"),
                    "description": _claim(
                        f"SEC 業務文件將{name}識別為公司的產品或核心能力。",
                        [signal],
                        "evidence_signal",
                    ),
                }
                for name, signal in zip(offering_names, offering_signals)
            ],
            "value_chain": {
                "upstream": [],
                "core": [_claim(name, [signal], "evidence_signal") for name, signal in zip([*role_names, *offering_names], [*roles, *offering_signals])],
                "downstream": [
                    {"label": name, "relationship": "終端市場", "evidence_ids": _source_ids([signal]), "signal_ids": [signal["signal_id"]]}
                    for name, signal in zip(market_names, end_markets)
                ],
            },
            "competitive_context": [],
            "watch_items": [],
            "evidence": evidence_rows,
            "provenance_policy": {
                "facts": "內容由 SEC business evidence 的產品、能力、角色與終端市場 signals 依固定模板產生。",
                "named_relationships": "目前不從關鍵字自動建立具名客戶或供應商關係。",
                "excluded": "technology signal 不得單獨成為公司主要產品或公司定位。",
            },
        })
    return {
        "schema_version": "axiom-company-analysis-index.v1",
        "generated_at": current.isoformat(),
        "summary": {"company_count": len(records)},
        "scope": {
            "source": "research_eligibility.decisions.supply_chain.enabled",
            "eligible_company_count": len(scoped_company_ids),
            "allowed_theme_ids": sorted(allowed_themes),
            "contains_company_membership": False,
            "required_classification_lock": True,
            "allowed_classification_sources": sorted(
                policy["scope"]["allowed_classification_sources"]
            ),
        },
        "records": records,
    }


def write_company_analyses(report: Mapping[str, Any], output: Path) -> None:
    files = {}
    for row in report.get("records") or []:
        filename = f"{row['ticker']}.json"
        files[str(row["ticker"])] = filename
        _write(output / "per-company" / filename, row)
    _write(output / "index.json", {
        "schema_version": report["schema_version"],
        "generated_at": report["generated_at"],
        "summary": report["summary"],
        "ticker_to_file": files,
    })
