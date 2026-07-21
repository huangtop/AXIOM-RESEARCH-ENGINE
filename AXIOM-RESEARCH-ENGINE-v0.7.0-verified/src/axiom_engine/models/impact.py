from __future__ import annotations

from datetime import date
from enum import StrEnum
from pydantic import Field, model_validator
from .core import StrictModel


class ShockDirection(StrEnum):
    positive = "positive"
    negative = "negative"


class PropagationMode(StrEnum):
    linear = "linear"
    blocked = "blocked"


class Shock(StrictModel):
    shock_id: str
    entity_id: str
    name: str
    direction: ShockDirection
    magnitude: float = Field(gt=0, le=1)
    unit: str = "fraction"
    start_date: date
    duration_months: int | None = Field(default=None, ge=0)
    confidence: float = Field(ge=0, le=1)
    notes_zh_tw: str = ""

    @property
    def signed_magnitude(self) -> float:
        return self.magnitude if self.direction == ShockDirection.positive else -self.magnitude


class PropagationRule(StrictModel):
    rule_id: str
    edge_id: str
    elasticity: float = Field(default=1.0, ge=0, le=2)
    attenuation: float = Field(default=1.0, ge=0, le=1)
    propagation_mode: PropagationMode = PropagationMode.linear
    max_hops: int = Field(default=6, ge=1, le=12)
    notes_zh_tw: str = ""


class ImpactNode(StrictModel):
    entity_id: str
    impact: float = Field(ge=-1, le=1)
    confidence: float = Field(ge=0, le=1)
    lag_months: int = Field(ge=0)
    path: list[str]
    edge_ids: list[str]

    @model_validator(mode="after")
    def path_has_target(self):
        if not self.path or self.path[-1] != self.entity_id:
            raise ValueError("impact path must terminate at entity_id")
        return self


class CompanyImpactSnapshot(StrictModel):
    snapshot_id: str
    shock_id: str
    company_id: str
    as_of_date: date
    estimated_revenue_impact: float = Field(ge=-1, le=1)
    estimated_eps_impact: float = Field(ge=-1, le=1)
    estimated_fair_value_impact: float = Field(ge=-1, le=1)
    confidence: float = Field(ge=0, le=1)
    source_paths: list[list[str]] = Field(default_factory=list)


class ETFImpactSnapshot(StrictModel):
    snapshot_id: str
    shock_id: str
    etf_id: str
    as_of_date: date
    estimated_fair_value_impact: float = Field(ge=-1, le=1)
    impact_coverage: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    contributors: list[dict] = Field(default_factory=list)


class ImpactScenario(StrictModel):
    scenario_id: str
    name: str
    shock_ids: list[str]
    aggregation_method: str = "additive_capped"
    notes_zh_tw: str = ""
