from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class StatementKind(StrEnum):
    INCOME = "income"
    BALANCE = "balance"
    CASH_FLOW = "cash_flow"


@dataclass(frozen=True, slots=True)
class ConceptDefinition:
    field_name: str
    statement: StatementKind
    aliases: tuple[str, ...]
    preferred_units: tuple[str, ...]
    instant: bool = False


DEFAULT_CONCEPTS: tuple[ConceptDefinition, ...] = (
    ConceptDefinition("revenue", StatementKind.INCOME, ("RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "Revenues"), ("USD",)),
    ConceptDefinition("gross_profit", StatementKind.INCOME, ("GrossProfit",), ("USD",)),
    ConceptDefinition("operating_income", StatementKind.INCOME, ("OperatingIncomeLoss",), ("USD",)),
    ConceptDefinition("net_income", StatementKind.INCOME, ("NetIncomeLoss", "ProfitLoss"), ("USD",)),
    ConceptDefinition("eps_basic", StatementKind.INCOME, ("EarningsPerShareBasic", "EarningsPerShareBasicAndDiluted"), ("USD/shares", "USD/share")),
    ConceptDefinition("eps_diluted", StatementKind.INCOME, ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"), ("USD/shares", "USD/share")),
    ConceptDefinition("cash", StatementKind.BALANCE, ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"), ("USD",), instant=True),
    ConceptDefinition("accounts_receivable", StatementKind.BALANCE, ("AccountsReceivableNetCurrent", "AccountsNotesAndLoansReceivableNetCurrent"), ("USD",), instant=True),
    ConceptDefinition("inventory", StatementKind.BALANCE, ("InventoryNet",), ("USD",), instant=True),
    ConceptDefinition("total_assets", StatementKind.BALANCE, ("Assets",), ("USD",), instant=True),
    ConceptDefinition("total_liabilities", StatementKind.BALANCE, ("Liabilities",), ("USD",), instant=True),
    ConceptDefinition("shareholders_equity", StatementKind.BALANCE, ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "EntityCommonStockholdersEquity", "PartnersCapital"), ("USD",), instant=True),
    ConceptDefinition("operating_cash_flow", StatementKind.CASH_FLOW, ("NetCashProvidedByUsedInOperatingActivities",), ("USD",)),
    ConceptDefinition("capital_expenditure", StatementKind.CASH_FLOW, ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsForAdditionsToPropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets", "PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets", "PropertyPlantAndEquipmentAdditions"), ("USD",)),
)


class FinancialConceptRegistry:
    def __init__(self, definitions: tuple[ConceptDefinition, ...] = DEFAULT_CONCEPTS) -> None:
        self._definitions = definitions
        names = [definition.field_name for definition in definitions]
        if len(names) != len(set(names)):
            raise ValueError("financial concept field names must be unique")

    @property
    def definitions(self) -> tuple[ConceptDefinition, ...]:
        return self._definitions

    def for_statement(self, statement: StatementKind) -> tuple[ConceptDefinition, ...]:
        return tuple(item for item in self._definitions if item.statement == statement)
