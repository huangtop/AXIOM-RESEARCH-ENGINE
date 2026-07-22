from __future__ import annotations

from decimal import Decimal

from axiom_engine.financial_statement_builder import FinancialStatementBuilder


def _obs(
    value: int,
    *,
    end: str,
    start: str | None = None,
    filed: str = "2026-02-25",
) -> dict[str, object]:
    item: dict[str, object] = {
        "val": value,
        "fy": 2026,
        "fp": "FY",
        "form": "10-K",
        "filed": filed,
        "end": end,
    }
    if start is not None:
        item["start"] = start
    return item


def test_balance_sheet_values_align_to_latest_statement_date() -> None:
    payload = {
        "cik": 1045810,
        "entityName": "NVIDIA CORP",
        "facts": {
            "us-gaap": {
                "Assets": {"units": {"USD": [_obs(111_601, end="2025-01-26")]}},
                "Liabilities": {"units": {"USD": [_obs(32_274, end="2025-01-26")]}},
                "StockholdersEquity": {
                    "units": {
                        "USD": [
                            _obs(22_101, end="2023-01-29"),
                            _obs(79_327, end="2025-01-26", filed="2025-02-26"),
                        ]
                    }
                },
            }
        },
    }

    statements = FinancialStatementBuilder().build(payload)

    assert statements.balance.shareholders_equity is not None
    assert statements.balance.shareholders_equity.end.isoformat() == "2025-01-26"
    assert statements.balance.shareholders_equity.value == Decimal("79327")


def test_duration_values_align_to_latest_annual_period() -> None:
    payload = {
        "cik": 1045810,
        "entityName": "NVIDIA CORP",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            _obs(60_922, start="2023-01-30", end="2024-01-28"),
                            _obs(130_497, start="2024-01-29", end="2025-01-26"),
                        ]
                    }
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {
                        "USD": [
                            _obs(28_090, start="2023-01-30", end="2024-01-28"),
                            _obs(64_089, start="2024-01-29", end="2025-01-26"),
                        ]
                    }
                },
            }
        },
    }

    statements = FinancialStatementBuilder().build(payload)

    assert statements.income.revenue is not None
    assert statements.income.revenue.end.isoformat() == "2025-01-26"
    assert statements.cash_flow.operating_cash_flow is not None
    assert statements.cash_flow.operating_cash_flow.end.isoformat() == "2025-01-26"


def test_capex_fallback_alias_enables_free_cash_flow() -> None:
    payload = {
        "cik": 1,
        "entityName": "Fallback Alias Corp",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": [_obs(100, start="2024-01-01", end="2024-12-31")]}
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {"USD": [_obs(40, start="2024-01-01", end="2024-12-31")]}
                },
                "PaymentsToAcquireProductiveAssets": {
                    "units": {"USD": [_obs(9, start="2024-01-01", end="2024-12-31")]}
                },
            }
        },
    }

    statements = FinancialStatementBuilder().build(payload)

    assert statements.cash_flow.capital_expenditure is not None
    assert statements.cash_flow.capital_expenditure.concept == "PaymentsToAcquireProductiveAssets"
    assert statements.cash_flow.free_cash_flow is not None
    assert statements.cash_flow.free_cash_flow.value == Decimal("31")
