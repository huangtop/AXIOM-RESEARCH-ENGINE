from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

MARKET_CACHE_SCHEMA = "previous-close-cache.tuple.v2"


def market_rows(payload: object) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    legacy = payload.get("symbols")
    return legacy if isinstance(legacy, Mapping) else payload


def unpack_market_row(row: object) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return {
            "close": row.get("close"),
            "session_date": row.get("session_date"),
            "currency": row.get("currency"),
            "exchange_timezone": row.get("exchange_timezone"),
            "provider": row.get("provider") or "yahoo_finance",
            "fetched_at": row.get("fetched_at"),
        }
    if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)) and len(row) >= 2:
        return {
            "close": row[0],
            "session_date": row[1],
            "currency": row[2] if len(row) >= 3 else None,
            "exchange_timezone": None,
            "provider": "yahoo_finance",
            "fetched_at": None,
        }
    return {}


def compact_market_row(close, session_date) -> list[object]:
    try:
        n = Decimal(str(close))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid close: {close!r}") from exc
    if not n.is_finite() or n <= 0:
        raise ValueError(f"invalid close: {close!r}")
    numeric = int(n) if n == n.to_integral_value() else float(n)
    day = session_date.isoformat() if isinstance(session_date, date) else str(session_date)
    date.fromisoformat(day)
    return [numeric, day]
