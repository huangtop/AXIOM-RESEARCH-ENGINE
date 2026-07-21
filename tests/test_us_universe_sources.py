from __future__ import annotations

import gzip
import json
import zlib
from pathlib import Path

import pytest

from axiom_engine.us_universe_sources import (
    OfficialUSUniverseSourceClient,
    _download_text,
    USUniverseSourceError,
    merge_official_sources,
    parse_nasdaq_listed,
    parse_other_listed,
    parse_sec_company_tickers,
)

NASDAQ = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
ACME|Acme Corporation - Common Stock|Q|N|N|100|N|N
TEST|Nasdaq Test Stock|Q|Y|N|100|N|N
ETF1|Example ETF|G|N|N|100|Y|N
File Creation Time: 0721202621:32|||||||
"""

OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BETA|Beta Holdings Common Stock|N|BETA|N|100|N|BETA
GAMMA|Gamma Inc Common Stock|A|GAMMA|N|100|N|GAMMA
ARCA|Arca Example|P|ARCA|N|100|N|ARCA
File Creation Time: 0721202621:32|||||||
"""

SEC = json.dumps(
    {
        "0": {"cik_str": 1001, "ticker": "ACME", "title": "Acme Corporation"},
        "1": {"cik_str": 1002, "ticker": "BETA", "title": "Beta Holdings, Inc."},
    }
)


def test_parse_nasdaq_filters_test_issues_and_etfs() -> None:
    records = parse_nasdaq_listed(NASDAQ)
    assert [(item.exchange, item.ticker) for item in records] == [("NASDAQ", "ACME")]


def test_parse_other_listed_keeps_only_nyse_and_american() -> None:
    records = parse_other_listed(OTHER)
    assert [(item.exchange, item.ticker) for item in records] == [
        ("NYSE", "BETA"),
        ("NYSE_AMERICAN", "GAMMA"),
    ]


def test_parse_sec_company_tickers() -> None:
    assert parse_sec_company_tickers(SEC)["ACME"] == (1001, "Acme Corporation")


def test_merge_enriches_listings_with_sec_identity() -> None:
    records = merge_official_sources(NASDAQ, OTHER, SEC)
    acme = next(item for item in records if item.ticker == "ACME")
    gamma = next(item for item in records if item.ticker == "GAMMA")
    assert acme.cik == 1001
    assert acme.legal_name == "Acme Corporation"
    assert gamma.cik is None


def test_duplicate_exchange_ticker_is_rejected() -> None:
    duplicate = NASDAQ.replace("ACME|", "ACME|", 1).replace(
        "File Creation Time", "ACME|Duplicate|Q|N|N|100|N|N\nFile Creation Time"
    )
    with pytest.raises(USUniverseSourceError, match="duplicate official listing key"):
        merge_official_sources(duplicate, OTHER, SEC)


def test_client_uses_injected_fetcher_and_writes_snapshot(tmp_path: Path) -> None:
    payloads = {
        "nasdaqlisted.txt": NASDAQ,
        "otherlisted.txt": OTHER,
        "company_tickers.json": SEC,
    }

    def fetch(url: str, user_agent: str) -> str:
        assert user_agent == "AXIOM test@example.com"
        return payloads[url.rsplit("/", 1)[-1]]

    snapshot = OfficialUSUniverseSourceClient(
        user_agent="AXIOM test@example.com", fetch_text=fetch
    ).build_snapshot()
    target = snapshot.write_json(tmp_path / "snapshot.json")
    result = json.loads(target.read_text())
    assert result["record_count"] == 3
    assert len(result["sources"]) == 3


def test_user_agent_is_required() -> None:
    with pytest.raises(ValueError, match="user_agent"):
        OfficialUSUniverseSourceClient(user_agent=" ")


class _FakeResponse:
    def __init__(self, body: bytes, content_encoding: str | None = None) -> None:
        self._body = body
        self.headers = {} if content_encoding is None else {"Content-Encoding": content_encoding}

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_download_text_plain_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "axiom_engine.us_universe_sources.urllib.request.urlopen",
        lambda *_args, **_kwargs: _FakeResponse("plain text".encode()),
    )
    assert _download_text("https://example.test/plain", "AXIOM test@example.com") == "plain text"


def test_download_text_utf8_bom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "axiom_engine.us_universe_sources.urllib.request.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(b"\xef\xbb\xbfwith bom"),
    )
    assert _download_text("https://example.test/bom", "AXIOM test@example.com") == "with bom"


def test_download_text_gzip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "axiom_engine.us_universe_sources.urllib.request.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(gzip.compress(b"gzip text"), "gzip"),
    )
    assert _download_text("https://example.test/gzip", "AXIOM test@example.com") == "gzip text"


def test_download_text_deflate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "axiom_engine.us_universe_sources.urllib.request.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(zlib.compress(b"deflate text"), "deflate"),
    )
    assert _download_text("https://example.test/deflate", "AXIOM test@example.com") == "deflate text"
