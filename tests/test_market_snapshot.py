from datetime import datetime, timezone
from decimal import Decimal

import pytest

from axiom_engine.market_snapshot import MarketSnapshot


def test_market_snapshot_round_trip() -> None:
    snapshot = MarketSnapshot(
        symbol="AAPL",
        provider="yahoo_finance",
        observed_at=datetime(2026, 7, 22, 8, 30, tzinfo=timezone.utc),
        currency="USD",
        regular_market_price=Decimal("225.50"),
        forward_earnings_per_share=Decimal("8.75"),
    )

    restored = MarketSnapshot.from_dict(snapshot.to_dict())

    assert restored == snapshot
    assert restored.has_market_price is True


def test_market_snapshot_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        MarketSnapshot(
            symbol="AAPL",
            provider="yahoo_finance",
            observed_at=datetime(2026, 7, 22),
        )


def test_market_snapshot_rejects_negative_price() -> None:
    with pytest.raises(ValueError, match="regular_market_price"):
        MarketSnapshot(
            symbol="AAPL",
            provider="yahoo_finance",
            observed_at=datetime.now(tz=timezone.utc),
            regular_market_price=Decimal("-1"),
        )
