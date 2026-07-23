from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ValuationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ModelResult(ValuationModel):
    model_name: Literal["discounted_cash_flow", "forward_earnings_multiple"]
    status: Literal["completed", "unavailable"]
    fair_value_per_share: Decimal | None = None
    currency: str | None = None
    inputs: dict[str, Decimal | int | str] = Field(default_factory=dict)
    source_record_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_result(self) -> "ModelResult":
        if self.status == "completed" and self.fair_value_per_share is None:
            raise ValueError("completed model requires fair_value_per_share")
        if self.status == "unavailable" and self.fair_value_per_share is not None:
            raise ValueError("unavailable model must not define fair_value_per_share")
        return self


class CompanyValuationResult(ValuationModel):
    valuation_result_id: str = Field(pattern=r"^canonical_valuation_result:")
    company_id: str = Field(pattern=r"^company:")
    as_of_date: date
    currency: str
    status: Literal["completed", "partial", "unavailable"]
    models: list[ModelResult]
    blended_fair_value_per_share: Decimal | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    engine_version: str = "1.0.0"

    @model_validator(mode="after")
    def validate_status(self) -> "CompanyValuationResult":
        completed = [item for item in self.models if item.status == "completed"]
        if self.status == "completed" and len(completed) != len(self.models):
            raise ValueError("completed company result requires all models")
        if self.status == "partial" and not completed:
            raise ValueError("partial company result requires at least one completed model")
        if self.status == "unavailable" and completed:
            raise ValueError("unavailable company result cannot contain completed models")
        if completed and self.blended_fair_value_per_share is None:
            raise ValueError("completed models require blended fair value")
        return self


class ReadinessItem(ValuationModel):
    company_id: str
    ready_models: list[str]
    missing_inputs: dict[str, list[str]]
    ready: bool


class ReadinessReport(ValuationModel):
    companies_checked: int
    companies_ready: int
    companies_partial: int
    companies_unavailable: int
    required_company_count: int
    acceptance_passed: bool
    items: list[ReadinessItem]


class BatchValuationReport(ValuationModel):
    as_of_date: date
    companies_requested: int
    completed: int
    partial: int
    unavailable: int
    output_directory: str
    written_files: list[str] = Field(default_factory=list)
