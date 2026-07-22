from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from axiom_engine.previous_close import _parse_yahoo_close


def _timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp())


def _payload():
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {
                        "currency": "USD",
                        "exchangeTimezoneName": "America/New_York",
                    },
                    "timestamp": [
                        _timestamp("2026-07-21T09:30:00-04:00"),
                        _timestamp("2026-07-22T09:30:00-04:00"),
                    ],
                    "indicators": {"quote": [{"close": [205.47, 206.81]}]},
                }
            ],
        }
    }


def test_current_daily_bar_is_excluded_before_regular_session_close():
    close = _parse_yahoo_close(
        _payload(),
        "NVDA",
        as_of=datetime(2026, 7, 22, 14, 25, tzinfo=timezone.utc),
    )
    assert close.session_date.isoformat() == "2026-07-21"
    assert close.close == Decimal("205.47")


def test_current_daily_bar_is_accepted_after_regular_session_close():
    close = _parse_yahoo_close(
        _payload(),
        "NVDA",
        as_of=datetime(2026, 7, 22, 21, 5, tzinfo=timezone.utc),
    )
    assert close.session_date.isoformat() == "2026-07-22"
    assert close.close == Decimal("206.81")
