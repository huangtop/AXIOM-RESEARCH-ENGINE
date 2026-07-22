from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from .financial_statement_builder import (
    FinancialStatementBuildError,
    FinancialStatementBuilder,
)
from .financial_statement_models import (
    BalanceSheet,
    CashFlowStatement,
    FinancialStatements,
    FinancialValue,
    IncomeStatement,
)


class FinancialRepositoryError(RuntimeError):
    """Base error for Financial Repository operations."""


class FinancialRecordNotFoundError(FinancialRepositoryError, LookupError):
    """Raised when a company or fiscal year cannot be found."""


class FinancialRepositoryIntegrityError(FinancialRepositoryError, ValueError):
    """Raised when duplicate identifiers or statement years are supplied."""


@dataclass(frozen=True, slots=True)
class FinancialCompany:
    """Canonical annual statements for one company."""

    identifier: str
    cik: str
    entity_name: str
    statements: tuple[FinancialStatements, ...]

    @property
    def fiscal_years(self) -> tuple[int, ...]:
        return tuple(item.fiscal_year for item in self.statements)

    @property
    def latest(self) -> FinancialStatements:
        if not self.statements:
            raise FinancialRecordNotFoundError(
                f"company has no financial statements: {self.identifier}"
            )
        return self.statements[0]


class FinancialRepository:
    """Read-only query and analysis layer over canonical annual statements.

    Ratios are returned as decimal fractions. For example, ``Decimal("0.25")``
    represents 25 percent.
    """

    def __init__(self, companies: Iterable[FinancialCompany]) -> None:
        self._companies: dict[str, FinancialCompany] = {}
        self._identifier_index: dict[str, FinancialCompany] = {}
        for company in companies:
            normalized = self._normalize_company(company)
            primary_key = normalized.identifier.upper()
            if primary_key in self._companies:
                raise FinancialRepositoryIntegrityError(
                    f"duplicate financial company identifier: {normalized.identifier}"
                )
            self._companies[primary_key] = normalized
            self._index_identifier(normalized.identifier, normalized)
            self._index_identifier(normalized.cik, normalized)

    @classmethod
    def from_statements(
        cls,
        statements_by_identifier: Mapping[str, Iterable[FinancialStatements]],
    ) -> FinancialRepository:
        companies: list[FinancialCompany] = []
        for identifier, statements in statements_by_identifier.items():
            values = tuple(statements)
            if not values:
                raise FinancialRepositoryIntegrityError(
                    f"no statements supplied for {identifier}"
                )
            companies.append(
                FinancialCompany(
                    identifier=identifier,
                    cik=values[0].cik,
                    entity_name=values[0].entity_name,
                    statements=values,
                )
            )
        return cls(companies)

    @classmethod
    def from_company_facts(
        cls,
        company_facts_by_identifier: Mapping[str, object],
        *,
        builder: FinancialStatementBuilder | None = None,
        fiscal_period: str = "FY",
        filed_on_or_before: date | None = None,
    ) -> FinancialRepository:
        """Build all discoverable annual statement years for each company payload."""

        statement_builder = builder or FinancialStatementBuilder()
        companies: list[FinancialCompany] = []
        for identifier, company_facts in company_facts_by_identifier.items():
            years = _annual_fiscal_years(
                company_facts,
                fiscal_period=fiscal_period,
                filed_on_or_before=filed_on_or_before,
            )
            statements: list[FinancialStatements] = []
            for fiscal_year in years:
                try:
                    statements.append(
                        statement_builder.build(
                            company_facts,
                            fiscal_year=fiscal_year,
                            fiscal_period=fiscal_period,
                            filed_on_or_before=filed_on_or_before,
                        )
                    )
                except FinancialStatementBuildError:
                    continue
            if not statements:
                raise FinancialRepositoryIntegrityError(
                    f"no canonical annual statements could be built for {identifier}"
                )
            companies.append(
                FinancialCompany(
                    identifier=identifier,
                    cik=statements[0].cik,
                    entity_name=statements[0].entity_name,
                    statements=tuple(statements),
                )
            )
        return cls(companies)

    def list_companies(self) -> tuple[FinancialCompany, ...]:
        return tuple(self._companies.values())

    def resolve_company(self, identifier: str) -> FinancialCompany:
        key = _normalize_identifier(identifier)
        try:
            return self._identifier_index[key]
        except KeyError as exc:
            raise FinancialRecordNotFoundError(
                f"financial company not found: {identifier}"
            ) from exc

    def fiscal_years(self, identifier: str) -> tuple[int, ...]:
        return self.resolve_company(identifier).fiscal_years

    def statements(
        self,
        identifier: str,
        *,
        fiscal_year: int | None = None,
    ) -> FinancialStatements:
        company = self.resolve_company(identifier)
        if fiscal_year is None:
            return company.latest
        for statements in company.statements:
            if statements.fiscal_year == fiscal_year:
                return statements
        raise FinancialRecordNotFoundError(
            f"financial statements not found for {identifier}, fiscal year {fiscal_year}"
        )

    def balance_sheet(
        self,
        identifier: str,
        *,
        fiscal_year: int | None = None,
    ) -> BalanceSheet:
        return self.statements(identifier, fiscal_year=fiscal_year).balance

    def income_statement(
        self,
        identifier: str,
        *,
        fiscal_year: int | None = None,
    ) -> IncomeStatement:
        return self.statements(identifier, fiscal_year=fiscal_year).income

    def cash_flow(
        self,
        identifier: str,
        *,
        fiscal_year: int | None = None,
    ) -> CashFlowStatement:
        return self.statements(identifier, fiscal_year=fiscal_year).cash_flow

    def revenue_history(
        self,
        identifier: str,
        *,
        years: int = 10,
    ) -> tuple[FinancialValue, ...]:
        if years < 1:
            raise ValueError("years must be at least 1")
        history = (
            item.income.revenue
            for item in self.resolve_company(identifier).statements
        )
        return tuple(value for value in history if value is not None)[:years]

    def free_cash_flow(
        self,
        identifier: str,
        *,
        fiscal_year: int | None = None,
    ) -> FinancialValue | None:
        return self.cash_flow(identifier, fiscal_year=fiscal_year).free_cash_flow

    def normalize(
        self,
        identifier: str,
        *,
        fiscal_year: int | None = None,
    ):
        """Return an immutable normalized financial snapshot."""

        from .financial_normalizer import FinancialNormalizer

        return FinancialNormalizer(self).normalize(
            identifier,
            fiscal_year=fiscal_year,
        )

    def net_margin(
        self,
        identifier: str,
        *,
        fiscal_year: int | None = None,
    ) -> Decimal | None:
        income = self.income_statement(identifier, fiscal_year=fiscal_year)
        return _safe_ratio(income.net_income, income.revenue)

    def roe(
        self,
        identifier: str,
        *,
        fiscal_year: int | None = None,
    ) -> Decimal | None:
        current = self.statements(identifier, fiscal_year=fiscal_year)
        net_income = current.income.net_income
        current_equity = current.balance.shareholders_equity
        if net_income is None or current_equity is None:
            return None

        prior_equity = self._prior_equity(identifier, current.fiscal_year)
        denominator = current_equity.value
        if prior_equity is not None:
            denominator = (current_equity.value + prior_equity.value) / Decimal("2")
        if denominator == 0:
            return None
        return net_income.value / denominator

    def _prior_equity(self, identifier: str, fiscal_year: int) -> FinancialValue | None:
        company = self.resolve_company(identifier)
        older = [item for item in company.statements if item.fiscal_year < fiscal_year]
        if not older:
            return None
        return older[0].balance.shareholders_equity

    def _index_identifier(self, identifier: str, company: FinancialCompany) -> None:
        key = _normalize_identifier(identifier)
        existing = self._identifier_index.get(key)
        if existing is not None and existing.identifier != company.identifier:
            raise FinancialRepositoryIntegrityError(
                f"ambiguous financial identifier: {identifier}"
            )
        self._identifier_index[key] = company

    @staticmethod
    def _normalize_company(company: FinancialCompany) -> FinancialCompany:
        identifier = company.identifier.strip()
        if not identifier:
            raise FinancialRepositoryIntegrityError("financial company identifier is empty")
        if not company.statements:
            raise FinancialRepositoryIntegrityError(
                f"company has no statements: {identifier}"
            )

        ordered = tuple(
            sorted(company.statements, key=lambda item: item.fiscal_year, reverse=True)
        )
        years = [item.fiscal_year for item in ordered]
        if len(years) != len(set(years)):
            raise FinancialRepositoryIntegrityError(
                f"duplicate fiscal years for {identifier}"
            )
        if any(item.cik != company.cik for item in ordered):
            raise FinancialRepositoryIntegrityError(
                f"statement CIK mismatch for {identifier}"
            )
        return FinancialCompany(
            identifier=identifier,
            cik=company.cik,
            entity_name=company.entity_name,
            statements=ordered,
        )


def _safe_ratio(
    numerator: FinancialValue | None,
    denominator: FinancialValue | None,
) -> Decimal | None:
    if numerator is None or denominator is None or denominator.value == 0:
        return None
    if numerator.unit != denominator.unit:
        return None
    return numerator.value / denominator.value


def _annual_fiscal_years(
    company_facts: object,
    *,
    fiscal_period: str,
    filed_on_or_before: date | None,
) -> tuple[int, ...]:
    payload = _as_payload(company_facts)
    facts = payload.get("facts")
    if not isinstance(facts, Mapping):
        raise FinancialRepositoryIntegrityError("Company Facts payload has no facts object")

    annual_forms = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
    years: set[int] = set()
    for taxonomy_payload in facts.values():
        if not isinstance(taxonomy_payload, Mapping):
            continue
        for concept_payload in taxonomy_payload.values():
            if not isinstance(concept_payload, Mapping):
                continue
            units = concept_payload.get("units")
            if not isinstance(units, Mapping):
                continue
            for observations in units.values():
                if not isinstance(observations, Sequence) or isinstance(
                    observations, (str, bytes)
                ):
                    continue
                for observation in observations:
                    if not isinstance(observation, Mapping):
                        continue
                    if str(observation.get("form") or "").upper() not in annual_forms:
                        continue
                    if str(observation.get("fp") or "").upper() != fiscal_period.upper():
                        continue
                    filed = _parse_date(observation.get("filed"))
                    if filed is None or (
                        filed_on_or_before is not None and filed > filed_on_or_before
                    ):
                        continue
                    try:
                        years.add(int(observation["fy"]))
                    except (KeyError, TypeError, ValueError):
                        continue
    return tuple(sorted(years, reverse=True))


def _as_payload(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    raw = getattr(value, "raw", None)
    if isinstance(raw, Mapping):
        return raw
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, Mapping):
            return payload
    raise FinancialRepositoryIntegrityError(
        "company_facts must be a mapping or expose raw/to_dict"
    )


def _normalize_identifier(identifier: str) -> str:
    value = identifier.strip().upper()
    if not value:
        raise FinancialRecordNotFoundError("financial company identifier is empty")
    digits = "".join(character for character in value if character.isdigit())
    if value.isdigit() and digits:
        return digits.zfill(10)
    return value


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None
