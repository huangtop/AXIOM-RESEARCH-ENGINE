from datetime import datetime, timezone
from decimal import Decimal
import json

import pytest

from axiom_engine.cached_close import JsonCachedPreviousCloseProvider, write_close_cache
from axiom_engine.previous_close import DailyClose, PreviousCloseError


def test_cached_provider_reads_without_network(tmp_path):
    path = tmp_path / "closes.json"
    path.write_text(json.dumps({"symbols": {"NVDA": {
        "session_date": "2026-07-22",
        "close": "212.05",
        "currency": "USD",
        "exchange_timezone": "America/New_York",
        "provider": "github_actions_close_cache"
    }}}))
    close = JsonCachedPreviousCloseProvider(path).previous_close("nvda")
    assert close.symbol == "NVDA"
    assert close.session_date.isoformat() == "2026-07-22"
    assert close.close == Decimal("212.05")
    assert close.provider == "github_actions_close_cache"


def test_cached_provider_rejects_missing_symbol(tmp_path):
    path = tmp_path / "closes.json"
    path.write_text('{"symbols": {}}')
    with pytest.raises(PreviousCloseError, match="not cached"):
        JsonCachedPreviousCloseProvider(path).previous_close("AAPL")


def test_write_cache_preserves_other_symbols(tmp_path):
    path = tmp_path / "closes.json"
    path.write_text('{"symbols": {"AAPL": {"close": "1"}}}')
    write_close_cache(path, [DailyClose(
        symbol="NVDA", session_date=datetime(2026, 7, 22).date(),
        close=Decimal("212.05"), currency="USD", exchange_timezone="America/New_York"
    )], generated_at=datetime(2026, 7, 23, tzinfo=timezone.utc))
    payload = json.loads(path.read_text())
    assert "AAPL" in payload["symbols"]
    assert payload["symbols"]["NVDA"]["close"] == "212.05"
