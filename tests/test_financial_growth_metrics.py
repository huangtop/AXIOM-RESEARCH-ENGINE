from __future__ import annotations

from datetime import date
from decimal import Decimal

from axiom_engine.financial_repository import FinancialRepository
from axiom_engine.financial_statement_models import (
    BalanceSheet,
    CashFlowStatement,
    FinancialStatements,
    FinancialValue,
    IncomeStatement,
)


def _value(
    amount: str | None,
    *,
    concept: str,
    fiscal_year: int,
    unit: str = "USD",
) -> FinancialValue | None:
    if amount is None:
        return None
    return FinancialValue(
        value=Decimal(amount),
        unit=unit,
        taxonomy="us-gaap",
        concept=concept,
        filed=date(fiscal_year, 3, 1),
        form="10-K",
        fiscal_year=fiscal_year,
        fiscal_period="FY",
        start=date(fiscal_year - 1, 1, 1),
        end=date(fiscal_year - 1, 12, 31),
    )


def _statements(
    fiscal_year: int,
    *,
    revenue: str | None = "120",
    net_income: str | None = "30",
    eps_diluted: str | None = "6",
    free_cash_flow: str | None = "24",
    unit: str = "USD",
) -> FinancialStatements:
    return FinancialStatements(
        cik="0001045810",
        entity_name="NVIDIA CORP",
        fiscal_year=fiscal_year,
        fiscal_period="FY",
        income=IncomeStatement(
            revenue=_value(revenue, concept="Revenues", fiscal_year=fiscal_year, unit=unit),
            net_income=_value(
                net_income,
                concept="NetIncomeLoss",
                fiscal_year=fiscal_year,
                unit=unit,
            ),
            eps_diluted=_value(
                eps_diluted,
                concept="EarningsPerShareDiluted",
                fiscal_year=fiscal_year,
                unit="USD/shares" if unit == "USD" else f"{unit}/shares",
            ),
        ),
        balance=BalanceSheet(),
        cash_flow=CashFlowStatement(
            free_cash_flow=_value(
                free_cash_flow,
                concept="FreeCashFlow",
                fiscal_year=fiscal_year,
                unit=unit,
            )
        ),
    )


def _repository(*statements: FinancialStatements) -> FinancialRepository:
    return FinancialRepository.from_statements({"NVDA": statements})


def test_calculates_year_over_year_growth_metrics() -> None:
    repository = _repository(
        _statements(2026),
        _statements(
            2025,
            revenue="100",
            net_income="20",
            eps_diluted="4",
            free_cash_flow="20",
        ),
    )

    growth = repository.normalize("NVDA").growth

    assert growth.revenue_growth == Decimal("0.2")
    assert growth.net_income_growth == Decimal("0.5")
    assert growth.eps_diluted_growth == Decimal("0.5")
    assert growth.free_cash_flow_growth == Decimal("0.2")


def test_growth_uses_nearest_older_available_year() -> None:
    repository = _repository(
        _statements(2026, revenue="150"),
        _statements(2023, revenue="100"),
    )

    assert repository.normalize("NVDA").growth.revenue_growth == Decimal("0.5")


def test_no_prior_period_returns_empty_growth_metrics() -> None:
    growth = _repository(_statements(2026)).normalize("NVDA").growth

    assert growth.revenue_growth is None
    assert growth.net_income_growth is None
    assert growth.eps_diluted_growth is None
    assert growth.free_cash_flow_growth is None


def test_missing_values_only_disable_their_metric() -> None:
    repository = _repository(
        _statements(2026, net_income=None),
        _statements(2025, revenue="100", net_income="20", eps_diluted="4", free_cash_flow="20"),
    )

    growth = repository.normalize("NVDA").growth

    assert growth.revenue_growth == Decimal("0.2")
    assert growth.net_income_growth is None
    assert growth.eps_diluted_growth == Decimal("0.5")
    assert growth.free_cash_flow_growth == Decimal("0.2")


def test_zero_or_negative_prior_base_is_not_reported_as_growth() -> None:
    repository = _repository(
        _statements(2026),
        _statements(2025, revenue="0", net_income="-10", eps_diluted="0", free_cash_flow="-5"),
    )

    growth = repository.normalize("NVDA").growth

    assert growth.revenue_growth is None
    assert growth.net_income_growth is None
    assert growth.eps_diluted_growth is None
    assert growth.free_cash_flow_growth is None


def test_unit_mismatch_returns_none_for_only_that_metric() -> None:
    current = _statements(2026)
    prior = _statements(2025, revenue="100", net_income="20", eps_diluted="4", free_cash_flow="20")
    assert prior.income.revenue is not None
    mismatched_revenue = FinancialValue(
        value=prior.income.revenue.value,
        unit="EUR",
        taxonomy=prior.income.revenue.taxonomy,
        concept=prior.income.revenue.concept,
        filed=prior.income.revenue.filed,
        form=prior.income.revenue.form,
        fiscal_year=prior.income.revenue.fiscal_year,
        fiscal_period=prior.income.revenue.fiscal_period,
        start=prior.income.revenue.start,
        end=prior.income.revenue.end,
    )
    prior = FinancialStatements(
        cik=prior.cik,
        entity_name=prior.entity_name,
        fiscal_year=prior.fiscal_year,
        fiscal_period=prior.fiscal_period,
        income=IncomeStatement(
            revenue=mismatched_revenue,
            net_income=prior.income.net_income,
            eps_diluted=prior.income.eps_diluted,
        ),
        balance=prior.balance,
        cash_flow=prior.cash_flow,
    )

    growth = _repository(current, prior).normalize("NVDA").growth

    assert growth.revenue_growth is None
    assert growth.net_income_growth == Decimal("0.5")


def test_preserves_decimal_precision_without_rounding() -> None:
    repository = _repository(
        _statements(2026, revenue="4"),
        _statements(2025, revenue="3"),
    )

    assert repository.normalize("NVDA").growth.revenue_growth == Decimal("1") / Decimal("3")
