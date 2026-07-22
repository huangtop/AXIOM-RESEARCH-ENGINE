from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from .financial_repository import FinancialRepository
from .financial_statement_models import FinancialStatements, FinancialValue
from .normalized_financials import (
    EfficiencyMetrics,
    GrowthMetrics,
    LeverageMetrics,
    LiquidityMetrics,
    NormalizedBalance,
    NormalizedCashFlow,
    NormalizedFinancials,
    NormalizedIdentity,
    NormalizedIncome,
    ProfitabilityMetrics,
)


class FinancialNormalizationError(RuntimeError):
    """Raised when canonical statements cannot be normalized consistently."""


class FinancialNormalizer:
    """Map canonical financial statements to an immutable normalized snapshot.

    Commit-010B intentionally performs structural normalization only. Ratio and
    analytical metric calculation is deferred to later normalization commits.
    """

    def __init__(self, repository: FinancialRepository) -> None:
        self._repository = repository

    def normalize(
        self,
        identifier: str,
        *,
        fiscal_year: int | None = None,
    ) -> NormalizedFinancials:
        company = self._repository.resolve_company(identifier)
        statements = self._repository.statements(identifier, fiscal_year=fiscal_year)
        values = tuple(_statement_values(statements))
        currency = _resolve_currency(values)
        period_start, period_end = _resolve_period(values)
        prior = _prior_statements(self._repository, identifier, statements.fiscal_year)

        return NormalizedFinancials(
            identity=NormalizedIdentity(
                identifier=company.identifier,
                cik=company.cik,
                entity_name=company.entity_name,
                currency=currency,
            ),
            fiscal_year=statements.fiscal_year,
            fiscal_period=statements.fiscal_period,
            income=NormalizedIncome(
                revenue=_amount(statements.income.revenue),
                gross_profit=_amount(statements.income.gross_profit),
                operating_income=_amount(statements.income.operating_income),
                net_income=_amount(statements.income.net_income),
                eps_basic=_amount(statements.income.eps_basic),
                eps_diluted=_amount(statements.income.eps_diluted),
            ),
            balance=NormalizedBalance(
                cash=_amount(statements.balance.cash),
                accounts_receivable=_amount(statements.balance.accounts_receivable),
                inventory=_amount(statements.balance.inventory),
                current_assets=_amount(statements.balance.current_assets),
                current_liabilities=_amount(statements.balance.current_liabilities),
                total_assets=_amount(statements.balance.total_assets),
                total_liabilities=_amount(statements.balance.total_liabilities),
                shareholders_equity=_amount(statements.balance.shareholders_equity),
            ),
            cash_flow=NormalizedCashFlow(
                operating_cash_flow=_amount(statements.cash_flow.operating_cash_flow),
                capital_expenditure=_amount(statements.cash_flow.capital_expenditure),
                free_cash_flow=_amount(statements.cash_flow.free_cash_flow),
            ),
            profitability=_profitability_metrics(statements),
            growth=_growth_metrics(statements, prior),
            efficiency=_efficiency_metrics(statements, prior),
            liquidity=_liquidity_metrics(statements),
            leverage=_leverage_metrics(statements),
            period_start=period_start,
            period_end=period_end,
        )


def _amount(value: FinancialValue | None) -> Decimal | None:
    return None if value is None else value.value


def _statement_values(statements: FinancialStatements) -> Iterable[FinancialValue]:
    for value in (
        statements.income.revenue,
        statements.income.gross_profit,
        statements.income.operating_income,
        statements.income.net_income,
        statements.income.eps_basic,
        statements.income.eps_diluted,
        statements.balance.cash,
        statements.balance.accounts_receivable,
        statements.balance.inventory,
        statements.balance.current_assets,
        statements.balance.current_liabilities,
        statements.balance.total_assets,
        statements.balance.total_liabilities,
        statements.balance.shareholders_equity,
        statements.cash_flow.operating_cash_flow,
        statements.cash_flow.capital_expenditure,
        statements.cash_flow.free_cash_flow,
    ):
        if value is not None:
            yield value


def _resolve_currency(values: tuple[FinancialValue, ...]) -> str:
    monetary_units = {
        value.unit
        for value in values
        if value.unit and value.unit.lower() not in {"shares", "usd/shares"}
    }
    if not monetary_units:
        return "USD"
    if len(monetary_units) != 1:
        units = ", ".join(sorted(monetary_units))
        raise FinancialNormalizationError(f"mixed monetary units are not supported: {units}")
    return next(iter(monetary_units))


def _resolve_period(values: tuple[FinancialValue, ...]) -> tuple[date | None, date | None]:
    duration_values = tuple(value for value in values if value.start is not None)
    starts = [value.start for value in duration_values if value.start is not None]
    ends = [value.end for value in values if value.end is not None]
    return (min(starts) if starts else None, max(ends) if ends else None)


def _profitability_metrics(statements: FinancialStatements) -> ProfitabilityMetrics:
    revenue = _amount(statements.income.revenue)
    return ProfitabilityMetrics(
        gross_margin=_safe_ratio(_amount(statements.income.gross_profit), revenue),
        operating_margin=_safe_ratio(_amount(statements.income.operating_income), revenue),
        net_margin=_safe_ratio(_amount(statements.income.net_income), revenue),
        free_cash_flow_margin=_safe_ratio(
            _amount(statements.cash_flow.free_cash_flow),
            revenue,
        ),
    )


def _prior_statements(
    repository: FinancialRepository,
    identifier: str,
    fiscal_year: int,
) -> FinancialStatements | None:
    older_years = tuple(
        year for year in repository.fiscal_years(identifier) if year < fiscal_year
    )
    if not older_years:
        return None
    return repository.statements(identifier, fiscal_year=max(older_years))


def _growth_metrics(
    statements: FinancialStatements,
    prior: FinancialStatements | None,
) -> GrowthMetrics:
    if prior is None:
        return GrowthMetrics()

    return GrowthMetrics(
        revenue_growth=_growth_rate(
            statements.income.revenue,
            prior.income.revenue,
        ),
        net_income_growth=_growth_rate(
            statements.income.net_income,
            prior.income.net_income,
        ),
        eps_diluted_growth=_growth_rate(
            statements.income.eps_diluted,
            prior.income.eps_diluted,
        ),
        free_cash_flow_growth=_growth_rate(
            statements.cash_flow.free_cash_flow,
            prior.cash_flow.free_cash_flow,
        ),
    )


def _growth_rate(
    current: FinancialValue | None,
    prior: FinancialValue | None,
) -> Decimal | None:
    if current is None or prior is None:
        return None
    if current.unit != prior.unit or prior.value <= 0:
        return None
    return (current.value - prior.value) / prior.value


def _efficiency_metrics(
    statements: FinancialStatements,
    prior: FinancialStatements | None,
) -> EfficiencyMetrics:
    net_income = statements.income.net_income
    revenue = statements.income.revenue
    equity = statements.balance.shareholders_equity
    assets = statements.balance.total_assets
    prior_equity = prior.balance.shareholders_equity if prior is not None else None
    prior_assets = prior.balance.total_assets if prior is not None else None

    average_equity = _average_balance(equity, prior_equity)
    average_assets = _average_balance(assets, prior_assets)
    return EfficiencyMetrics(
        return_on_equity=_safe_ratio(_amount(net_income), average_equity),
        return_on_assets=_safe_ratio(_amount(net_income), average_assets),
        asset_turnover=_safe_ratio(_amount(revenue), average_assets),
    )


def _liquidity_metrics(statements: FinancialStatements) -> LiquidityMetrics:
    return LiquidityMetrics(
        current_ratio=_safe_ratio(
            _amount(statements.balance.current_assets),
            _amount(statements.balance.current_liabilities),
        )
    )


def _leverage_metrics(statements: FinancialStatements) -> LeverageMetrics:
    liabilities = _amount(statements.balance.total_liabilities)
    return LeverageMetrics(
        debt_ratio=_safe_ratio(liabilities, _amount(statements.balance.total_assets)),
        debt_to_equity=_safe_ratio(
            liabilities,
            _amount(statements.balance.shareholders_equity),
        ),
    )


def _average_balance(
    current: FinancialValue | None,
    prior: FinancialValue | None,
) -> Decimal | None:
    if current is None:
        return None
    if prior is None or prior.unit != current.unit:
        return current.value
    return (current.value + prior.value) / Decimal("2")


def _safe_ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator
