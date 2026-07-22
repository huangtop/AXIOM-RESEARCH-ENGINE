from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """Point-in-time market data used by valuation eligibility and model inputs."""

    symbol: str
    provider: str
    observed_at: datetime
    currency: str | None = None
    exchange: str | None = None
    quote_type: str | None = None
    company_name: str | None = None
    regular_market_price: Decimal | None = None
    previous_close: Decimal | None = None
    market_cap: Decimal | None = None
    shares_outstanding: Decimal | None = None
    trailing_earnings_per_share: Decimal | None = None
    forward_earnings_per_share: Decimal | None = None
    trailing_price_to_earnings: Decimal | None = None
    forward_price_to_earnings: Decimal | None = None
    price_to_book: Decimal | None = None
    enterprise_value: Decimal | None = None
    enterprise_value_to_revenue: Decimal | None = None
    enterprise_value_to_ebitda: Decimal | None = None
    beta: Decimal | None = None
    fifty_two_week_low: Decimal | None = None
    fifty_two_week_high: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol cannot be empty")
        if not self.provider.strip():
            raise ValueError("provider cannot be empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        for name in (
            "regular_market_price",
            "previous_close",
            "market_cap",
            "shares_outstanding",
            "price_to_book",
            "enterprise_value",
            "fifty_two_week_low",
            "fifty_two_week_high",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")

    @property
    def has_market_price(self) -> bool:
        return self.regular_market_price is not None and self.regular_market_price > 0

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> MarketSnapshot:
        values = dict(payload)
        observed_at = values.get("observed_at")
        if isinstance(observed_at, str):
            values["observed_at"] = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        elif isinstance(observed_at, (int, float)):
            values["observed_at"] = datetime.fromtimestamp(observed_at, tz=timezone.utc)

        decimal_fields = {
            "regular_market_price",
            "previous_close",
            "market_cap",
            "shares_outstanding",
            "trailing_earnings_per_share",
            "forward_earnings_per_share",
            "trailing_price_to_earnings",
            "forward_price_to_earnings",
            "price_to_book",
            "enterprise_value",
            "enterprise_value_to_revenue",
            "enterprise_value_to_ebitda",
            "beta",
            "fifty_two_week_low",
            "fifty_two_week_high",
        }
        for name in decimal_fields:
            if values.get(name) is not None and not isinstance(values[name], Decimal):
                values[name] = Decimal(str(values[name]))
        return cls(**values)


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serialize(item) for item in value]
    return value
