from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from axiom_engine.financial_statement_builder import FinancialStatementBuildError, FinancialStatementBuilder


def _obs(value: int, *, fy: int = 2025, fp: str = "FY", form: str = "10-K", filed: str = "2025-03-01", start: str | None = "2024-01-01", end: str = "2024-12-31") -> dict[str, object]:
    item: dict[str, object] = {"val": value, "fy": fy, "fp": fp, "form": form, "filed": filed, "end": end}
    if start:
        item["start"] = start
    return item


def _payload() -> dict[str, object]:
    return {
        "cik": 1045810,
        "entityName": "NVIDIA Corporation",
        "facts": {"us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [_obs(60000)]}},
            "OperatingIncomeLoss": {"units": {"USD": [_obs(32000)]}},
            "NetIncomeLoss": {"units": {"USD": [_obs(29000)]}},
            "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [_obs(8000, start=None)]}},
            "Assets": {"units": {"USD": [_obs(65000, start=None)]}},
            "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [_obs(28000)]}},
            "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [_obs(3000)]}},
        }},
    }


def test_builder_resolves_statements_and_fcf() -> None:
    statements = FinancialStatementBuilder().build(_payload())
    assert statements.cik == "0001045810"
    assert statements.fiscal_year == 2025
    assert statements.income.revenue is not None
    assert statements.income.revenue.value == Decimal("60000")
    assert statements.balance.cash is not None
    assert statements.balance.cash.value == Decimal("8000")
    assert statements.cash_flow.free_cash_flow is not None
    assert statements.cash_flow.free_cash_flow.value == Decimal("25000")


def test_alias_priority_wins_over_newer_fallback() -> None:
    payload = _payload()
    payload["facts"]["us-gaap"]["Revenues"] = {"units": {"USD": [_obs(999999, filed="2025-04-01")]}}
    statements = FinancialStatementBuilder().build(payload)
    assert statements.income.revenue is not None
    assert statements.income.revenue.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_requested_year_and_filing_cutoff() -> None:
    payload = _payload()
    observations = payload["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
    observations.extend([
        _obs(40000, fy=2024, filed="2024-03-01", start="2023-01-01", end="2023-12-31"),
        _obs(80000, filed="2025-05-01"),
    ])
    old = FinancialStatementBuilder().build(payload, fiscal_year=2024)
    cutoff = FinancialStatementBuilder().build(payload, filed_on_or_before=date(2025, 3, 31))
    assert old.income.revenue is not None and old.income.revenue.value == Decimal("40000")
    assert cutoff.income.revenue is not None and cutoff.income.revenue.value == Decimal("60000")


def test_missing_concepts_are_none() -> None:
    payload = {"cik": "1", "entityName": "Sparse", "facts": {"us-gaap": {"Revenues": {"units": {"USD": [_obs(100)]}}}}}
    statements = FinancialStatementBuilder().build(payload)
    assert statements.income.revenue is not None
    assert statements.income.net_income is None
    assert statements.balance.total_assets is None
    assert statements.cash_flow.free_cash_flow is None


def test_quarterly_only_payload_is_rejected() -> None:
    payload = {"cik": "1", "entityName": "Quarterly", "facts": {"us-gaap": {"Revenues": {"units": {"USD": [_obs(10, fp="Q1", form="10-Q")]}}}}}
    with pytest.raises(FinancialStatementBuildError, match="no FY observations"):
        FinancialStatementBuilder().build(payload)
