from __future__ import annotations

import json
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from axiom_engine.yahoo_market_data import (
    YahooMarketDataAdapter,
    YahooMarketDataConfig,
    YahooMarketDataHTTPError,
    YahooMarketDataResponseError,
    YahooSymbolNotFoundError,
    normalize_yahoo_symbol,
)

SAMPLE_QUOTES: dict[str, Any] = {
    "quoteResponse": {
        "result": [
            {
                "symbol": "AAPL",
                "longName": "Apple Inc.",
                "currency": "USD",
                "fullExchangeName": "NasdaqGS",
                "quoteType": "EQUITY",
                "regularMarketTime": 1784709000,
                "regularMarketPrice": 225.5,
                "regularMarketPreviousClose": 223.1,
                "marketCap": 3_390_000_000_000,
                "sharesOutstanding": 15_040_000_000,
                "epsTrailingTwelveMonths": 6.42,
                "epsForward": 8.75,
                "trailingPE": 35.1246,
                "forwardPE": 25.7714,
                "priceToBook": 52.1,
                "enterpriseValue": 3_410_000_000_000,
                "enterpriseToRevenue": 8.4,
                "enterpriseToEbitda": 25.2,
                "beta": 1.21,
                "fiftyTwoWeekLow": 164.08,
                "fiftyTwoWeekHigh": 260.1,
            },
            {
                "symbol": "MSFT",
                "shortName": "Microsoft",
                "currency": "USD",
                "regularMarketTime": 1784709000,
                "regularMarketPrice": 510.25,
            },
        ],
        "error": None,
    }
}


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.body = json.dumps(payload).encode()

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_normalize_yahoo_symbol() -> None:
    assert normalize_yahoo_symbol(" brk-b ") == "BRK-B"
    with pytest.raises(ValueError, match="empty"):
        normalize_yahoo_symbol(" ")
    with pytest.raises(ValueError, match="whitespace"):
        normalize_yahoo_symbol("BRK B")


def test_snapshot_builds_request_and_normalizes_quote() -> None:
    observed: dict[str, object] = {}

    def opener(request: object, *, timeout: float) -> FakeResponse:
        observed["url"] = request.full_url  # type: ignore[attr-defined]
        observed["agent"] = request.get_header("User-agent")  # type: ignore[attr-defined]
        observed["timeout"] = timeout
        return FakeResponse(SAMPLE_QUOTES)

    adapter = YahooMarketDataAdapter(opener=opener)
    snapshot = adapter.snapshot("aapl")

    assert snapshot.symbol == "AAPL"
    assert snapshot.company_name == "Apple Inc."
    assert str(snapshot.regular_market_price) == "225.5"
    assert str(snapshot.forward_earnings_per_share) == "8.75"
    assert snapshot.provider == "yahoo_finance"
    assert observed == {
        "url": "https://query1.finance.yahoo.com/v7/finance/quote?symbols=AAPL",
        "agent": "AXIOM-Research-Engine/0.7",
        "timeout": 15.0,
    }


def test_snapshots_preserve_requested_order_and_deduplicate() -> None:
    adapter = YahooMarketDataAdapter(opener=lambda *_args, **_kwargs: FakeResponse(SAMPLE_QUOTES))

    snapshots = adapter.snapshots(["msft", "AAPL", "MSFT"])

    assert [snapshot.symbol for snapshot in snapshots] == ["MSFT", "AAPL"]
    assert str(snapshots[0].regular_market_price) == "510.25"


def test_missing_symbol_raises_explicit_error() -> None:
    adapter = YahooMarketDataAdapter(opener=lambda *_args, **_kwargs: FakeResponse(SAMPLE_QUOTES))
    with pytest.raises(YahooSymbolNotFoundError, match="NVDA"):
        adapter.snapshot("NVDA")


def test_malformed_response_raises_response_error() -> None:
    adapter = YahooMarketDataAdapter(opener=lambda *_args, **_kwargs: FakeResponse({"bad": True}))
    with pytest.raises(YahooMarketDataResponseError, match="quoteResponse"):
        adapter.snapshot("AAPL")


def test_http_retry_then_success() -> None:
    calls = 0
    sleeps: list[float] = []

    def opener(*_args: object, **_kwargs: object) -> FakeResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError("https://example.test", 503, "busy", Message(), None)
        return FakeResponse(SAMPLE_QUOTES)

    adapter = YahooMarketDataAdapter(
        YahooMarketDataConfig(backoff_base_seconds=1),
        opener=opener,
        sleep=sleeps.append,
        random_value=lambda: 0,
    )

    assert adapter.snapshot("AAPL").symbol == "AAPL"
    assert sleeps == [1]


def test_non_retryable_http_error_fails_immediately() -> None:
    def opener(*_args: object, **_kwargs: object) -> FakeResponse:
        raise urllib.error.HTTPError("https://example.test", 404, "missing", Message(), None)

    adapter = YahooMarketDataAdapter(opener=opener)
    with pytest.raises(YahooMarketDataHTTPError, match="HTTP 404"):
        adapter.snapshot("AAPL")


def test_fresh_cache_avoids_network(tmp_path: Path) -> None:
    online = YahooMarketDataAdapter(
        YahooMarketDataConfig(cache_directory=tmp_path),
        opener=lambda *_args, **_kwargs: FakeResponse(SAMPLE_QUOTES),
    )
    assert online.snapshot("AAPL").symbol == "AAPL"

    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("network should not be called")

    offline = YahooMarketDataAdapter(
        YahooMarketDataConfig(cache_directory=tmp_path, cache_ttl_seconds=None),
        opener=fail,
    )
    assert offline.snapshot("AAPL").company_name == "Apple Inc."
