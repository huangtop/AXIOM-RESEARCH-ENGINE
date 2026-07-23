from __future__ import annotations

import gzip
import json
import re
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from axiom_engine.company_registry import import_company_universe
from axiom_engine.real_100_onboarding import load_cohort

SEC_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

# Cohort symbols may lag an official ticker change. Keep this mapping explicit,
# reviewable, and limited to verified corporate actions.
CURRENT_TICKER_ALIASES: dict[str, str] = {
    "MMC": "MRSH",  # Marsh McLennan changed its NYSE symbol on 2026-01-14.
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegistryBuildReport(StrictModel):
    cohort_id: str
    companies_requested: int
    companies_resolved: int
    securities_resolved: int
    unresolved_tickers: list[str]
    duplicate_tickers: list[str]
    source_file: str | None = None
    registry_directory: str | None = None
    dry_run: bool

    @model_validator(mode="after")
    def consistent(self) -> "RegistryBuildReport":
        if self.companies_resolved + len(self.unresolved_tickers) != self.companies_requested:
            raise ValueError("resolved and unresolved counts do not match requested count")
        return self


def _normalize_ticker(value: str) -> str:
    return value.strip().upper().replace(".", "-")


def _validate_user_agent(user_agent: str) -> None:
    if "@" not in user_agent:
        raise ValueError("SEC user agent must include a contact email")
    try:
        user_agent.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("SEC user agent must contain ASCII characters only") from exc
    if not re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", user_agent):
        raise ValueError("SEC user agent must include a valid contact email")


def _decode_http_body(body: bytes, content_encoding: str | None) -> bytes:
    encoding = (content_encoding or "").strip().lower()
    if encoding == "gzip" or body.startswith(b"\x1f\x8b"):
        return gzip.decompress(body)
    if encoding == "deflate":
        try:
            return zlib.decompress(body)
        except zlib.error:
            return zlib.decompress(body, -zlib.MAX_WBITS)
    return body


def _read_sec_payload(*, user_agent: str, sec_file: str | None) -> dict[str, Any]:
    if sec_file:
        return json.loads(Path(sec_file).read_text(encoding="utf-8"))
    _validate_user_agent(user_agent)
    request = urllib.request.Request(
        SEC_EXCHANGE_URL,
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        body = response.read()
        decoded = _decode_http_body(body, response.headers.get("Content-Encoding"))
        return json.loads(decoded.decode("utf-8"))


def _sec_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    fields = payload.get("fields")
    data = payload.get("data")
    if not isinstance(fields, list) or not isinstance(data, list):
        raise ValueError("invalid SEC company_tickers_exchange payload")
    required = {"cik", "name", "ticker", "exchange"}
    if not required.issubset(set(fields)):
        raise ValueError("SEC payload is missing required fields")
    return [dict(zip(fields, row, strict=True)) for row in data]


def build_real_100_registry(
    *,
    user_agent: str,
    cohort_path: str = "data/onboarding/us_real_100_cohort.json",
    sec_file: str | None = None,
    source_output: str = "data/onboarding/generated/real_100_company_registry_source.json",
    registry_dir: str = "data/company_registry",
    write: bool = False,
) -> RegistryBuildReport:
    if not sec_file:
        _validate_user_agent(user_agent)
    cohort = load_cohort(cohort_path)
    rows = _sec_rows(_read_sec_payload(user_agent=user_agent, sec_file=sec_file))
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_ticker.setdefault(_normalize_ticker(str(row["ticker"])), []).append(row)

    now = datetime.now(timezone.utc).isoformat()
    companies: list[dict[str, Any]] = []
    securities: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    unresolved: list[str] = []
    duplicates: list[str] = []

    for member in sorted(cohort.symbols, key=lambda item: item.rank):
        cohort_key = _normalize_ticker(member.ticker)
        lookup_key = CURRENT_TICKER_ALIASES.get(cohort_key, cohort_key)
        matches = by_ticker.get(lookup_key, [])
        if member.exchange_hint:
            hinted = [r for r in matches if str(r["exchange"]).upper() == member.exchange_hint.upper()]
            if hinted:
                matches = hinted
        if not matches:
            unresolved.append(member.ticker)
            continue
        if len(matches) > 1:
            duplicates.append(member.ticker)
        row = sorted(matches, key=lambda item: (str(item["exchange"]), str(item["cik"])))[0]
        cik = str(row["cik"]).zfill(10)
        exchange = str(row["exchange"]).upper()
        company_id = f"company:US-CIK{cik}"
        security_id = f"security:{exchange}-{cohort_key}"
        provenance_id = f"provenance:SEC-TICKER-EXCHANGE-{cik}-{lookup_key}"
        provenance.append({
            "provenance_id": provenance_id,
            "source_type": "regulator",
            "source_name": "SEC company_tickers_exchange.json",
            "source_record_id": f"{cik}:{lookup_key}:{exchange}",
            "retrieved_at": now,
            "source_url": SEC_EXCHANGE_URL,
        })
        companies.append({
            "company_id": company_id,
            "legal_name": str(row["name"]),
            "display_name": str(row["name"]),
            "country": "US",
            "provenance_ids": [provenance_id],
            "metadata": {
                "cik": cik,
                "cohort_id": cohort.cohort_id,
                "cohort_rank": member.rank,
                "sec_current_ticker": lookup_key,
                "ticker_alias_applied": lookup_key != cohort_key,
            },
        })
        securities.append({
            "security_id": security_id,
            "company_id": company_id,
            "exchange": exchange,
            "ticker": member.ticker,
            "currency": "USD",
            "security_type": "common_stock",
            "primary_listing": True,
            "provenance_ids": [provenance_id],
        })

    source = {
        "schema_version": "1.0.0",
        "as_of_date": now[:10],
        "source_name": "SEC Real 100 Company Registry Builder",
        "provenance": provenance,
        "companies": companies,
        "securities": securities,
    }
    source_path = Path(source_output)
    if write:
        if unresolved:
            raise ValueError(f"cannot write incomplete real-100 registry; unresolved={unresolved}")
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        import_company_universe(source_path, output_dir=registry_dir, dry_run=False)

    return RegistryBuildReport(
        cohort_id=cohort.cohort_id,
        companies_requested=len(cohort.symbols),
        companies_resolved=len(companies),
        securities_resolved=len(securities),
        unresolved_tickers=unresolved,
        duplicate_tickers=sorted(set(duplicates)),
        source_file=str(source_path) if write else None,
        registry_directory=registry_dir if write else None,
        dry_run=not write,
    )


def validate_real_100_registry(
    cohort_path: str = "data/onboarding/us_real_100_cohort.json",
    registry_dir: str = "data/company_registry",
) -> dict[str, Any]:
    cohort = load_cohort(cohort_path)
    root = Path(registry_dir)
    companies = json.loads((root / "companies.json").read_text(encoding="utf-8"))
    securities = json.loads((root / "securities.json").read_text(encoding="utf-8"))
    company_ids = {row["company_id"] for row in companies}
    by_ticker = {str(row["ticker"]).upper(): row for row in securities}
    missing = [member.ticker for member in cohort.symbols if member.ticker.upper() not in by_ticker]
    invalid_links = [row["security_id"] for row in securities if row["company_id"] not in company_ids]
    cohort_company_ids = {by_ticker[m.ticker.upper()]["company_id"] for m in cohort.symbols if m.ticker.upper() in by_ticker}
    result = {
        "cohort_id": cohort.cohort_id,
        "companies_requested": len(cohort.symbols),
        "companies_resolved": len(cohort_company_ids),
        "securities_resolved": len(cohort.symbols) - len(missing),
        "missing_tickers": missing,
        "invalid_security_links": invalid_links,
        "acceptance_passed": not missing and not invalid_links and len(cohort_company_ids) == len(cohort.symbols),
    }
    return result
