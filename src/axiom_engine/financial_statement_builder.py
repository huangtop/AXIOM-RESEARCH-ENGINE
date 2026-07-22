from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .financial_concept_registry import FinancialConceptRegistry, StatementKind
from .financial_statement_models import (
    BalanceSheet,
    CashFlowStatement,
    FinancialStatements,
    FinancialValue,
    IncomeStatement,
)


class FinancialStatementBuildError(ValueError):
    pass


_ANNUAL_FORMS = frozenset({"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"})


class FinancialStatementBuilder:
    def __init__(self, registry: FinancialConceptRegistry | None = None) -> None:
        self._registry = registry or FinancialConceptRegistry()

    def build(
        self,
        company_facts: object,
        *,
        fiscal_year: int | None = None,
        fiscal_period: str = "FY",
        filed_on_or_before: date | None = None,
    ) -> FinancialStatements:
        payload = _as_payload(company_facts)
        cik = _normalize_cik(payload.get("cik"))
        entity_name = str(payload.get("entityName") or payload.get("entity_name") or "").strip()
        if not entity_name:
            raise FinancialStatementBuildError("Company Facts payload has no entity name")
        facts = payload.get("facts")
        if not isinstance(facts, Mapping):
            raise FinancialStatementBuildError("Company Facts payload has no facts object")

        target_year = fiscal_year or self._latest_year(facts, fiscal_period, filed_on_or_before)
        if target_year is None:
            raise FinancialStatementBuildError(f"no {fiscal_period} observations found")

        selected: dict[str, FinancialValue | None] = {}
        for definition in self._registry.definitions:
            selected[definition.field_name] = self._resolve(
                facts,
                definition.aliases,
                definition.preferred_units,
                definition.instant,
                target_year,
                fiscal_period,
                filed_on_or_before,
            )

        operating_cash_flow = selected["operating_cash_flow"]
        capital_expenditure = selected["capital_expenditure"]
        return FinancialStatements(
            cik=cik,
            entity_name=entity_name,
            fiscal_year=target_year,
            fiscal_period=fiscal_period,
            income=IncomeStatement(**{
                item.field_name: selected[item.field_name]
                for item in self._registry.for_statement(StatementKind.INCOME)
            }),
            balance=BalanceSheet(**{
                item.field_name: selected[item.field_name]
                for item in self._registry.for_statement(StatementKind.BALANCE)
            }),
            cash_flow=CashFlowStatement(
                operating_cash_flow=operating_cash_flow,
                capital_expenditure=capital_expenditure,
                free_cash_flow=_derive_fcf(operating_cash_flow, capital_expenditure),
            ),
        )

    def _latest_year(
        self,
        facts: Mapping[str, Any],
        fiscal_period: str,
        filed_on_or_before: date | None,
    ) -> int | None:
        years: list[int] = []
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
                    if not isinstance(observations, Sequence):
                        continue
                    for observation in observations:
                        if not isinstance(observation, Mapping):
                            continue
                        if _eligible(observation, None, fiscal_period, filed_on_or_before):
                            year = _optional_int(observation.get("fy"))
                            if year is not None:
                                years.append(year)
        return max(years) if years else None

    def _resolve(
        self,
        facts: Mapping[str, Any],
        aliases: tuple[str, ...],
        preferred_units: tuple[str, ...],
        instant: bool,
        fiscal_year: int,
        fiscal_period: str,
        filed_on_or_before: date | None,
    ) -> FinancialValue | None:
        candidates: list[tuple[tuple[int, int, int, date], FinancialValue]] = []
        for taxonomy, taxonomy_payload in facts.items():
            if not isinstance(taxonomy_payload, Mapping):
                continue
            for alias_rank, alias in enumerate(aliases):
                concept_payload = taxonomy_payload.get(alias)
                if not isinstance(concept_payload, Mapping):
                    continue
                units = concept_payload.get("units")
                if not isinstance(units, Mapping):
                    continue
                ordered_units = list(preferred_units) + [u for u in units if u not in preferred_units]
                for unit_rank, unit in enumerate(ordered_units):
                    observations = units.get(unit)
                    if not isinstance(observations, Sequence):
                        continue
                    for observation in observations:
                        if not isinstance(observation, Mapping):
                            continue
                        if not _eligible(observation, fiscal_year, fiscal_period, filed_on_or_before):
                            continue
                        parsed = _parse_value(observation, str(taxonomy), alias, str(unit))
                        if parsed is None:
                            continue
                        candidates.append((
                            (-alias_rank, -unit_rank, _period_score(parsed, instant), parsed.filed),
                            parsed,
                        ))
        return max(candidates, key=lambda item: item[0])[1] if candidates else None


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
    raise FinancialStatementBuildError("company_facts must be a mapping or expose raw/to_dict")


def _normalize_cik(value: object) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if not digits or len(digits) > 10:
        raise FinancialStatementBuildError(f"invalid CIK: {value}")
    return digits.zfill(10)


def _eligible(
    observation: Mapping[str, Any],
    fiscal_year: int | None,
    fiscal_period: str,
    filed_on_or_before: date | None,
) -> bool:
    if str(observation.get("form") or "").upper() not in _ANNUAL_FORMS:
        return False
    if str(observation.get("fp") or "").upper() != fiscal_period.upper():
        return False
    if fiscal_year is not None and _optional_int(observation.get("fy")) != fiscal_year:
        return False
    filed = _parse_date(observation.get("filed"))
    return filed is not None and (filed_on_or_before is None or filed <= filed_on_or_before)


def _parse_value(
    observation: Mapping[str, Any], taxonomy: str, concept: str, unit: str
) -> FinancialValue | None:
    try:
        numeric = Decimal(str(observation["val"]))
    except (KeyError, InvalidOperation, ValueError):
        return None
    filed = _parse_date(observation.get("filed"))
    if filed is None:
        return None
    return FinancialValue(
        value=numeric,
        unit=unit,
        taxonomy=taxonomy,
        concept=concept,
        filed=filed,
        form=str(observation.get("form") or ""),
        fiscal_year=_optional_int(observation.get("fy")),
        fiscal_period=_optional_str(observation.get("fp")),
        start=_parse_date(observation.get("start")),
        end=_parse_date(observation.get("end")),
        frame=_optional_str(observation.get("frame")),
    )


def _period_score(value: FinancialValue, instant: bool) -> int:
    if instant:
        return 2 if value.end else 0
    if value.start is None or value.end is None:
        return 0
    return 2 if 330 <= (value.end - value.start).days <= 400 else 1


def _derive_fcf(
    operating_cash_flow: FinancialValue | None,
    capital_expenditure: FinancialValue | None,
) -> FinancialValue | None:
    if operating_cash_flow is None or capital_expenditure is None:
        return None
    if operating_cash_flow.unit != capital_expenditure.unit:
        return None
    return replace(
        operating_cash_flow,
        value=operating_cash_flow.value - abs(capital_expenditure.value),
        taxonomy="axiom",
        concept="FreeCashFlow",
        filed=max(operating_cash_flow.filed, capital_expenditure.filed),
    )


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_str(value: object) -> str | None:
    return str(value) if value not in (None, "") else None
