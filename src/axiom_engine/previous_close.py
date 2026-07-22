from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping, Protocol

YAHOO_CHART_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    "?interval=1d&range=1mo&events=history"
)


class PreviousCloseError(RuntimeError):
    """Base error for completed-session close resolution."""


class PreviousCloseResponseError(PreviousCloseError):
    """Raised when a provider returns unusable history data."""


@dataclass(frozen=True, slots=True)
class DailyClose:
    symbol: str
    session_date: date
    close: Decimal
    currency: str | None
    exchange_timezone: str | None
    provider: str = "yahoo_finance"

    def __post_init__(self) -> None:
        normalized = self.symbol.strip().upper()
        if not normalized:
            raise ValueError("symbol cannot be empty")
        object.__setattr__(self, "symbol", normalized)
        if self.close <= 0:
            raise ValueError("close must be positive")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["session_date"] = self.session_date.isoformat()
        payload["close"] = str(self.close)
        return payload


class DailyCloseProvider(Protocol):
    def previous_close(self, symbol: str, *, as_of: datetime | None = None) -> DailyClose: ...


class YahooPreviousCloseAdapter:
    """Resolve the last completed Yahoo daily bar, never an intraday quote."""

    def __init__(
        self,
        *,
        opener: Callable[..., object] | None = None,
        timeout_seconds: float = 15.0,
        user_agent: str = "AXIOM-Research-Engine/0.7",
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._opener = opener or urllib.request.urlopen
        self._timeout_seconds = timeout_seconds
        self._user_agent = user_agent

    def previous_close(self, symbol: str, *, as_of: datetime | None = None) -> DailyClose:
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("symbol cannot be empty")
        encoded = urllib.parse.quote(normalized, safe="")
        request = urllib.request.Request(
            YAHOO_CHART_URL.format(symbol=encoded),
            headers={"User-Agent": self._user_agent, "Accept": "application/json"},
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8-sig"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            raise PreviousCloseError("Yahoo history request failed") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PreviousCloseResponseError("Yahoo history response is not valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise PreviousCloseResponseError("Yahoo history response must be an object")
        return _parse_yahoo_close(payload, normalized, as_of=as_of)


def _parse_yahoo_close(
    payload: Mapping[str, Any], symbol: str, *, as_of: datetime | None
) -> DailyClose:
    chart = payload.get("chart")
    if not isinstance(chart, Mapping) or chart.get("error"):
        raise PreviousCloseResponseError("Yahoo chart response contains an error")
    results = chart.get("result")
    if not isinstance(results, list) or not results or not isinstance(results[0], Mapping):
        raise PreviousCloseResponseError("Yahoo chart response has no result")
    result = results[0]
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    quote = indicators.get("quote") if isinstance(indicators, Mapping) else None
    closes = quote[0].get("close") if isinstance(quote, list) and quote and isinstance(quote[0], Mapping) else None
    if not isinstance(timestamps, list) or not isinstance(closes, list):
        raise PreviousCloseResponseError("Yahoo chart response is missing daily closes")

    cutoff = as_of or datetime.now(tz=timezone.utc)
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    candidates: list[tuple[int, Decimal]] = []
    for raw_ts, raw_close in zip(timestamps, closes, strict=False):
        if not isinstance(raw_ts, (int, float)) or raw_close is None:
            continue
        bar_time = datetime.fromtimestamp(raw_ts, tz=timezone.utc)
        if bar_time > cutoff:
            continue
        try:
            close = Decimal(str(raw_close))
        except (InvalidOperation, ValueError):
            continue
        if close > 0:
            candidates.append((int(raw_ts), close))
    if not candidates:
        raise PreviousCloseResponseError("Yahoo chart response has no completed positive close")
    timestamp, close = max(candidates, key=lambda item: item[0])
    meta = result.get("meta") if isinstance(result.get("meta"), Mapping) else {}
    return DailyClose(
        symbol=symbol,
        session_date=datetime.fromtimestamp(timestamp, tz=timezone.utc).date(),
        close=close,
        currency=_text(meta.get("currency")),
        exchange_timezone=_text(meta.get("exchangeTimezoneName")),
    )


def _text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
