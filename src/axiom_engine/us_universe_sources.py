from __future__ import annotations

import csv
import io
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


class USUniverseSourceError(RuntimeError):
    """Raised when an official US universe source cannot be fetched or parsed."""


@dataclass(frozen=True, slots=True)
class USListingSourceRecord:
    ticker: str
    exchange: str
    security_name: str
    cik: int | None = None
    legal_name: str | None = None
    source_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "exchange": self.exchange,
            "security_name": self.security_name,
            "cik": self.cik,
            "legal_name": self.legal_name,
            "source_ids": list(self.source_ids),
        }


@dataclass(frozen=True, slots=True)
class USUniverseSourceSnapshot:
    records: tuple[USListingSourceRecord, ...]
    source_urls: tuple[str, ...]

    def write_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "1.0.0",
            "sources": list(self.source_urls),
            "record_count": len(self.records),
            "records": [record.to_dict() for record in self.records],
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target


class OfficialUSUniverseSourceClient:
    """Fetch and normalize official SEC and Nasdaq Trader listing sources.

    This layer intentionally produces a source snapshot only. It does not write
    canonical Universe company/security files; Commit-005B will perform that
    transformation through UniverseImporter.
    """

    def __init__(
        self,
        *,
        user_agent: str,
        fetch_text: Callable[[str, str], str] | None = None,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("user_agent is required for official data access")
        self.user_agent = user_agent.strip()
        self._fetch_text = fetch_text or _download_text

    def build_snapshot(self) -> USUniverseSourceSnapshot:
        nasdaq_text = self._fetch_text(NASDAQ_LISTED_URL, self.user_agent)
        other_text = self._fetch_text(OTHER_LISTED_URL, self.user_agent)
        sec_text = self._fetch_text(SEC_COMPANY_TICKERS_URL, self.user_agent)
        records = merge_official_sources(nasdaq_text, other_text, sec_text)
        return USUniverseSourceSnapshot(
            records=records,
            source_urls=(NASDAQ_LISTED_URL, OTHER_LISTED_URL, SEC_COMPANY_TICKERS_URL),
        )


def _download_text(url: str, user_agent: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.read().decode("utf-8-sig")
    except Exception as exc:  # pragma: no cover - network behavior is environment-dependent
        raise USUniverseSourceError(f"failed to fetch official source: {url}") from exc


def parse_nasdaq_listed(text: str) -> tuple[USListingSourceRecord, ...]:
    rows = _pipe_rows(text)
    records: list[USListingSourceRecord] = []
    for row in rows:
        symbol = row.get("Symbol", "").strip().upper()
        if not symbol or symbol.startswith("FILE CREATION TIME"):
            continue
        if row.get("Test Issue", "N").strip().upper() == "Y":
            continue
        if row.get("ETF", "N").strip().upper() == "Y":
            continue
        records.append(
            USListingSourceRecord(
                ticker=symbol,
                exchange="NASDAQ",
                security_name=row.get("Security Name", "").strip(),
                source_ids=("nasdaq_trader:nasdaqlisted",),
            )
        )
    return tuple(records)


def parse_other_listed(text: str) -> tuple[USListingSourceRecord, ...]:
    exchange_map = {"N": "NYSE", "A": "NYSE_AMERICAN"}
    rows = _pipe_rows(text)
    records: list[USListingSourceRecord] = []
    for row in rows:
        symbol = row.get("ACT Symbol", "").strip().upper()
        if not symbol or symbol.startswith("FILE CREATION TIME"):
            continue
        exchange = exchange_map.get(row.get("Exchange", "").strip().upper())
        if exchange is None:
            continue
        if row.get("Test Issue", "N").strip().upper() == "Y":
            continue
        if row.get("ETF", "N").strip().upper() == "Y":
            continue
        records.append(
            USListingSourceRecord(
                ticker=symbol,
                exchange=exchange,
                security_name=row.get("Security Name", "").strip(),
                source_ids=("nasdaq_trader:otherlisted",),
            )
        )
    return tuple(records)


def parse_sec_company_tickers(text: str) -> dict[str, tuple[int, str]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise USUniverseSourceError("invalid SEC company_tickers JSON") from exc
    if not isinstance(payload, dict):
        raise USUniverseSourceError("SEC company_tickers payload must be an object")
    result: dict[str, tuple[int, str]] = {}
    for item in payload.values():
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker", "")).strip().upper()
        title = str(item.get("title", "")).strip()
        try:
            cik = int(item["cik_str"])
        except (KeyError, TypeError, ValueError):
            continue
        if ticker:
            result[ticker] = (cik, title)
    return result


def merge_official_sources(
    nasdaq_text: str,
    other_text: str,
    sec_text: str,
) -> tuple[USListingSourceRecord, ...]:
    sec = parse_sec_company_tickers(sec_text)
    listings = (*parse_nasdaq_listed(nasdaq_text), *parse_other_listed(other_text))
    merged: list[USListingSourceRecord] = []
    seen: set[tuple[str, str]] = set()
    for record in listings:
        key = (record.exchange, record.ticker)
        if key in seen:
            raise USUniverseSourceError(f"duplicate official listing key: {record.exchange}:{record.ticker}")
        seen.add(key)
        cik, legal_name = sec.get(record.ticker, (None, None))
        source_ids = record.source_ids
        if cik is not None:
            source_ids = (*source_ids, "sec:company_tickers")
        merged.append(
            USListingSourceRecord(
                ticker=record.ticker,
                exchange=record.exchange,
                security_name=record.security_name,
                cik=cik,
                legal_name=legal_name,
                source_ids=source_ids,
            )
        )
    return tuple(sorted(merged, key=lambda item: (item.exchange, item.ticker)))


def _pipe_rows(text: str) -> Iterable[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    if reader.fieldnames is None:
        raise USUniverseSourceError("official symbol directory has no header")
    for row in reader:
        yield {str(key): "" if value is None else value for key, value in row.items()}
