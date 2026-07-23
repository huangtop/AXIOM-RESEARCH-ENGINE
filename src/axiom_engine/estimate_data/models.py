from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class EstimateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

class EstimateProvenance(EstimateModel):
    provenance_id: str = Field(pattern=r"^provenance:")
    provider_id: str = Field(pattern=r"^provider:")
    source_type: Literal["licensed_vendor", "company_guidance", "analyst_consensus", "manual_fixture"]
    source_name: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    retrieved_at: str = Field(min_length=10)
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class AnalystEstimate(EstimateModel):
    estimate_id: str = Field(pattern=r"^estimate:")
    company_id: str = Field(pattern=r"^company:")
    metric: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    value: Decimal
    unit: str = Field(min_length=1)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    period_end: date
    fiscal_year: int = Field(ge=1900, le=2200)
    fiscal_period: Literal["FY", "Q1", "Q2", "Q3", "Q4"]
    estimate_kind: Literal["consensus_mean", "consensus_median", "high", "low", "company_guidance"]
    analyst_count: int | None = Field(default=None, ge=1)
    provenance_ids: list[str] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @field_validator("provenance_ids")
    @classmethod
    def validate_provenance_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)): raise ValueError("provenance_ids must be unique")
        if any(not x.startswith("provenance:") for x in values): raise ValueError("provenance_ids must use provenance: namespace")
        return values

    @model_validator(mode="after")
    def validate_unit(self) -> "AnalystEstimate":
        if self.unit == "currency" and not self.currency: raise ValueError("currency unit requires currency code")
        if self.unit != "currency" and self.currency: raise ValueError("currency is only valid when unit=currency")
        return self

class ForwardAssumption(EstimateModel):
    assumption_id: str = Field(pattern=r"^forward_assumption:")
    company_id: str = Field(pattern=r"^company:")
    metric: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    value: Decimal
    unit: str = Field(min_length=1)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    effective_date: date
    horizon_years: int = Field(ge=1, le=20)
    assumption_type: Literal["provider_consensus", "company_guidance", "research_assumption", "scenario_input"]
    status: Literal["proposed", "approved", "superseded"] = "proposed"
    provenance_ids: list[str] = Field(min_length=1)
    rationale: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @model_validator(mode="after")
    def validate_unit(self) -> "ForwardAssumption":
        if self.unit == "currency" and not self.currency: raise ValueError("currency unit requires currency code")
        if self.unit != "currency" and self.currency: raise ValueError("currency is only valid when unit=currency")
        if len(self.provenance_ids) != len(set(self.provenance_ids)): raise ValueError("provenance_ids must be unique")
        return self

class EstimateDataSource(EstimateModel):
    schema_version: str = "1.0.0"
    provider_id: str = Field(pattern=r"^provider:")
    provider_name: str = Field(min_length=1)
    as_of_date: date
    provenance: list[EstimateProvenance] = Field(min_length=1)
    estimates: list[AnalystEstimate] = Field(default_factory=list)
    forward_assumptions: list[ForwardAssumption] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "EstimateDataSource":
        if not self.estimates and not self.forward_assumptions: raise ValueError("at least one estimate or forward assumption is required")
        prov=[x.provenance_id for x in self.provenance]
        if len(prov)!=len(set(prov)): raise ValueError("duplicate provenance_id")
        ids=[x.estimate_id for x in self.estimates]+[x.assumption_id for x in self.forward_assumptions]
        if len(ids)!=len(set(ids)): raise ValueError("duplicate estimate or assumption id")
        pset=set(prov)
        for item in self.provenance:
            if item.provider_id != self.provider_id: raise ValueError(f"provenance {item.provenance_id} provider mismatch")
        for item in [*self.estimates,*self.forward_assumptions]:
            missing=set(item.provenance_ids)-pset
            if missing: raise ValueError(f"{ids[0]} has missing provenance: {sorted(missing)}")
        return self

class EstimateImportReport(EstimateModel):
    schema_version: str = "1.0.0"
    provider_id: str
    as_of_date: date
    dry_run: bool
    estimates_found: int
    assumptions_found: int
    companies_found: int
    provenance_records: int
    output_directory: str
    written_files: list[str] = Field(default_factory=list)
