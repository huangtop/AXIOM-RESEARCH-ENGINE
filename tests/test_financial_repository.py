from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from axiom_engine.financial_repository import (
    FinancialCompany,
    FinancialRecordNotFoundError,
    FinancialRepository,
    FinancialRepositoryIntegrityError,
)
from axiom_engine.financial_statement_models import (
    BalanceSheet,
    CashFlowStatement,
    FinancialStatements,
    FinancialValue,
    IncomeStatement,
)


def _value(
    value: str,
    *,
    concept: str,
    fiscal_year: int,
    start: date | None = None,
    end: date | None = None,
) -> FinancialValue:
    return FinancialValue(
        value=Decimal(value),
        unit="USD",
        taxonomy="us-gaap",
        concept=concept,
        filed=date(fiscal_year, 3, 1),
        form="10-K",
        fiscal_year=fiscal_year,
        fiscal_period="FY",
        start=start,
        end=end or date(fiscal_year - 1, 12, 31),
    )


def _statements(
    fiscal_year: int,
    *,
    revenue: str,
    net_income: str,
    equity: str,
    operating_cash_flow: str,
    capital_expenditure: str,
) -> FinancialStatements:
    period_start = date(fiscal_year - 1, 1, 1)
    period_end = date(fiscal_year - 1, 12, 31)
    ocf = _value(
        operating_cash_flow,
        concept="NetCashProvidedByUsedInOperatingActivities",
        fiscal_year=fiscal_year,
        start=period_start,
        end=period_end,
    )
    capex = _value(
        capital_expenditure,
        concept="PaymentsToAcquireProductiveAssets",
        fiscal_year=fiscal_year,
        start=period_start,
        end=period_end,
    )
    fcf = _value(
        str(Decimal(operating_cash_flow) - abs(Decimal(capital_expenditure))),
        concept="FreeCashFlow",
        fiscal_year=fiscal_year,
        start=period_start,
        end=period_end,
    )
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
                start=period_start,
                end=period_end,
            ),
            net_income=_value(
                net_income,
                concept="NetIncomeLoss",
                fiscal_year=fiscal_year,
                start=period_start,
                end=period_end,
            ),
        ),
        balance=BalanceSheet(
            shareholders_equity=_value(
                equity,
                concept="StockholdersEquity",
                fiscal_year=fiscal_year,
                end=period_end,
            )
        ),
        cash_flow=CashFlowStatement(
            operating_cash_flow=ocf,
            capital_expenditure=capex,
            free_cash_flow=fcf,
        ),
    )


def _repository() -> FinancialRepository:
    return FinancialRepository.from_statements(
        {
            "NVDA": [
                _statements(
                    2026,
                    revenue="200",
                    net_income="50",
                    equity="120",
                    operating_cash_flow="80",
                    capital_expenditure="10",
                ),
                _statements(
                    2025,
                    revenue="100",
                    net_income="20",
                    equity="80",
                    operating_cash_flow="40",
                    capital_expenditure="5",
                ),
            ]
        }
    )


def test_statement_queries_default_to_latest_year() -> None:
    repository = _repository()

    assert repository.fiscal_years("nvda") == (2026, 2025)
    assert repository.statements("NVDA").fiscal_year == 2026
    assert repository.balance_sheet("NVDA", fiscal_year=2025).shareholders_equity is not None
    assert repository.income_statement("NVDA").revenue is not None
    assert repository.cash_flow("NVDA").free_cash_flow is not None


def test_repository_resolves_cik_and_rejects_unknown_year() -> None:
    repository = _repository()

    assert repository.statements("1045810").fiscal_year == 2026
    with pytest.raises(FinancialRecordNotFoundError, match="fiscal year 2024"):
        repository.statements("NVDA", fiscal_year=2024)


def test_revenue_history_and_free_cash_flow() -> None:
    repository = _repository()

    history = repository.revenue_history("NVDA", years=2)
    assert [item.fiscal_year for item in history] == [2026, 2025]
    assert [item.value for item in history] == [Decimal("200"), Decimal("100")]
    assert repository.free_cash_flow("NVDA").value == Decimal("70")


def test_net_margin_and_roe_use_canonical_values() -> None:
    repository = _repository()

    assert repository.net_margin("NVDA") == Decimal("0.25")
    assert repository.roe("NVDA") == Decimal("0.5")
    assert repository.roe("NVDA", fiscal_year=2025) == Decimal("0.25")


def test_duplicate_years_are_rejected() -> None:
    statement = _statements(
        2026,
        revenue="200",
        net_income="50",
        equity="120",
        operating_cash_flow="80",
        capital_expenditure="10",
    )
    company = FinancialCompany(
        identifier="NVDA",
        cik=statement.cik,
        entity_name=statement.entity_name,
        statements=(statement, statement),
    )

    with pytest.raises(FinancialRepositoryIntegrityError, match="duplicate fiscal years"):
        FinancialRepository([company])


def _obs(
    value: int,
    *,
    fy: int,
    start: str | None,
    end: str,
) -> dict[str, object]:
    observation: dict[str, object] = {
        "val": value,
        "fy": fy,
        "fp": "FY",
        "form": "10-K",
        "filed": f"{fy}-03-01",
        "end": end,
    }
    if start is not None:
        observation["start"] = start
    return observation


def test_from_company_facts_builds_multi_year_repository() -> None:
    payload = {
        "cik": 1045810,
        "entityName": "NVIDIA CORP",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            _obs(100, fy=2025, start="2023-01-01", end="2023-12-31"),
                            _obs(200, fy=2026, start="2024-01-01", end="2024-12-31"),
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            _obs(20, fy=2025, start="2023-01-01", end="2023-12-31"),
                            _obs(50, fy=2026, start="2024-01-01", end="2024-12-31"),
                        ]
                    }
                },
                "StockholdersEquity": {
                    "units": {
                        "USD": [
                            _obs(80, fy=2025, start=None, end="2023-12-31"),
                            _obs(120, fy=2026, start=None, end="2024-12-31"),
                        ]
                    }
                },
            }
        },
    }

    repository = FinancialRepository.from_company_facts({"NVDA": payload})

    assert repository.fiscal_years("NVDA") == (2026, 2025)
    assert repository.net_margin("NVDA") == Decimal("0.25")
    assert repository.roe("NVDA") == Decimal("0.5")
