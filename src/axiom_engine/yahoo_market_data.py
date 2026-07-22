from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping

from axiom_engine.market_snapshot import MarketSnapshot

YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols}"


class YahooMarketDataError(RuntimeError):
    """Base exception raised by the Yahoo market-data adapter."""


class YahooMarketDataHTTPError(YahooMarketDataError):
    """Raised when Yahoo returns an HTTP/network error."""


class YahooMarketDataResponseError(YahooMarketDataError):
    """Raised when Yahoo returns malformed or incomplete quote data."""


class YahooSymbolNotFoundError(YahooMarketDataResponseError):
    """Raised when Yahoo returns no quote for the requested symbol."""


@dataclass(frozen=True, slots=True)
class YahooMarketDataConfig:
    timeout_seconds: float = 15.0
    max_attempts: int = 3
    backoff_base_seconds: float = 0.5
    user_agent: str = "AXIOM-Research-Engine/0.7"
    cache_directory: Path | None = None
    cache_ttl_seconds: float | None = 300.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if self.backoff_base_seconds < 0:
            raise ValueError("backoff_base_seconds cannot be negative")
        if not self.user_agent.strip():
            raise ValueError("user_agent cannot be empty")
        if self.cache_ttl_seconds is not None and self.cache_ttl_seconds < 0:
            raise ValueError("cache_ttl_seconds cannot be negative")


class YahooMarketDataAdapter:
    """Fetch normalized point-in-time quote snapshots from Yahoo Finance.

    Network access is isolated behind an injectable opener so tests and callers
    can validate behavior without depending on live Yahoo availability.
    """

    def __init__(
        self,
        config: YahooMarketDataConfig | None = None,
        *,
        opener: Callable[..., object] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        wall_time: Callable[[], float] = time.time,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self.config = config or YahooMarketDataConfig()
        self._opener = opener or urllib.request.urlopen
        self._sleep = sleep
        self._wall_time = wall_time
        self._random_value = random_value

    def snapshot(self, symbol: str, *, refresh: bool = False) -> MarketSnapshot:
        normalized_symbol = normalize_yahoo_symbol(symbol)
        cache_path = self._cache_path(normalized_symbol)
        if not refresh and cache_path is not None and self._cache_is_fresh(cache_path):
            return self._read_cache(cache_path, normalized_symbol)

        payload = self._fetch((normalized_symbol,))
        snapshot = self._parse_snapshot(payload, normalized_symbol)
        if cache_path is not None:
            self._write_cache(cache_path, snapshot)
        return snapshot

    def snapshots(
        self,
        symbols: tuple[str, ...] | list[str],
        *,
        refresh: bool = False,
    ) -> tuple[MarketSnapshot, ...]:
        normalized = tuple(dict.fromkeys(normalize_yahoo_symbol(symbol) for symbol in symbols))
        if not normalized:
            return ()
        if len(normalized) == 1:
            return (self.snapshot(normalized[0], refresh=refresh),)

        if not refresh and self.config.cache_directory is not None:
            cached: dict[str, MarketSnapshot] = {}
            missing: list[str] = []
            for symbol in normalized:
                path = self._cache_path(symbol)
                if path is not None and self._cache_is_fresh(path):
                    cached[symbol] = self._read_cache(path, symbol)
                else:
                    missing.append(symbol)
            if not missing:
                return tuple(cached[symbol] for symbol in normalized)
        else:
            cached = {}
            missing = list(normalized)

        payload = self._fetch(tuple(missing))
        results = _quote_results(payload)
        by_symbol = {
            normalize_yahoo_symbol(str(item.get("symbol", ""))): item
            for item in results
            if item.get("symbol")
        }
        snapshots: dict[str, MarketSnapshot] = dict(cached)
        for symbol in missing:
            item = by_symbol.get(symbol)
            if item is None:
                raise YahooSymbolNotFoundError(f"Yahoo returned no quote for symbol {symbol}")
            snapshot = _snapshot_from_quote(item, symbol)
            snapshots[symbol] = snapshot
            path = self._cache_path(symbol)
            if path is not None:
                self._write_cache(path, snapshot)
        return tuple(snapshots[symbol] for symbol in normalized)

    def _fetch(self, symbols: tuple[str, ...]) -> Mapping[str, Any]:
        encoded = urllib.parse.quote(",".join(symbols), safe=",")
        url = YAHOO_QUOTE_URL.format(symbols=encoded)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.config.user_agent.strip(),
                "Accept": "application/json",
            },
        )
        last_error: BaseException | None = None
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                with self._opener(request, timeout=self.config.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8-sig"))
                    if not isinstance(payload, Mapping):
                        raise YahooMarketDataResponseError("Yahoo response must be a JSON object")
                    return payload
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504} or attempt == self.config.max_attempts:
                    raise YahooMarketDataHTTPError(
                        f"Yahoo request failed: HTTP {exc.code}"
                    ) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt == self.config.max_attempts:
                    raise YahooMarketDataHTTPError(
                        f"Yahoo request failed after {attempt} attempts"
                    ) from exc
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise YahooMarketDataResponseError("Yahoo response is not valid JSON") from exc
            self._sleep(self._retry_delay(attempt))
        raise YahooMarketDataHTTPError("Yahoo request failed") from last_error

    def _parse_snapshot(self, payload: Mapping[str, Any], symbol: str) -> MarketSnapshot:
        results = _quote_results(payload)
        for item in results:
            if normalize_yahoo_symbol(str(item.get("symbol", ""))) == symbol:
                return _snapshot_from_quote(item, symbol)
        raise YahooSymbolNotFoundError(f"Yahoo returned no quote for symbol {symbol}")

    def _retry_delay(self, attempt: int) -> float:
        base = self.config.backoff_base_seconds * (2 ** (attempt - 1))
        return base + base * 0.25 * self._random_value()

    def _cache_path(self, symbol: str) -> Path | None:
        if self.config.cache_directory is None:
            return None
        safe_symbol = urllib.parse.quote(symbol, safe="")
        return Path(self.config.cache_directory) / f"{safe_symbol}.json"

    def _cache_is_fresh(self, path: Path) -> bool:
        if not path.is_file():
            return False
        ttl = self.config.cache_ttl_seconds
        if ttl is None:
            return True
        return self._wall_time() - path.stat().st_mtime <= ttl

    def _read_cache(self, path: Path, symbol: str) -> MarketSnapshot:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            snapshot = MarketSnapshot.from_dict(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise YahooMarketDataResponseError(f"invalid Yahoo cache file: {path}") from exc
        if snapshot.symbol != symbol:
            raise YahooMarketDataResponseError(
                f"cached Yahoo symbol mismatch: expected {symbol}, received {snapshot.symbol}"
            )
        return snapshot

    @staticmethod
    def _write_cache(path: Path, snapshot: MarketSnapshot) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(snapshot.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def normalize_yahoo_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("symbol cannot be empty")
    if any(character.isspace() for character in normalized):
        raise ValueError("symbol cannot contain whitespace")
    return normalized


def _quote_results(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    quote_response = payload.get("quoteResponse")
    if not isinstance(quote_response, Mapping):
        raise YahooMarketDataResponseError("Yahoo response is missing quoteResponse")
    error = quote_response.get("error")
    if error:
        raise YahooMarketDataResponseError(f"Yahoo quote error: {error}")
    results = quote_response.get("result")
    if not isinstance(results, list):
        raise YahooMarketDataResponseError("Yahoo response result must be a list")
    return [item for item in results if isinstance(item, Mapping)]


def _snapshot_from_quote(item: Mapping[str, Any], symbol: str) -> MarketSnapshot:
    market_time = item.get("regularMarketTime")
    if isinstance(market_time, (int, float)):
        observed_at = datetime.fromtimestamp(market_time, tz=timezone.utc)
    else:
        observed_at = datetime.now(tz=timezone.utc)

    return MarketSnapshot(
        symbol=symbol,
        provider="yahoo_finance",
        observed_at=observed_at,
        currency=_text(item.get("currency")),
        exchange=_text(item.get("fullExchangeName") or item.get("exchange")),
        quote_type=_text(item.get("quoteType")),
        company_name=_text(item.get("longName") or item.get("shortName")),
        regular_market_price=_decimal(item.get("regularMarketPrice")),
        previous_close=_decimal(item.get("regularMarketPreviousClose")),
        market_cap=_decimal(item.get("marketCap")),
        shares_outstanding=_decimal(item.get("sharesOutstanding")),
        trailing_earnings_per_share=_decimal(item.get("epsTrailingTwelveMonths")),
        forward_earnings_per_share=_decimal(item.get("epsForward")),
        trailing_price_to_earnings=_decimal(item.get("trailingPE")),
        forward_price_to_earnings=_decimal(item.get("forwardPE")),
        price_to_book=_decimal(item.get("priceToBook")),
        enterprise_value=_decimal(item.get("enterpriseValue")),
        enterprise_value_to_revenue=_decimal(item.get("enterpriseToRevenue")),
        enterprise_value_to_ebitda=_decimal(item.get("enterpriseToEbitda")),
        beta=_decimal(item.get("beta")),
        fifty_two_week_low=_decimal(item.get("fiftyTwoWeekLow")),
        fifty_two_week_high=_decimal(item.get("fiftyTwoWeekHigh")),
    )


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite():
        return None
    return result


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
