from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from .core import StrictModel


class PeriodType(StrEnum):
    instant = "instant"
    quarter = "quarter"
    annual = "annual"
    trailing_twelve_months = "trailing_twelve_months"
    forward = "forward"


class FactQuality(StrEnum):
    reported = "reported"
    normalized = "normalized"
    derived = "derived"
    user_provided = "user_provided"


class FinancialFact(StrictModel):
    fact_id: str
    company_id: str
    security_id: str | None = None
    metric: str
    value: float
    unit: str
    period_type: PeriodType
    period_start: date | None = None
    period_end: date
    fiscal_year: int | None = None
    fiscal_quarter: int | None = Field(default=None, ge=1, le=4)
    quality: FactQuality
    source_ids: list[str] = Field(default_factory=list)
    formula_version: str | None = None
    input_fact_ids: list[str] = Field(default_factory=list)


class EstimateType(StrEnum):
    consensus = "consensus"
    internal_model = "internal_model"
    manual = "manual"


class Estimate(StrictModel):
    estimate_id: str
    company_id: str
    security_id: str | None = None
    metric: str
    value: float
    unit: str
    fiscal_period: str
    estimate_type: EstimateType
    scenario: str
    as_of_date: date
    source_ids: list[str] = Field(default_factory=list)
    supported_by_driver_ids: list[str] = Field(default_factory=list)
    supported_by_catalyst_ids: list[str] = Field(default_factory=list)
    notes: str | None = None


class ModelApplicability(StrEnum):
    primary = "primary"
    secondary = "secondary"
    optional = "optional"
    disabled = "disabled"


class ValuationModelConfig(StrictModel):
    model_type: str
    applicability: ModelApplicability
    priority: int = Field(ge=1)
    enabled: bool = True
    reason_zh_tw: str
    parameter_keys: list[str] = Field(default_factory=list)
    required_metrics: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ValuationProfile(StrictModel):
    profile_id: str
    name: str
    description_zh_tw: str
    parent_profile_id: str | None = None
    business_characteristics: list[str] = Field(default_factory=list)
    models: list[ValuationModelConfig]


class CompanyValuationProfile(StrictModel):
    company_id: str
    profile_ids: list[str]
    model_overrides: list[ValuationModelConfig] = Field(default_factory=list)
    selected_by: str = "human"
    effective_from: date
    effective_to: date | None = None
    rationale_zh_tw: str


class ScenarioType(StrEnum):
    bear = "bear"
    base = "base"
    bull = "bull"
    custom = "custom"


class ValuationScenario(StrictModel):
    scenario_id: str
    company_id: str
    research_period: str
    revision: int = Field(ge=1)
    name: str
    scenario_type: ScenarioType
    as_of_date: date
    description_zh_tw: str | None = None


class AssumptionValueType(StrEnum):
    absolute = "absolute"
    multiple = "multiple"
    rate = "rate"


class ValuationAssumption(StrictModel):
    assumption_id: str
    scenario_id: str
    key: str
    value: float
    value_type: AssumptionValueType
    unit: str
    source_type: str
    source_ref_ids: list[str] = Field(default_factory=list)
    rationale_zh_tw: str | None = None


class ExecutionStatus(StrEnum):
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class ValuationExecution(StrictModel):
    execution_id: str
    valuation_snapshot_id: str
    company_id: str
    security_id: str
    scenario_id: str
    model_type: str
    model_version: str
    input_refs: list[str]
    input_hash: str
    started_at: datetime
    completed_at: datetime
    status: ExecutionStatus
    created_snapshot: bool
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_timing(self) -> "ValuationExecution":
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        return self


class ValuationSnapshot(StrictModel):
    valuation_snapshot_id: str
    company_id: str
    security_id: str
    scenario_id: str
    research_period: str
    revision: int
    model_type: str
    model_version: str
    input_hash: str
    input_refs: list[str]
    as_of_date: date
    currency: str
    fair_value_per_share: float
    market_price: float
    upside: float
    model_inputs: dict[str, float] = Field(default_factory=dict)
    model_outputs: dict[str, float] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0, le=1)


class ValuationBookEntry(StrictModel):
    model_type: str
    applicability: ModelApplicability
    priority: int
    snapshot_id: str | None = None
    status: str
    fair_value_per_share: float | None = None
    upside: float | None = None
    confidence: float | None = None
    reason_zh_tw: str
    warnings: list[str] = Field(default_factory=list)


class ValuationBook(StrictModel):
    valuation_book_id: str
    company_id: str
    security_id: str
    scenario_id: str
    as_of_date: date
    profile_ids: list[str]
    entries: list[ValuationBookEntry]
    blended_fair_value: float | None = None
    blended_upside: float | None = None
