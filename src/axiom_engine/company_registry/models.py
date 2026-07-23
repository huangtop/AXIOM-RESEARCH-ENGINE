from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class DataProvenance(RegistryModel):
    provenance_id: str = Field(pattern=r"^provenance:")
    source_type: Literal["official_exchange", "regulator", "licensed_vendor", "company_disclosure"]
    source_name: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    retrieved_at: str = Field(min_length=10)
    source_url: str | None = None
    license_note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompanyRegistryRecord(RegistryModel):
    company_id: str = Field(pattern=r"^company:")
    legal_name: str = Field(min_length=1)
    display_name: str | None = None
    country: str = Field(min_length=2, max_length=2)
    website: str | None = None
    official_sector: str | None = None
    official_industry: str | None = None
    business_description: str | None = None
    provenance_ids: list[str] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        return value.upper()

    @field_validator("provenance_ids")
    @classmethod
    def validate_provenance_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("provenance_ids must be unique")
        if any(not value.startswith("provenance:") for value in values):
            raise ValueError("provenance_ids must use provenance: namespace")
        return values


class SecurityRegistryRecord(RegistryModel):
    security_id: str = Field(pattern=r"^security:")
    company_id: str = Field(pattern=r"^company:")
    exchange: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)
    security_type: str = "common_stock"
    primary_listing: bool = False
    isin: str | None = None
    figi: str | None = None
    provenance_ids: list[str] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("exchange", "ticker", "currency")
    @classmethod
    def normalize_codes(cls, value: str) -> str:
        return value.upper()


class CompanyUniverseSource(RegistryModel):
    schema_version: str = "1.0.0"
    as_of_date: date
    source_name: str = Field(min_length=1)
    provenance: list[DataProvenance] = Field(min_length=1)
    companies: list[CompanyRegistryRecord]
    securities: list[SecurityRegistryRecord]

    @model_validator(mode="after")
    def validate_references(self) -> "CompanyUniverseSource":
        provenance_ids = [item.provenance_id for item in self.provenance]
        if len(provenance_ids) != len(set(provenance_ids)):
            raise ValueError("duplicate provenance_id")
        company_ids = [item.company_id for item in self.companies]
        if len(company_ids) != len(set(company_ids)):
            raise ValueError("duplicate company_id")
        security_ids = [item.security_id for item in self.securities]
        if len(security_ids) != len(set(security_ids)):
            raise ValueError("duplicate security_id")
        provenance_set = set(provenance_ids)
        company_set = set(company_ids)
        for company in self.companies:
            missing = set(company.provenance_ids) - provenance_set
            if missing:
                raise ValueError(f"company {company.company_id} has missing provenance: {sorted(missing)}")
        for security in self.securities:
            if security.company_id not in company_set:
                raise ValueError(f"security {security.security_id} references missing company")
            missing = set(security.provenance_ids) - provenance_set
            if missing:
                raise ValueError(f"security {security.security_id} has missing provenance: {sorted(missing)}")
        return self


class RegistryImportReport(RegistryModel):
    schema_version: str = "1.0.0"
    source_name: str
    as_of_date: date
    dry_run: bool
    companies_found: int
    securities_found: int
    companies_with_official_sector: int
    companies_with_official_industry: int
    companies_with_business_description: int
    provenance_records: int
    output_directory: str
    written_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
