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


def _primary_business_score(item: Mapping[str, Any]) -> int:
    """Rank what the company sells above technologies/end markets it mentions."""
    if "primary_business_score" in item:
        return int(item.get("primary_business_score") or 0)
    source_ids = {str(value) for value in item.get("source_signal_ids") or []}
    if any(value.startswith("product:") for value in source_ids):
        return 2
    if any(
        value.startswith(("capability:", "infrastructure:")) for value in source_ids
    ):
        return 1
    return 0


def _business_signal_kind_rank(item: Mapping[str, Any]) -> int:
    """Prefer a sold product over an enabling capability or mentioned use."""
    source_ids = {str(value) for value in item.get("source_signal_ids") or []}
    if any(value.startswith("product:") for value in source_ids):
        return 2
    if any(value.startswith(("capability:", "infrastructure:")) for value in source_ids):
        return 1
    return 0


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompanyOverviewError(f"cannot read {path}: {exc}") from exc


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_official_classifications(root: Path) -> dict[str, dict[str, Any]]:
    """
    Load authoritative source classifications without projecting them into
    AXIOM theme/sector taxonomy.

    SEC SIC is a separate classification layer. It may be used as a full-market
    industry baseline and validation signal, but it must never masquerade as an
    inferred AXIOM sector.
    """
    path = (
        root
        / "data/generated/canonical_company_evidence/"
        "official_classifications.json"
    )
    if not path.is_file():
        return {}

    payload = _load(path)
    if not isinstance(payload, list):
        raise CompanyOverviewError(
            "official classifications input must be an array"
        )

    output: dict[str, dict[str, Any]] = {}

    for row in payload:
        if not isinstance(row, Mapping):
            continue
        company_id = str(row.get("company_id") or "")
        if not company_id:
            continue
        if str(row.get("classification_scheme") or "") != "SEC_SIC":
            continue

        output[company_id] = {
            "classification_id": row.get("classification_id"),
            "scheme": row.get("classification_scheme"),
            "code": row.get("classification_code"),
            "label": row.get("classification_label"),
            "authority": row.get("authority"),
            "observed_at": row.get("observed_at"),
            "provenance_ids": list(row.get("provenance_ids") or []),
        }

    return output


def build_company_overviews(
    root: Path,
    *,
    company_ids: set[str] | None = None,
    knowledge_payload: Mapping[str, Any] | None = None,
    respect_existing_locks: bool = True,
    strict_company_scope: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    companies = _load(root / "data/universe/companies.json")
    securities = _load(root / "data/universe/securities.json")
    knowledge = knowledge_payload or _load(
        root / "data/generated/knowledge_inference/knowledge_inference.json"
    )
    evidence = load_business_evidence(
        root / "data/generated/canonical_business_evidence"
    )
    policy = _load(root / "config/company_overview.v031c.6.json")
    quality_path = root / "config/classification_quality.v031c.5.json"
    quality_policy = _load(quality_path) if quality_path.is_file() else {}
    compatibility = quality_policy.get("theme_sector_compatibility") or {}
    official_by_company = _load_official_classifications(root)

    identity_path = (
        root
        / "data/generated/security_identity/"
        "security_identity_normalization.json"
    )
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
        if row.get("company_id")
        and row.get("theme_id")
        and row.get("sector_id")
    }

    # Existing automatic locks are retained only when callers explicitly ask
    # for them. Full-market production rebuilds may set
    # respect_existing_locks=False to re-evaluate stale automatic paths.
    locked_by_company: dict[str, dict[str, Any]] = {}
    existing_dir = root / "data/generated/company_overview/per-company"
    if respect_existing_locks and existing_dir.is_dir():
        for existing_path in existing_dir.glob("*.json"):
            try:
                existing = _load(existing_path)
            except CompanyOverviewError:
                continue
            existing_company_id = str(existing.get("company_id") or "")
            if existing_company_id and existing.get("status") == "classified":
                locked_by_company[existing_company_id] = dict(existing)

    company_by_id = {
        str(row["company_id"]): row
        for row in companies
    }

    primary: dict[str, str] = {}
    aliases: dict[str, list[str]] = {}

    for row in securities:
        cid = str(row.get("company_id") or "")
        ticker = str(row.get("ticker") or "").upper()
        if (
            not cid
            or not ticker
            or str(row.get("status") or "active").lower() != "active"
        ):
            continue
        if (
            eligible_security_ids is not None
            and str(row.get("security_id") or "") not in eligible_security_ids
        ):
            continue

        aliases.setdefault(cid, []).append(ticker)
        if row.get("primary_listing") is True or cid not in primary:
            primary[cid] = ticker

    evidence_by_id = {
        str(row.get("business_evidence_id")): row
        for row in evidence
    }

    evidence_by_company: dict[str, list[str]] = {}
    for row in evidence:
        if row.get("company_id") and row.get("business_evidence_id"):
            evidence_by_company.setdefault(
                str(row["company_id"]),
                [],
            ).append(
                str(row["business_evidence_id"])
            )

    records: list[dict[str, Any]] = []

    knowledge_records = {
        str(row["company_id"]): row
        for row in knowledge.get("records") or []
        if row.get("company_id")
    }

    for missing_id in curated_overrides.keys() - knowledge_records.keys():
        knowledge_records[missing_id] = {
            "company_id": missing_id,
            "knowledge": [],
            "source_company_signal_status": "signals_available",
        }

    for locked_id in locked_by_company.keys() - knowledge_records.keys():
        knowledge_records[locked_id] = {
            "company_id": locked_id,
            "knowledge": [],
            "source_company_signal_status": "signals_available",
        }

    for source in knowledge_records.values():
        cid = str(source["company_id"])
        override = curated_overrides.get(cid)
        locked = locked_by_company.get(cid) if override is None else None

        if (
            company_ids is not None
            and cid not in company_ids
            and (
                strict_company_scope
                or (
                    override is None
                    and locked is None
                )
            )
        ):
            continue

        items = list(source.get("knowledge") or [])

        themes = sorted(
            (
                item
                for item in items
                if item.get("dimension") == "theme"
            ),
            key=lambda item: (
                -float(item.get("confidence") or 0),
                str(item.get("knowledge_id")),
            ),
        )

        sectors = sorted(
            (
                item
                for item in items
                if item.get("dimension") == "sector"
            ),
            key=_sector_rank,
        )

        theme = themes[0] if themes else None
        sector = sectors[0] if sectors else None

        compatible_pairs = [
            (
                candidate_theme,
                candidate_sector,
            )
            for candidate_theme in themes
            for candidate_sector in sectors
            if candidate_sector.get("knowledge_id")
            in compatibility.get(
                str(candidate_theme.get("knowledge_id")),
                [],
            )
        ]

        if compatible_pairs:
            theme, sector = max(
                compatible_pairs,
                key=lambda pair: (
                    _primary_business_score(pair[0]),
                    _primary_business_score(pair[1]),
                    _business_signal_kind_rank(pair[1]),
                    float(pair[0].get("confidence") or 0)
                    + float(pair[1].get("confidence") or 0),
                    float(pair[1].get("confidence") or 0),
                ),
            )

        if (
            sector
            and sector.get("knowledge_id") in AI_INFRASTRUCTURE_SECTOR_IDS
        ):
            theme = next(
                (
                    item
                    for item in themes
                    if item.get("knowledge_id")
                    == "theme:ai_infrastructure"
                ),
                theme,
            )

        if override is not None:
            theme = {
                "knowledge_id": override["theme_id"],
                "canonical_name": (
                    override.get("theme_name")
                    or override["theme_id"].split(":", 1)[-1]
                ),
                "confidence": float(
                    override.get("confidence")
                    or 1
                ),
                "source_business_evidence_ids": [],
            }
            sector = {
                "knowledge_id": override["sector_id"],
                "canonical_name": (
                    override.get("sector_name")
                    or override["sector_id"].split(":", 1)[-1]
                ),
                "confidence": float(
                    override.get("confidence")
                    or 1
                ),
                "source_business_evidence_ids": [],
            }

        source_ids = sorted(
            {
                str(value)
                for item in (theme, sector)
                if item
                for value in (
                    item.get("source_business_evidence_ids")
                    or []
                )
            }
        )

        if override is not None and not source_ids:
            source_ids = sorted(
                evidence_by_company.get(
                    cid,
                    [],
                )
            )

        sources = [
            {
                "business_evidence_id": eid,
                "form": evidence_by_id.get(eid, {}).get("form"),
                "filing_date": evidence_by_id.get(eid, {}).get(
                    "filing_date"
                ),
                "document_url": evidence_by_id.get(eid, {}).get(
                    "document_url"
                ),
                "text_sha256": evidence_by_id.get(eid, {}).get(
                    "text_sha256"
                ),
            }
            for eid in source_ids
        ]

        status = (
            "classified"
            if (
                override is not None
                or (
                    theme
                    and sector
                    and sources
                    and (
                        "primary_business_score" not in sector
                        or _primary_business_score(sector) > 0
                    )
                )
            )
            else (
                "evidence_available_unclassified"
                if source.get("source_company_signal_status")
                != "business_evidence_unavailable"
                else "awaiting_business_evidence"
            )
        )

        company = company_by_id.get(cid, {})

        if not primary.get(cid):
            continue

        official_industry = official_by_company.get(cid)

        record = {
            "schema_version": "canonical-company-overview.v031c.6",
            "company_id": cid,
            "ticker": primary.get(cid),
            "ticker_aliases": sorted(
                set(
                    aliases.get(
                        cid,
                        [],
                    )
                )
            ),
            "display_name": (
                company.get("display_name")
                or company.get("legal_name")
            ),
            "status": status,
            "official_industry": official_industry,
            "path": {
                "theme": (
                    None
                    if not theme
                    else {
                        "id": theme["knowledge_id"],
                        "name": theme["canonical_name"],
                        "display_name_zh_tw": names.get(
                            theme["knowledge_id"],
                            theme["canonical_name"],
                        ),
                        "confidence": theme["confidence"],
                    }
                ),
                "sector": (
                    None
                    if not sector
                    else {
                        "id": sector["knowledge_id"],
                        "name": sector["canonical_name"],
                        "display_name_zh_tw": names.get(
                            sector["knowledge_id"],
                            sector["canonical_name"],
                        ),
                        "confidence": sector["confidence"],
                    }
                ),
                "company": {
                    "company_id": cid,
                    "ticker": primary.get(cid),
                    "display_name": (
                        company.get("display_name")
                        or company.get("legal_name")
                    ),
                },
            },
            "evidence": sources,
            **(
                {
                    "classification_source": "curated_core_override",
                }
                if override is not None
                else {}
            ),
            "reason_code": (
                None
                if status == "classified"
                else (
                    "SEC_BUSINESS_EVIDENCE_PENDING"
                    if status == "awaiting_business_evidence"
                    else "NO_EVIDENCE_SUPPORTED_THEME_SECTOR_PATH"
                )
            ),
        }

        if locked is not None:
            record["status"] = "classified"
            record["path"] = locked["path"]
            record["evidence"] = list(
                locked.get("evidence")
                or []
            )
            record["classification_source"] = locked.get(
                "classification_source",
                "locked_published_classification",
            )
            record["reason_code"] = None

            # Do not preserve a stale/missing official baseline from the lock.
            # Official classification is source evidence and must be refreshed
            # from canonical_company_evidence on every rebuild.
            record["official_industry"] = official_industry

        if record["status"] == "classified":
            record["classification_lock"] = {
                "status": "locked",
                "update_mode": "manual_override_only",
            }

        records.append(record)

    records.sort(
        key=lambda row: str(
            row.get("ticker")
            or row["company_id"]
        )
    )

    return {
        "schema_version": "canonical-company-overview-index.v031c.6",
        "generated_at": current.isoformat(),
        "summary": {
            "company_count": len(records),
            "classified_count": sum(
                row["status"] == "classified"
                for row in records
            ),
            "official_industry_count": sum(
                row.get("official_industry") is not None
                for row in records
            ),
            "evidence_available_unclassified_count": sum(
                row["status"] == "evidence_available_unclassified"
                for row in records
            ),
            "awaiting_evidence_count": sum(
                row["status"] == "awaiting_business_evidence"
                for row in records
            ),
        },
        "records": records,
    }


def write_company_overviews(
    report: Mapping[str, Any],
    output: Path,
    *,
    preserve_existing: bool = False,
) -> None:
    files: dict[str, str] = {}
    per_company = output / "per-company"

    expected_filenames = {
        f"{row['ticker']}.json"
        for row in report["records"]
        if row.get("ticker")
    }

    if per_company.is_dir() and not preserve_existing:
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

        _write(
            per_company / filename,
            row,
        )

    index_path = output / "index.json"

    if preserve_existing and index_path.is_file():
        existing_index = _load(index_path)
        existing_files = dict(
            existing_index.get("ticker_to_file")
            or {}
        )
        existing_files.update(files)
        existing_index["generated_at"] = report["generated_at"]
        existing_index["ticker_to_file"] = existing_files
        _write(
            index_path,
            existing_index,
        )
    else:
        _write(
            index_path,
            {
                "schema_version": report["schema_version"],
                "generated_at": report["generated_at"],
                "summary": report["summary"],
                "ticker_to_file": files,
            },
        )


class CompanyOverviewService:
    def __init__(
        self,
        *,
        root: Path | None = None,
    ):
        self.root = root or Path.cwd()

    def get(
        self,
        ticker: str,
    ) -> Mapping[str, Any]:
        symbol = str(
            ticker
            or ""
        ).strip().upper()

        index = _load(
            self.root
            / "data/generated/company_overview/index.json"
        )

        filename = (
            index.get(
                "ticker_to_file",
                {},
            ).get(symbol)
        )

        if not filename:
            raise CompanyOverviewNotFound(
                f"company overview not found: {symbol}"
            )

        return _load(
            self.root
            / "data/generated/company_overview/per-company"
            / filename
        )