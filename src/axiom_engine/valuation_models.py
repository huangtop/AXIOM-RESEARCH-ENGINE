from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any


class ValuationModelType(StrEnum):
    """Supported valuation model families."""

    discounted_cash_flow = "discounted_cash_flow"
    reverse_discounted_cash_flow = "reverse_discounted_cash_flow"
    relative_multiples = "relative_multiples"


class TerminalValueMethod(StrEnum):
    """Methods available for estimating value beyond the explicit forecast."""

    perpetual_growth = "perpetual_growth"
    exit_multiple = "exit_multiple"


@dataclass(frozen=True, slots=True)
class ValuationIdentity:
    """Stable identity and market context for a valuation."""

    company_id: str
    security_id: str
    ticker: str
    currency: str
    as_of_date: date

    def __post_init__(self) -> None:
        _require_text("company_id", self.company_id)
        _require_text("security_id", self.security_id)
        _require_text("ticker", self.ticker)
        _require_text("currency", self.currency)


@dataclass(frozen=True, slots=True)
class ForecastPeriod:
    """One explicit forecast period used by a valuation model."""

    fiscal_year: int
    revenue: Decimal | None = None
    operating_income: Decimal | None = None
    net_income: Decimal | None = None
    free_cash_flow: Decimal | None = None

    def __post_init__(self) -> None:
        if self.fiscal_year < 1:
            raise ValueError("fiscal_year must be positive")


@dataclass(frozen=True, slots=True)
class DiscountRateAssumptions:
    """Discount-rate inputs expressed as decimal fractions."""

    risk_free_rate: Decimal
    equity_risk_premium: Decimal
    beta: Decimal
    cost_of_debt: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0")
    debt_weight: Decimal = Decimal("0")
    equity_weight: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        _require_non_negative("risk_free_rate", self.risk_free_rate)
        _require_non_negative("equity_risk_premium", self.equity_risk_premium)
        _require_non_negative("beta", self.beta)
        _require_non_negative("cost_of_debt", self.cost_of_debt)
        _require_rate("tax_rate", self.tax_rate)
        _require_rate("debt_weight", self.debt_weight)
        _require_rate("equity_weight", self.equity_weight)
        if self.debt_weight + self.equity_weight != Decimal("1"):
            raise ValueError("debt_weight and equity_weight must sum to 1")

    @property
    def cost_of_equity(self) -> Decimal:
        """Return CAPM cost of equity without rounding."""

        return self.risk_free_rate + self.beta * self.equity_risk_premium

    @property
    def weighted_average_cost_of_capital(self) -> Decimal:
        """Return WACC without rounding."""

        after_tax_debt = self.cost_of_debt * (Decimal("1") - self.tax_rate)
        return self.equity_weight * self.cost_of_equity + self.debt_weight * after_tax_debt


@dataclass(frozen=True, slots=True)
class TerminalValueAssumptions:
    """Terminal-value configuration for a DCF model."""

    method: TerminalValueMethod
    perpetual_growth_rate: Decimal | None = None
    exit_multiple: Decimal | None = None

    def __post_init__(self) -> None:
        if self.method is TerminalValueMethod.perpetual_growth:
            if self.perpetual_growth_rate is None:
                raise ValueError("perpetual_growth_rate is required")
            if self.exit_multiple is not None:
                raise ValueError("exit_multiple is not allowed for perpetual growth")
        elif self.method is TerminalValueMethod.exit_multiple:
            if self.exit_multiple is None:
                raise ValueError("exit_multiple is required")
            _require_non_negative("exit_multiple", self.exit_multiple)
            if self.perpetual_growth_rate is not None:
                raise ValueError("perpetual_growth_rate is not allowed for exit multiple")


@dataclass(frozen=True, slots=True)
class CapitalStructure:
    """Bridge from enterprise value to equity value."""

    cash_and_equivalents: Decimal = Decimal("0")
    total_debt: Decimal = Decimal("0")
    non_controlling_interest: Decimal = Decimal("0")
    preferred_stock: Decimal = Decimal("0")
    diluted_shares_outstanding: Decimal | None = None

    def __post_init__(self) -> None:
        _require_non_negative("cash_and_equivalents", self.cash_and_equivalents)
        _require_non_negative("total_debt", self.total_debt)
        _require_non_negative("non_controlling_interest", self.non_controlling_interest)
        _require_non_negative("preferred_stock", self.preferred_stock)
        if self.diluted_shares_outstanding is not None:
            if self.diluted_shares_outstanding <= 0:
                raise ValueError("diluted_shares_outstanding must be positive")

    @property
    def net_debt(self) -> Decimal:
        return self.total_debt - self.cash_and_equivalents


@dataclass(frozen=True, slots=True)
class DCFInputs:
    """Complete immutable input contract for a future DCF engine."""

    identity: ValuationIdentity
    forecasts: tuple[ForecastPeriod, ...]
    discount_rates: DiscountRateAssumptions
    terminal_value: TerminalValueAssumptions
    capital_structure: CapitalStructure = field(default_factory=CapitalStructure)
    model_version: str = "1.0"

    def __post_init__(self) -> None:
        _require_text("model_version", self.model_version)
        if not self.forecasts:
            raise ValueError("forecasts cannot be empty")
        years = [period.fiscal_year for period in self.forecasts]
        if years != sorted(years):
            raise ValueError("forecasts must be ordered by fiscal_year")
        if len(years) != len(set(years)):
            raise ValueError("forecast fiscal years must be unique")
        if any(period.free_cash_flow is None for period in self.forecasts):
            raise ValueError("every DCF forecast requires free_cash_flow")
        if self.terminal_value.method is TerminalValueMethod.perpetual_growth:
            growth = self.terminal_value.perpetual_growth_rate
            if growth is not None and growth >= self.discount_rates.weighted_average_cost_of_capital:
                raise ValueError("perpetual growth must be lower than WACC")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True, slots=True)
class ReverseDCFInputs:
    """Inputs for solving the constant FCF growth implied by a market price."""

    identity: ValuationIdentity
    current_free_cash_flow: Decimal
    forecast_years: int
    discount_rates: DiscountRateAssumptions
    terminal_value: TerminalValueAssumptions
    capital_structure: CapitalStructure
    market_price: Decimal
    minimum_growth_rate: Decimal = Decimal("-0.50")
    maximum_growth_rate: Decimal = Decimal("1.00")
    tolerance: Decimal = Decimal("0.000001")
    max_iterations: int = 200
    model_version: str = "1.0"

    def __post_init__(self) -> None:
        _require_text("model_version", self.model_version)
        if self.current_free_cash_flow <= 0:
            raise ValueError("current_free_cash_flow must be positive")
        if self.forecast_years < 1:
            raise ValueError("forecast_years must be positive")
        if self.market_price <= 0:
            raise ValueError("market_price must be positive")
        if self.capital_structure.diluted_shares_outstanding is None:
            raise ValueError("diluted_shares_outstanding is required")
        if self.minimum_growth_rate <= Decimal("-1"):
            raise ValueError("minimum_growth_rate must be greater than -1")
        if self.minimum_growth_rate >= self.maximum_growth_rate:
            raise ValueError("minimum_growth_rate must be lower than maximum_growth_rate")
        if self.tolerance <= 0:
            raise ValueError("tolerance must be positive")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        wacc = self.discount_rates.weighted_average_cost_of_capital
        if wacc <= 0:
            raise ValueError("WACC must be positive")
        if self.terminal_value.method is TerminalValueMethod.perpetual_growth:
            growth = self.terminal_value.perpetual_growth_rate
            if growth is not None and growth >= wacc:
                raise ValueError("perpetual growth must be lower than WACC")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True, slots=True)
class ReverseDCFResult:
    """Market-implied constant FCF growth and the DCF that reproduces it."""

    identity: ValuationIdentity
    model_type: ValuationModelType
    model_version: str
    market_price: Decimal
    target_equity_value: Decimal
    target_enterprise_value: Decimal
    implied_growth_rate: Decimal
    enterprise_value: Decimal
    equity_value: Decimal
    implied_value_per_share: Decimal
    forecast_values: tuple[DiscountedCashFlowPeriod, ...]
    terminal_value: Decimal
    present_value_terminal: Decimal
    iterations: int
    converged: bool
    valuation_error: Decimal
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text("model_version", self.model_version)
        if self.market_price <= 0:
            raise ValueError("market_price must be positive")
        if self.iterations < 0:
            raise ValueError("iterations cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True, slots=True)
class DiscountedCashFlowPeriod:
    """Calculated present value for one forecast period."""

    fiscal_year: int
    free_cash_flow: Decimal
    discount_factor: Decimal
    present_value: Decimal

    def __post_init__(self) -> None:
        if self.fiscal_year < 1:
            raise ValueError("fiscal_year must be positive")
        if self.discount_factor <= 0:
            raise ValueError("discount_factor must be positive")


@dataclass(frozen=True, slots=True)
class ValuationResult:
    """Common output contract shared by future valuation engines."""

    identity: ValuationIdentity
    model_type: ValuationModelType
    model_version: str
    enterprise_value: Decimal
    equity_value: Decimal
    fair_value_per_share: Decimal | None
    market_price: Decimal | None = None
    upside: Decimal | None = None
    forecast_values: tuple[DiscountedCashFlowPeriod, ...] = ()
    terminal_value: Decimal | None = None
    present_value_terminal: Decimal | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text("model_version", self.model_version)
        if self.fair_value_per_share is not None and self.fair_value_per_share < 0:
            raise ValueError("fair_value_per_share cannot be negative")
        if self.market_price is not None and self.market_price < 0:
            raise ValueError("market_price cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


def _require_text(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} cannot be empty")


def _require_non_negative(name: str, value: Decimal) -> None:
    if value < 0:
        raise ValueError(f"{name} cannot be negative")


def _require_rate(name: str, value: Decimal) -> None:
    if value < 0 or value > 1:
        raise ValueError(f"{name} must be between 0 and 1")


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serialize(item) for item in value]
    return value
