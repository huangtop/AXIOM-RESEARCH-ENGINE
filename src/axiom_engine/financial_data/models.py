from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FinancialModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class FinancialProvenance(FinancialModel):
    provenance_id: str = Field(pattern=r"^provenance:")
    provider_id: str = Field(pattern=r"^provider:")
    source_type: Literal["regulator_filing", "company_filing", "licensed_vendor", "manual_fixture"]
    source_name: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    retrieved_at: str = Field(min_length=10)
    source_url: str | None = None
    filing_date: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FinancialFact(FinancialModel):
    financial_fact_id: str = Field(pattern=r"^financial_fact:")
    company_id: str = Field(pattern=r"^company:")
    metric: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    value: Decimal
    unit: str = Field(min_length=1)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    period_type: Literal["instant", "duration"]
    period_start: date | None = None
    period_end: date
    fiscal_year: int = Field(ge=1900, le=2200)
    fiscal_period: Literal["FY", "Q1", "Q2", "Q3", "Q4", "TTM"]
    statement: Literal["income_statement", "balance_sheet", "cash_flow", "operating_metric"]
    form_type: str | None = None
    accession_number: str | None = None
    audited: bool | None = None
    provenance_ids: list[str] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @field_validator("provenance_ids")
    @classmethod
    def validate_provenance_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("provenance_ids must be unique")
        if any(not value.startswith("provenance:") for value in values):
            raise ValueError("provenance_ids must use provenance: namespace")
        return values

    @model_validator(mode="after")
    def validate_period(self) -> "FinancialFact":
        if self.period_type == "duration" and self.period_start is None:
            raise ValueError("duration facts require period_start")
        if self.period_type == "instant" and self.period_start is not None:
            raise ValueError("instant facts must not define period_start")
        if self.period_start and self.period_start > self.period_end:
            raise ValueError("period_start must not be after period_end")
        if self.unit == "currency" and not self.currency:
            raise ValueError("currency unit requires currency code")
        if self.unit != "currency" and self.currency:
            raise ValueError("currency is only valid when unit=currency")
        return self


class FinancialDataSource(FinancialModel):
    schema_version: str = "1.0.0"
    provider_id: str = Field(pattern=r"^provider:")
    provider_name: str = Field(min_length=1)
    as_of_date: date
    provenance: list[FinancialProvenance] = Field(min_length=1)
    facts: list[FinancialFact] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> "FinancialDataSource":
        provenance_ids = [x.provenance_id for x in self.provenance]
        fact_ids = [x.financial_fact_id for x in self.facts]
        if len(provenance_ids) != len(set(provenance_ids)):
            raise ValueError("duplicate provenance_id")
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("duplicate financial_fact_id")
        provenance_set = set(provenance_ids)
        for item in self.provenance:
            if item.provider_id != self.provider_id:
                raise ValueError(f"provenance {item.provenance_id} provider mismatch")
        for fact in self.facts:
            missing = set(fact.provenance_ids) - provenance_set
            if missing:
                raise ValueError(f"fact {fact.financial_fact_id} has missing provenance: {sorted(missing)}")
        return self


class FinancialImportReport(FinancialModel):
    schema_version: str = "1.0.0"
    provider_id: str
    as_of_date: date
    dry_run: bool
    facts_found: int
    companies_found: int
    metrics_found: int
    provenance_records: int
    output_directory: str
    written_files: list[str] = Field(default_factory=list)
