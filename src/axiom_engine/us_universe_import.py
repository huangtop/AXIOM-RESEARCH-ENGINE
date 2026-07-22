from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models.universe import CompanyMaster, ResearchLevel, SecurityMaster
from .universe_import import UniverseImportBundle
from .us_universe_sources import USListingSourceRecord, USUniverseSourceError

_EXCHANGE_PRIORITY = {"NASDAQ": 0, "NYSE": 1, "NYSE_AMERICAN": 2}


@dataclass(frozen=True, slots=True)
class USUniverseTransformReport:
    source_path: Path
    input_records: int
    company_count: int
    security_count: int
    cik_company_count: int
    fallback_company_count: int


def load_source_snapshot(path: str | Path) -> tuple[USListingSourceRecord, ...]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise USUniverseSourceError(f"cannot read US universe source snapshot: {source}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise USUniverseSourceError("US universe source snapshot must contain a records array")
    records: list[USListingSourceRecord] = []
    for index, item in enumerate(payload["records"], start=1):
        if not isinstance(item, dict):
            raise USUniverseSourceError(f"source record {index} must be an object")
        try:
            ticker = str(item["ticker"]).strip().upper()
            exchange = str(item["exchange"]).strip().upper()
            security_name = str(item["security_name"]).strip()
            cik_raw = item.get("cik")
            cik = None if cik_raw in (None, "") else int(cik_raw)
            legal_name_raw = item.get("legal_name")
            legal_name = None if legal_name_raw in (None, "") else str(legal_name_raw).strip()
            source_ids_raw = item.get("source_ids", [])
            if not isinstance(source_ids_raw, list):
                raise TypeError("source_ids must be an array")
        except (KeyError, TypeError, ValueError) as exc:
            raise USUniverseSourceError(f"invalid source record {index}: {exc}") from exc
        if not ticker or not exchange or not security_name:
            raise USUniverseSourceError(f"source record {index} has blank required fields")
        records.append(
            USListingSourceRecord(
                ticker=ticker,
                exchange=exchange,
                security_name=security_name,
                cik=cik,
                legal_name=legal_name,
                source_ids=tuple(str(value) for value in source_ids_raw),
            )
        )
    return tuple(records)


def transform_us_source_records(
    records: Iterable[USListingSourceRecord],
) -> UniverseImportBundle:
    source_records = tuple(records)
    grouped: dict[str, list[USListingSourceRecord]] = {}
    for record in source_records:
        grouped.setdefault(_company_key(record), []).append(record)

    companies: list[CompanyMaster] = []
    securities: list[SecurityMaster] = []
    seen_security_ids: set[str] = set()

    for company_key in sorted(grouped):
        listings = sorted(
            grouped[company_key],
            key=lambda item: (_EXCHANGE_PRIORITY.get(item.exchange, 99), item.ticker),
        )
        primary = listings[0]
        company_id = _company_id(primary)
        primary_security_id = _security_id(primary)
        source_ids = sorted({source_id for item in listings for source_id in item.source_ids})
        cik = next((item.cik for item in listings if item.cik is not None), None)
        legal_name = next((item.legal_name for item in listings if item.legal_name), None)
        legal_name = legal_name or _clean_security_name(primary.security_name)

        companies.append(
            CompanyMaster(
                company_id=company_id,
                legal_name=legal_name,
                display_name=_clean_security_name(primary.security_name),
                country="US",
                primary_security_id=primary_security_id,
                research_level=ResearchLevel.NONE,
                metadata={
                    "cik": cik,
                    "import_source": "official_us_universe_snapshot",
                    "source_ids": source_ids,
                    "listing_count": len(listings),
                },
            )
        )
        for listing in listings:
            security_id = _security_id(listing)
            if security_id in seen_security_ids:
                raise USUniverseSourceError(f"duplicate generated security ID: {security_id}")
            seen_security_ids.add(security_id)
            securities.append(
                SecurityMaster(
                    security_id=security_id,
                    company_id=company_id,
                    exchange=listing.exchange,
                    ticker=listing.ticker,
                    currency="USD",
                    primary_listing=security_id == primary_security_id,
                    metadata={
                        "security_name": listing.security_name,
                        "cik": listing.cik,
                        "source_ids": list(listing.source_ids),
                        "import_source": "official_us_universe_snapshot",
                    },
                )
            )

    return UniverseImportBundle(
        companies=tuple(sorted(companies, key=lambda item: item.company_id)),
        securities=tuple(sorted(securities, key=lambda item: item.security_id)),
    )


def build_us_universe_import(
    source_path: str | Path,
    output_path: str | Path,
) -> USUniverseTransformReport:
    source = Path(source_path)
    records = load_source_snapshot(source)
    bundle = transform_us_source_records(records)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "source": "official_us_universe_snapshot",
        "companies": [item.model_dump(mode="json") for item in bundle.companies],
        "securities": [item.model_dump(mode="json") for item in bundle.securities],
        "valuation_profile_assignments": [],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cik_count = sum(1 for company in bundle.companies if company.metadata.get("cik") is not None)
    return USUniverseTransformReport(
        source_path=source,
        input_records=len(records),
        company_count=len(bundle.companies),
        security_count=len(bundle.securities),
        cik_company_count=cik_count,
        fallback_company_count=len(bundle.companies) - cik_count,
    )


def _company_key(record: USListingSourceRecord) -> str:
    if record.cik is not None:
        return f"cik:{record.cik:010d}"
    return f"listing:{record.exchange}:{record.ticker}"


def _company_id(record: USListingSourceRecord) -> str:
    if record.cik is not None:
        return f"company:US-CIK{record.cik:010d}"

    exchange = _canonical_exchange(record.exchange)

    return f"company:US-{exchange}-{_safe_token(record.ticker)}"

def _security_id(record: USListingSourceRecord) -> str:
    exchange = _canonical_exchange(record.exchange)
    return f"security:{exchange}-{_safe_token(record.ticker)}"

def _canonical_exchange(exchange: str) -> str:
    normalized = exchange.strip().upper()

    mapping = {
        "NASDAQ": "NASDAQ",
        "NYSE": "NYSE",
        "NYSE_AMERICAN": "NYSE-AMERICAN",
        "NYSE_ARCA": "NYSE-ARCA",
        "NYSE_MKT": "NYSE-MKT",
    }

    return mapping.get(normalized, normalized.replace("_", "-"))

def _safe_token(value: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise USUniverseSourceError(f"cannot create stable ID from value: {value!r}")
    parts: list[str] = []
    for char in normalized:
        if char.isascii() and (char.isalnum() or char in ".-"):
            parts.append(char)
        else:
            parts.append(f"~{ord(char):X}~")
    return "".join(parts)


def _clean_security_name(value: str) -> str:
    cleaned = re.sub(
        (
            r"\s*[-–]\s*(Common Stock|Class [A-Z] Common Stock|Ordinary Shares|"
            r"American Depositary Shares).*$"
        ),
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or value.strip()
