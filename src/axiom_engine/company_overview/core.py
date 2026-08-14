from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from axiom_engine.business_evidence_store import load_business_evidence


class CompanyOverviewError(RuntimeError):
    pass


class CompanyOverviewNotFound(CompanyOverviewError):
    pass


AI_INFRASTRUCTURE_SECTOR_IDS = {
    "sector:ai_compute",
    "sector:ai_memory",
    "sector:ai_networking",
    "sector:ai_servers",
}


def _sector_rank(item: Mapping[str, Any]) -> tuple[int, float, str]:
    knowledge_id = str(item.get("knowledge_id") or "")
    specificity = 1 if knowledge_id in AI_INFRASTRUCTURE_SECTOR_IDS else 0
    return (-specificity, -float(item.get("confidence") or 0), knowledge_id)


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompanyOverviewError(f"cannot read {path}: {exc}") from exc


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def build_company_overviews(
    root: Path,
    *,
    company_ids: set[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    companies = _load(root / "data/universe/companies.json")
    securities = _load(root / "data/universe/securities.json")
    knowledge = _load(root / "data/generated/knowledge_inference/knowledge_inference.json")
    evidence = load_business_evidence(root / "data/generated/canonical_business_evidence")
    policy = _load(root / "config/company_overview.v031c.6.json")
    quality_path = root / "config/classification_quality.v031c.5.json"
    quality_policy = _load(quality_path) if quality_path.is_file() else {}
    compatibility = quality_policy.get("theme_sector_compatibility") or {}
    identity_path = root / "data/generated/security_identity/security_identity_normalization.json"
    eligible_security_ids = None
    if identity_path.is_file():
        identity = _load(identity_path)
        eligible_security_ids = {
            str(row.get("security_id"))
            for row in identity.get("securities") or []
            if row.get("valuation_eligible") is True
        }
    if policy.get("schema_version") != "canonical-company-overview-policy.v031c.6":
        raise CompanyOverviewError("unsupported overview policy")
    names = policy["display_names_zh_tw"]
    curated_overrides = {
        str(row["company_id"]): row
        for row in policy.get("curated_overrides") or []
        if row.get("company_id") and row.get("theme_id") and row.get("sector_id")
    }
    company_by_id = {str(row["company_id"]): row for row in companies}
    primary = {}
    aliases: dict[str, list[str]] = {}
    for row in securities:
        cid, ticker = str(row.get("company_id") or ""), str(row.get("ticker") or "").upper()
        if not cid or not ticker or str(row.get("status") or "active").lower() != "active":
            continue
        if eligible_security_ids is not None and str(row.get("security_id") or "") not in eligible_security_ids:
            continue
        aliases.setdefault(cid, []).append(ticker)
        if row.get("primary_listing") is True or cid not in primary:
            primary[cid] = ticker
    evidence_by_id = {str(row.get("business_evidence_id")): row for row in evidence}
    evidence_by_company: dict[str, list[str]] = {}
    for row in evidence:
        if row.get("company_id") and row.get("business_evidence_id"):
            evidence_by_company.setdefault(str(row["company_id"]), []).append(
                str(row["business_evidence_id"])
            )
    records = []
    knowledge_records = {
        str(row["company_id"]): row for row in knowledge.get("records") or [] if row.get("company_id")
    }
    for missing_id in curated_overrides.keys() - knowledge_records.keys():
        knowledge_records[missing_id] = {
            "company_id": missing_id,
            "knowledge": [],
            "source_company_signal_status": "signals_available",
        }
    for source in knowledge_records.values():
        cid = str(source["company_id"])
        override = curated_overrides.get(cid)
        if company_ids is not None and cid not in company_ids and override is None:
            continue
        items = list(source.get("knowledge") or [])
        themes = sorted(
            (x for x in items if x.get("dimension") == "theme"),
            key=lambda x: (-float(x.get("confidence") or 0), str(x.get("knowledge_id"))),
        )
        sectors = sorted(
            (x for x in items if x.get("dimension") == "sector"),
            key=_sector_rank,
        )
        theme, sector = (themes[0] if themes else None), (sectors[0] if sectors else None)
        compatible_pairs = [
            (candidate_theme, candidate_sector)
            for candidate_theme in themes
            for candidate_sector in sectors
            if candidate_sector.get("knowledge_id")
            in compatibility.get(str(candidate_theme.get("knowledge_id")), [])
        ]
        if compatible_pairs:
            theme, sector = max(
                compatible_pairs,
                key=lambda pair: (
                    float(pair[0].get("confidence") or 0)
                    + float(pair[1].get("confidence") or 0),
                    float(pair[1].get("confidence") or 0),
                ),
            )
        if sector and sector.get("knowledge_id") in AI_INFRASTRUCTURE_SECTOR_IDS:
            theme = next(
                (item for item in themes if item.get("knowledge_id") == "theme:ai_infrastructure"),
                theme,
            )
        if override is not None:
            theme = {
                "knowledge_id": override["theme_id"],
                "canonical_name": override.get("theme_name") or override["theme_id"].split(":", 1)[-1],
                "confidence": float(override.get("confidence") or 1),
                "source_business_evidence_ids": [],
            }
            sector = {
                "knowledge_id": override["sector_id"],
                "canonical_name": override.get("sector_name") or override["sector_id"].split(":", 1)[-1],
                "confidence": float(override.get("confidence") or 1),
                "source_business_evidence_ids": [],
            }
        source_ids = sorted(
            {
                str(value)
                for item in (theme, sector)
                if item
                for value in item.get("source_business_evidence_ids") or []
            }
        )
        if override is not None and not source_ids:
            source_ids = sorted(evidence_by_company.get(cid, []))
        sources = [
            {
                "business_evidence_id": eid,
                "form": evidence_by_id.get(eid, {}).get("form"),
                "filing_date": evidence_by_id.get(eid, {}).get("filing_date"),
                "document_url": evidence_by_id.get(eid, {}).get("document_url"),
                "text_sha256": evidence_by_id.get(eid, {}).get("text_sha256"),
            }
            for eid in source_ids
        ]
        status = (
            "classified"
            if override is not None or (theme and sector and sources)
            else "evidence_available_unclassified"
            if source.get("source_company_signal_status") != "business_evidence_unavailable"
            else "awaiting_business_evidence"
        )
        company = company_by_id.get(cid, {})
        if not primary.get(cid):
            continue
        records.append(
            {
                "schema_version": "canonical-company-overview.v031c.6",
                "company_id": cid,
                "ticker": primary.get(cid),
                "ticker_aliases": sorted(set(aliases.get(cid, []))),
                "display_name": company.get("display_name") or company.get("legal_name"),
                "status": status,
                "path": {
                    "theme": None
                    if not theme
                    else {
                        "id": theme["knowledge_id"],
                        "name": theme["canonical_name"],
                        "display_name_zh_tw": names.get(
                            theme["knowledge_id"], theme["canonical_name"]
                        ),
                        "confidence": theme["confidence"],
                    },
                    "sector": None
                    if not sector
                    else {
                        "id": sector["knowledge_id"],
                        "name": sector["canonical_name"],
                        "display_name_zh_tw": names.get(
                            sector["knowledge_id"], sector["canonical_name"]
                        ),
                        "confidence": sector["confidence"],
                    },
                    "company": {
                        "company_id": cid,
                        "ticker": primary.get(cid),
                        "display_name": company.get("display_name") or company.get("legal_name"),
                    },
                },
                "evidence": sources,
                **({"classification_source": "curated_core_override"} if override is not None else {}),
                "reason_code": None
                if status == "classified"
                else "SEC_BUSINESS_EVIDENCE_PENDING"
                if status == "awaiting_business_evidence"
                else "NO_EVIDENCE_SUPPORTED_THEME_SECTOR_PATH",
            }
        )
    records.sort(key=lambda row: str(row.get("ticker") or row["company_id"]))
    return {
        "schema_version": "canonical-company-overview-index.v031c.6",
        "generated_at": current.isoformat(),
        "summary": {
            "company_count": len(records),
            "classified_count": sum(r["status"] == "classified" for r in records),
            "awaiting_evidence_count": sum(
                r["status"] == "awaiting_business_evidence" for r in records
            ),
        },
        "records": records,
    }


def write_company_overviews(report: Mapping[str, Any], output: Path) -> None:
    files = {}
    per_company = output / "per-company"
    expected_filenames = {
        f"{row['ticker']}.json" for row in report["records"] if row.get("ticker")
    }
    if per_company.is_dir():
        for stale in per_company.glob("*.json"):
            if stale.name not in expected_filenames:
                stale.unlink()
    for row in report["records"]:
        ticker = row.get("ticker")
        if not ticker:
            continue
        filename = f"{ticker}.json"
        for alias in row.get("ticker_aliases") or [ticker]:
            files[alias] = filename
        _write(per_company / filename, row)
    _write(
        output / "index.json",
        {
            "schema_version": report["schema_version"],
            "generated_at": report["generated_at"],
            "summary": report["summary"],
            "ticker_to_file": files,
        },
    )


class CompanyOverviewService:
    def __init__(self, *, root: Path | None = None):
        self.root = root or Path.cwd()

    def get(self, ticker: str) -> Mapping[str, Any]:
        symbol = str(ticker or "").strip().upper()
        index = _load(self.root / "data/generated/company_overview/index.json")
        filename = index.get("ticker_to_file", {}).get(symbol)
        if not filename:
            raise CompanyOverviewNotFound(f"company overview not found: {symbol}")
        return _load(self.root / "data/generated/company_overview/per-company" / filename)
