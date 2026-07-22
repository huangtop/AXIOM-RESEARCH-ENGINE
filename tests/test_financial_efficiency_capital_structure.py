from __future__ import annotations

from datetime import date
from decimal import Decimal

from axiom_engine.financial_repository import FinancialRepository
from axiom_engine.financial_statement_builder import FinancialStatementBuilder
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
    fiscal_year: int,
    unit: str = "USD",
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
        end=date(fiscal_year - 1, 12, 31),
    )


def _statements(
    fiscal_year: int,
    *,
    revenue: str = "200",
    net_income: str = "40",
    assets: str | None = "300",
    liabilities: str | None = "120",
    equity: str | None = "180",
    current_assets: str | None = "150",
    current_liabilities: str | None = "75",
    unit: str = "USD",
) -> FinancialStatements:
    def value(amount: str | None, concept: str) -> FinancialValue | None:
        if amount is None:
            return None
        return _value(
            amount,
            concept=concept,
            fiscal_year=fiscal_year,
            unit=unit,
        )

    return FinancialStatements(
        cik="0001045810",
        entity_name="NVIDIA CORP",
        fiscal_year=fiscal_year,
        fiscal_period="FY",
        income=IncomeStatement(
            revenue=value(revenue, "Revenues"),
            net_income=value(net_income, "NetIncomeLoss"),
        ),
        balance=BalanceSheet(
            current_assets=value(current_assets, "AssetsCurrent"),
            current_liabilities=value(current_liabilities, "LiabilitiesCurrent"),
            total_assets=value(assets, "Assets"),
            total_liabilities=value(liabilities, "Liabilities"),
            shareholders_equity=value(equity, "StockholdersEquity"),
        ),
        cash_flow=CashFlowStatement(),
    )


def _repository(*statements: FinancialStatements) -> FinancialRepository:
    return FinancialRepository.from_statements({"NVDA": statements})


def test_efficiency_metrics_use_average_assets_and_equity() -> None:
    repository = _repository(
        _statements(2026, assets="300", equity="180"),
        _statements(2025, assets="200", equity="120"),
    )

    metrics = repository.normalize("NVDA").efficiency

    assert metrics.return_on_equity == Decimal("40") / Decimal("150")
    assert metrics.return_on_assets == Decimal("40") / Decimal("250")
    assert metrics.asset_turnover == Decimal("200") / Decimal("250")


def test_efficiency_metrics_fall_back_to_current_balance_without_prior_year() -> None:
    metrics = _repository(_statements(2026)).normalize("NVDA").efficiency

    assert metrics.return_on_equity == Decimal("40") / Decimal("180")
    assert metrics.return_on_assets == Decimal("40") / Decimal("300")
    assert metrics.asset_turnover == Decimal("200") / Decimal("300")


def test_efficiency_uses_nearest_older_available_year() -> None:
    repository = _repository(
        _statements(2026, assets="300", equity="180"),
        _statements(2023, assets="100", equity="60"),
    )

    metrics = repository.normalize("NVDA").efficiency

    assert metrics.return_on_equity == Decimal("40") / Decimal("120")
    assert metrics.return_on_assets == Decimal("40") / Decimal("200")


def test_current_ratio_uses_reported_current_balances() -> None:
    normalized = _repository(_statements(2026)).normalize("NVDA")

    assert normalized.balance.current_assets == Decimal("150")
    assert normalized.balance.current_liabilities == Decimal("75")
    assert normalized.liquidity.current_ratio == Decimal("2")


def test_leverage_metrics_use_total_liabilities() -> None:
    leverage = _repository(_statements(2026)).normalize("NVDA").leverage

    assert leverage.debt_ratio == Decimal("0.4")
    assert leverage.debt_to_equity == Decimal("120") / Decimal("180")


def test_missing_metric_inputs_return_none_independently() -> None:
    normalized = _repository(
        _statements(
            2026,
            assets=None,
            equity=None,
            current_assets=None,
            liabilities="120",
        )
    ).normalize("NVDA")

    assert normalized.efficiency.return_on_equity is None
    assert normalized.efficiency.return_on_assets is None
    assert normalized.efficiency.asset_turnover is None
    assert normalized.liquidity.current_ratio is None
    assert normalized.leverage.debt_ratio is None
    assert normalized.leverage.debt_to_equity is None


def test_zero_denominators_return_none() -> None:
    normalized = _repository(
        _statements(
            2026,
            assets="0",
            equity="0",
            current_liabilities="0",
        )
    ).normalize("NVDA")

    assert normalized.efficiency.return_on_equity is None
    assert normalized.efficiency.return_on_assets is None
    assert normalized.efficiency.asset_turnover is None
    assert normalized.liquidity.current_ratio is None
    assert normalized.leverage.debt_ratio is None
    assert normalized.leverage.debt_to_equity is None


def test_prior_balance_with_different_unit_is_not_averaged() -> None:
    repository = _repository(
        _statements(2026, assets="300", equity="180"),
        _statements(2025, assets="200", equity="120", unit="EUR"),
    )

    metrics = repository.normalize("NVDA").efficiency

    assert metrics.return_on_equity == Decimal("40") / Decimal("180")
    assert metrics.return_on_assets == Decimal("40") / Decimal("300")


def test_builder_maps_current_asset_and_liability_concepts() -> None:
    def observation(value: int) -> dict[str, object]:
        return {
            "val": value,
            "fy": 2026,
            "fp": "FY",
            "form": "10-K",
            "filed": "2026-03-01",
            "end": "2026-01-25",
        }

    payload = {
        "cik": 1045810,
        "entityName": "NVIDIA CORP",
        "facts": {
            "us-gaap": {
                "AssetsCurrent": {"units": {"USD": [observation(150)]}},
                "LiabilitiesCurrent": {"units": {"USD": [observation(75)]}},
                "Assets": {"units": {"USD": [observation(300)]}},
            }
        },
    }

    statements = FinancialStatementBuilder().build(payload, fiscal_year=2026)

    assert statements.balance.current_assets is not None
    assert statements.balance.current_assets.value == Decimal("150")
    assert statements.balance.current_liabilities is not None
    assert statements.balance.current_liabilities.value == Decimal("75")
