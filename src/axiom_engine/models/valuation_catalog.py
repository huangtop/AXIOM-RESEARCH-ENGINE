from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator, model_validator

from .universe import UniverseModel


class LifecycleStage(StrEnum):
    PRE_REVENUE = "pre_revenue"
    EARLY_GROWTH = "early_growth"
    HIGH_GROWTH = "high_growth"
    MATURE = "mature"
    DECLINING = "declining"
    CYCLICAL = "cyclical"


class ProfitabilityState(StrEnum):
    PRE_PROFIT = "pre_profit"
    LOSS_MAKING = "loss_making"
    BREAK_EVEN = "break_even"
    PROFITABLE = "profitable"
    HIGHLY_PROFITABLE = "highly_profitable"


class LegacyCalcType(StrEnum):
    PE = "pe"
    PS = "ps"
    PB = "pb"
    EV = "ev"
    PEG = "peg"
    DCF = "dcf"
    SOTP = "sotp"
    MILESTONE = "milestone"


class ValuationModelPolicy(UniverseModel):
    model_type: str = Field(min_length=1)
    applicability: str = Field(pattern=r"^(primary|secondary|optional|disabled)$")
    priority: int = Field(ge=1)
    legacy_calc_type: LegacyCalcType | None = None
    default_assumptions: dict[str, float | int | str | bool] = Field(default_factory=dict)
    warning_rules: list[str] = Field(default_factory=list)


class ConfidencePolicy(UniverseModel):
    base_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    maximum_confidence: float = Field(default=0.95, ge=0.0, le=1.0)
    minimum_confidence: float = Field(default=0.1, ge=0.0, le=1.0)
    penalties: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_bounds(self) -> "ConfidencePolicy":
        if not self.minimum_confidence <= self.base_confidence <= self.maximum_confidence:
            raise ValueError("confidence bounds must satisfy minimum <= base <= maximum")
        if any(value < 0 for value in self.penalties.values()):
            raise ValueError("confidence penalties cannot be negative")
        return self


class ValuationProfileCatalogEntry(UniverseModel):
    profile_id: str = Field(pattern=r"^valuation_profile:")
    name: str = Field(min_length=1)
    description_zh_tw: str = Field(min_length=1)
    business_model_ids: list[str] = Field(default_factory=list)
    lifecycle_stages: list[LifecycleStage] = Field(min_length=1)
    profitability_states: list[ProfitabilityState] = Field(min_length=1)
    classification_rules: dict[str, list[str]] = Field(default_factory=dict)
    model_policy: list[ValuationModelPolicy] = Field(min_length=1)
    confidence_policy: ConfidencePolicy = Field(default_factory=ConfidencePolicy)
    catalog_version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("business_model_ids")
    @classmethod
    def validate_business_model_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("business_model_ids must be unique")
        for item in value:
            if not item.startswith("business_model:"):
                raise ValueError("business_model_ids must use business_model: namespace")
        return value

    @model_validator(mode="after")
    def validate_model_policy(self) -> "ValuationProfileCatalogEntry":
        model_types = [item.model_type for item in self.model_policy]
        priorities = [item.priority for item in self.model_policy]
        if len(model_types) != len(set(model_types)):
            raise ValueError("model_policy cannot repeat model_type")
        if len(priorities) != len(set(priorities)):
            raise ValueError("model_policy priorities must be unique")
        if not any(item.applicability == "primary" for item in self.model_policy):
            raise ValueError("an active valuation profile requires at least one primary model")
        return self
