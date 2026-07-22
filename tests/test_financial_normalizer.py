from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from axiom_engine.financial_normalizer import (
    FinancialNormalizationError,
    FinancialNormalizer,
)
from axiom_engine.financial_repository import (
    FinancialRecordNotFoundError,
    FinancialRepository,
)
from axiom_engine.financial_statement_models import (
    BalanceSheet,
    CashFlowStatement,
    FinancialStatements,
    FinancialValue,
    IncomeStatement,
)
from axiom_engine.normalized_financials import NormalizedFinancials


def _value(
    amount: str,
    *,
    concept: str,
    fiscal_year: int,
    unit: str = "USD",
    start: date | None = None,
    end: date | None = None,
) -> FinancialValue:
    return FinancialValue(
        value=Decimal(amount),
        unit=unit,
        taxonomy="us-gaap",
        concept=concept,
        filed=date(fiscal_year, 3, 1),
        form="10-K",
        fiscal_year=fiscal_year,
        fiscal_period="FY",
        start=start,
        end=end or date(fiscal_year - 1, 12, 31),
    )


def _statements(fiscal_year: int, *, revenue: str, cash: str, fcf: str) -> FinancialStatements:
    start = date(fiscal_year - 1, 1, 1)
    end = date(fiscal_year - 1, 12, 31)
    return FinancialStatements(
        cik="0001045810",
        entity_name="NVIDIA CORP",
        fiscal_year=fiscal_year,
        fiscal_period="FY",
        income=IncomeStatement(
            revenue=_value(
                revenue,
                concept="Revenues",
                fiscal_year=fiscal_year,
                start=start,
                end=end,
            ),
            net_income=_value(
                "50",
                concept="NetIncomeLoss",
                fiscal_year=fiscal_year,
                start=start,
                end=end,
            ),
            eps_diluted=_value(
                "2.00",
                concept="EarningsPerShareDiluted",
                fiscal_year=fiscal_year,
                unit="USD/shares",
                start=start,
                end=end,
            ),
        ),
        balance=BalanceSheet(
            cash=_value(
                cash,
                concept="CashAndCashEquivalentsAtCarryingValue",
                fiscal_year=fiscal_year,
            ),
            total_assets=_value("300", concept="Assets", fiscal_year=fiscal_year),
            shareholders_equity=_value(
                "120",
                concept="StockholdersEquity",
                fiscal_year=fiscal_year,
            ),
        ),
        cash_flow=CashFlowStatement(
            operating_cash_flow=_value(
                "80",
                concept="NetCashProvidedByUsedInOperatingActivities",
                fiscal_year=fiscal_year,
                start=start,
                end=end,
            ),
            capital_expenditure=_value(
                "10",
                concept="PaymentsToAcquireProductiveAssets",
                fiscal_year=fiscal_year,
                start=start,
                end=end,
            ),
            free_cash_flow=_value(
                fcf,
                concept="FreeCashFlow",
                fiscal_year=fiscal_year,
                start=start,
                end=end,
            ),
        ),
    )


def _repository() -> FinancialRepository:
    return FinancialRepository.from_statements(
        {
            "NVDA": (
                _statements(2026, revenue="200", cash="40", fcf="70"),
                _statements(2025, revenue="100", cash="20", fcf="35"),
            )
        }
    )


def test_normalizer_builds_latest_snapshot() -> None:
    normalized = FinancialNormalizer(_repository()).normalize("nvda")

    assert isinstance(normalized, NormalizedFinancials)
    assert normalized.identity.identifier == "NVDA"
    assert normalized.identity.cik == "0001045810"
    assert normalized.identity.entity_name == "NVIDIA CORP"
    assert normalized.identity.currency == "USD"
    assert normalized.fiscal_year == 2026
    assert normalized.fiscal_period == "FY"


def test_normalizer_maps_income_balance_and_cash_flow_values() -> None:
    normalized = FinancialNormalizer(_repository()).normalize("NVDA")

    assert normalized.income.revenue == Decimal("200")
    assert normalized.income.net_income == Decimal("50")
    assert normalized.income.eps_diluted == Decimal("2.00")
    assert normalized.balance.cash == Decimal("40")
    assert normalized.balance.total_assets == Decimal("300")
    assert normalized.cash_flow.free_cash_flow == Decimal("70")


def test_normalizer_sets_period_dates() -> None:
    normalized = FinancialNormalizer(_repository()).normalize("NVDA")

    assert normalized.period_start == date(2025, 1, 1)
    assert normalized.period_end == date(2025, 12, 31)


def test_metrics_remain_empty_in_commit_010b() -> None:
    normalized = FinancialNormalizer(_repository()).normalize("NVDA")

    assert normalized.profitability.net_margin is None
    assert normalized.profitability.gross_margin is None
    assert normalized.efficiency.return_on_equity is None
    assert normalized.liquidity.current_ratio is None
    assert normalized.leverage.debt_ratio is None


def test_repository_normalize_delegates_and_supports_fiscal_year() -> None:
    normalized = _repository().normalize("NVDA", fiscal_year=2025)

    assert normalized.fiscal_year == 2025
    assert normalized.income.revenue == Decimal("100")
    assert normalized.balance.cash == Decimal("20")
    assert normalized.cash_flow.free_cash_flow == Decimal("35")


def test_normalizer_preserves_missing_values() -> None:
    statements = _statements(2026, revenue="200", cash="40", fcf="70")
    statements = FinancialStatements(
        cik=statements.cik,
        entity_name=statements.entity_name,
        fiscal_year=statements.fiscal_year,
        fiscal_period=statements.fiscal_period,
        income=IncomeStatement(revenue=statements.income.revenue),
        balance=BalanceSheet(),
        cash_flow=CashFlowStatement(),
    )
    repository = FinancialRepository.from_statements({"NVDA": (statements,)})

    normalized = FinancialNormalizer(repository).normalize("NVDA")

    assert normalized.income.revenue == Decimal("200")
    assert normalized.income.net_income is None
    assert normalized.balance.cash is None
    assert normalized.cash_flow.free_cash_flow is None


def test_normalizer_propagates_unknown_company_and_year_errors() -> None:
    normalizer = FinancialNormalizer(_repository())

    with pytest.raises(FinancialRecordNotFoundError, match="company not found"):
        normalizer.normalize("UNKNOWN")
    with pytest.raises(FinancialRecordNotFoundError, match="fiscal year 2024"):
        normalizer.normalize("NVDA", fiscal_year=2024)


def test_normalizer_rejects_mixed_monetary_units() -> None:
    statements = _statements(2026, revenue="200", cash="40", fcf="70")
    mixed = FinancialStatements(
        cik=statements.cik,
        entity_name=statements.entity_name,
        fiscal_year=statements.fiscal_year,
        fiscal_period=statements.fiscal_period,
        income=statements.income,
        balance=BalanceSheet(
            cash=_value(
                "40",
                concept="CashAndCashEquivalentsAtCarryingValue",
                fiscal_year=2026,
                unit="EUR",
            )
        ),
        cash_flow=statements.cash_flow,
    )
    repository = FinancialRepository.from_statements({"NVDA": (mixed,)})

    with pytest.raises(FinancialNormalizationError, match="mixed monetary units"):
        FinancialNormalizer(repository).normalize("NVDA")
