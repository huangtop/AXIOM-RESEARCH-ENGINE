from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class FinancialValue:
    value: Decimal
    unit: str
    taxonomy: str
    concept: str
    filed: date
    form: str
    fiscal_year: int | None
    fiscal_period: str | None
    start: date | None = None
    end: date | None = None
    frame: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": str(self.value), "unit": self.unit, "taxonomy": self.taxonomy,
            "concept": self.concept, "filed": self.filed.isoformat(), "form": self.form,
            "fiscal_year": self.fiscal_year, "fiscal_period": self.fiscal_period,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None, "frame": self.frame,
        }


@dataclass(frozen=True, slots=True)
class IncomeStatement:
    revenue: FinancialValue | None = None
    gross_profit: FinancialValue | None = None
    operating_income: FinancialValue | None = None
    net_income: FinancialValue | None = None
    eps_basic: FinancialValue | None = None
    eps_diluted: FinancialValue | None = None


@dataclass(frozen=True, slots=True)
class BalanceSheet:
    cash: FinancialValue | None = None
    accounts_receivable: FinancialValue | None = None
    inventory: FinancialValue | None = None
    current_assets: FinancialValue | None = None
    current_liabilities: FinancialValue | None = None
    total_assets: FinancialValue | None = None
    total_liabilities: FinancialValue | None = None
    shareholders_equity: FinancialValue | None = None


@dataclass(frozen=True, slots=True)
class CashFlowStatement:
    operating_cash_flow: FinancialValue | None = None
    capital_expenditure: FinancialValue | None = None
    free_cash_flow: FinancialValue | None = None


@dataclass(frozen=True, slots=True)
class FinancialStatements:
    cik: str
    entity_name: str
    fiscal_year: int
    fiscal_period: str
    income: IncomeStatement
    balance: BalanceSheet
    cash_flow: CashFlowStatement

    def to_dict(self) -> dict[str, Any]:
        def convert(statement: object) -> dict[str, Any]:
            output: dict[str, Any] = {}
            for field in fields(statement):
                value = getattr(statement, field.name)
                output[field.name] = value.to_dict() if isinstance(value, FinancialValue) else None
            return output

        return {
            "cik": self.cik, "entity_name": self.entity_name,
            "fiscal_year": self.fiscal_year, "fiscal_period": self.fiscal_period,
            "income_statement": convert(self.income),
            "balance_sheet": convert(self.balance),
            "cash_flow_statement": convert(self.cash_flow),
        }
