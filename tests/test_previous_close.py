from __future__ import annotations

import io
import json
import urllib.error
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from axiom_engine.previous_close import PreviousCloseResponseError, YahooPreviousCloseAdapter


class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *_args): self.close()


def opener_for(payload):
    def opener(_request, timeout):
        assert timeout == 15.0
        return Response(json.dumps(payload).encode())
    return opener


def payload():
    return {"chart": {"error": None, "result": [{"meta": {"currency": "USD", "exchangeTimezoneName": "America/New_York"}, "timestamp": [1784511000, 1784597400, 1784683800], "indicators": {"quote": [{"close": [201.1, 203.2, 205.47]}]}}]}}


def test_resolves_latest_completed_close_at_cutoff():
    close = YahooPreviousCloseAdapter(opener=opener_for(payload())).previous_close(
        "nvda", as_of=datetime.fromtimestamp(1784600000, tz=timezone.utc)
    )
    assert close.symbol == "NVDA"
    assert close.close == Decimal("203.2")
    assert close.to_dict()["close"] == "203.2"


def test_resolves_latest_when_all_bars_are_before_cutoff():
    close = YahooPreviousCloseAdapter(opener=opener_for(payload())).previous_close(
        "NVDA", as_of=datetime.fromtimestamp(1784700000, tz=timezone.utc)
    )
    assert close.close == Decimal("205.47")


def test_rejects_naive_cutoff():
    with pytest.raises(ValueError, match="timezone-aware"):
        YahooPreviousCloseAdapter(opener=opener_for(payload())).previous_close("NVDA", as_of=datetime(2026, 7, 22))


def test_rejects_missing_history():
    with pytest.raises(PreviousCloseResponseError):
        YahooPreviousCloseAdapter(opener=opener_for({"chart": {"error": None, "result": []}})).previous_close("NVDA")


def test_retries_transient_rate_limit_with_exponential_backoff():
    calls = []
    sleeps = []

    def opener(request, timeout):
        calls.append(request)
        if len(calls) < 3:
            raise urllib.error.HTTPError(request.full_url, 429, "rate limited", {}, None)
        return Response(json.dumps(payload()).encode())

    close = YahooPreviousCloseAdapter(
        opener=opener,
        max_attempts=3,
        backoff_seconds=0.25,
        sleep=sleeps.append,
    ).previous_close("NVDA", as_of=datetime.fromtimestamp(1784700000, tz=timezone.utc))
    assert close.close == Decimal("205.47")
    assert len(calls) == 3
    assert sleeps == [0.25, 0.5]
