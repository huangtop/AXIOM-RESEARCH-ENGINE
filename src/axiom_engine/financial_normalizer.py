from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from .financial_repository import FinancialRepository
from .financial_statement_models import FinancialStatements, FinancialValue
from .normalized_financials import (
    EfficiencyMetrics,
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
            efficiency=EfficiencyMetrics(),
            liquidity=LiquidityMetrics(),
            leverage=LeverageMetrics(),
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


def _safe_ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator
