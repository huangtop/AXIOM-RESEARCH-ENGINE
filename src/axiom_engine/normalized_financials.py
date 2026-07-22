from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class NormalizedIdentity:
    """Stable company identity attached to normalized financial data."""

    identifier: str
    cik: str
    entity_name: str
    currency: str = "USD"


@dataclass(frozen=True, slots=True)
class NormalizedIncome:
    """Normalized income-statement values for one fiscal period."""

    revenue: Decimal | None = None
    gross_profit: Decimal | None = None
    operating_income: Decimal | None = None
    net_income: Decimal | None = None
    eps_basic: Decimal | None = None
    eps_diluted: Decimal | None = None


@dataclass(frozen=True, slots=True)
class NormalizedBalance:
    """Normalized balance-sheet values at the fiscal-period end."""

    cash: Decimal | None = None
    accounts_receivable: Decimal | None = None
    inventory: Decimal | None = None
    current_assets: Decimal | None = None
    current_liabilities: Decimal | None = None
    total_assets: Decimal | None = None
    total_liabilities: Decimal | None = None
    shareholders_equity: Decimal | None = None


@dataclass(frozen=True, slots=True)
class NormalizedCashFlow:
    """Normalized cash-flow values for one fiscal period."""

    operating_cash_flow: Decimal | None = None
    capital_expenditure: Decimal | None = None
    free_cash_flow: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ProfitabilityMetrics:
    """Profitability metrics expressed as decimal fractions."""

    gross_margin: Decimal | None = None
    operating_margin: Decimal | None = None
    net_margin: Decimal | None = None
    free_cash_flow_margin: Decimal | None = None


@dataclass(frozen=True, slots=True)
class EfficiencyMetrics:
    """Capital and asset efficiency metrics."""

    return_on_equity: Decimal | None = None
    return_on_assets: Decimal | None = None
    asset_turnover: Decimal | None = None


@dataclass(frozen=True, slots=True)
class LiquidityMetrics:
    """Short-term liquidity metrics."""

    current_ratio: Decimal | None = None


@dataclass(frozen=True, slots=True)
class LeverageMetrics:
    """Capital-structure and leverage metrics."""

    debt_ratio: Decimal | None = None
    debt_to_equity: Decimal | None = None


@dataclass(frozen=True, slots=True)
class NormalizedFinancials:
    """Immutable normalized financial snapshot for one company and fiscal period."""

    identity: NormalizedIdentity
    fiscal_year: int
    fiscal_period: str
    income: NormalizedIncome
    balance: NormalizedBalance
    cash_flow: NormalizedCashFlow
    profitability: ProfitabilityMetrics = ProfitabilityMetrics()
    efficiency: EfficiencyMetrics = EfficiencyMetrics()
    liquidity: LiquidityMetrics = LiquidityMetrics()
    leverage: LeverageMetrics = LeverageMetrics()
    period_start: date | None = None
    period_end: date | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation without losing decimal precision."""

        return _serialize(asdict(self))


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serialize(item) for item in value]
    return value
