from __future__ import annotations

from datetime import date
from decimal import Decimal

from axiom_engine.financial_normalizer import FinancialNormalizer
from axiom_engine.financial_repository import FinancialRepository
from axiom_engine.financial_statement_models import (
    BalanceSheet,
    CashFlowStatement,
    FinancialStatements,
    FinancialValue,
    IncomeStatement,
)


def _value(
    amount: str,
    *,
    concept: str,
    fiscal_year: int = 2026,
    start: date | None = None,
) -> FinancialValue:
    return FinancialValue(
        value=Decimal(amount),
        unit="USD",
        taxonomy="us-gaap",
        concept=concept,
        filed=date(2026, 3, 1),
        form="10-K",
        fiscal_year=fiscal_year,
        fiscal_period="FY",
        start=start,
        end=date(2026, 1, 25),
    )


def _repository(
    *,
    revenue: str | None = "200",
    gross_profit: str | None = "120",
    operating_income: str | None = "80",
    net_income: str | None = "50",
    free_cash_flow: str | None = "70",
) -> FinancialRepository:
    start = date(2025, 1, 27)

    def duration(amount: str | None, concept: str) -> FinancialValue | None:
        if amount is None:
            return None
        return _value(amount, concept=concept, start=start)

    statements = FinancialStatements(
        cik="0001045810",
        entity_name="NVIDIA CORP",
        fiscal_year=2026,
        fiscal_period="FY",
        income=IncomeStatement(
            revenue=duration(revenue, "Revenues"),
            gross_profit=duration(gross_profit, "GrossProfit"),
            operating_income=duration(operating_income, "OperatingIncomeLoss"),
            net_income=duration(net_income, "NetIncomeLoss"),
        ),
        balance=BalanceSheet(),
        cash_flow=CashFlowStatement(
            free_cash_flow=duration(free_cash_flow, "FreeCashFlow"),
        ),
    )
    return FinancialRepository.from_statements({"NVDA": (statements,)})


def _normalize(**kwargs: str | None):
    return FinancialNormalizer(_repository(**kwargs)).normalize("NVDA")


def test_calculates_gross_margin() -> None:
    assert _normalize().profitability.gross_margin == Decimal("0.6")


def test_calculates_operating_margin() -> None:
    assert _normalize().profitability.operating_margin == Decimal("0.4")


def test_calculates_net_margin() -> None:
    assert _normalize().profitability.net_margin == Decimal("0.25")


def test_calculates_free_cash_flow_margin() -> None:
    assert _normalize().profitability.free_cash_flow_margin == Decimal("0.35")


def test_preserves_decimal_precision_without_rounding() -> None:
    normalized = _normalize(revenue="3", net_income="1")

    assert normalized.profitability.net_margin == Decimal("1") / Decimal("3")


def test_missing_numerator_produces_none_for_only_that_metric() -> None:
    normalized = _normalize(gross_profit=None)

    assert normalized.profitability.gross_margin is None
    assert normalized.profitability.operating_margin == Decimal("0.4")
    assert normalized.profitability.net_margin == Decimal("0.25")
    assert normalized.profitability.free_cash_flow_margin == Decimal("0.35")


def test_missing_revenue_produces_no_profitability_margins() -> None:
    metrics = _normalize(revenue=None).profitability

    assert metrics.gross_margin is None
    assert metrics.operating_margin is None
    assert metrics.net_margin is None
    assert metrics.free_cash_flow_margin is None


def test_zero_revenue_produces_no_profitability_margins() -> None:
    metrics = _normalize(revenue="0").profitability

    assert metrics.gross_margin is None
    assert metrics.operating_margin is None
    assert metrics.net_margin is None
    assert metrics.free_cash_flow_margin is None
