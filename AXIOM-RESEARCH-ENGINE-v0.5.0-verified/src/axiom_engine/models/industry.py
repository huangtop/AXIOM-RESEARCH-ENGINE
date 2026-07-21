from __future__ import annotations
from enum import StrEnum
from pydantic import Field, model_validator
from .core import StrictModel


class IndustryEdgeType(StrEnum):
    supplies = "supplies"
    manufactures = "manufactures"
    packages = "packages"
    depends_on = "depends_on"
    enables = "enables"
    competes_with = "competes_with"
    substitutes = "substitutes"
    adopts = "adopts"
    exposed_to = "exposed_to"


class IndustryEdge(StrictModel):
    edge_id: str
    source_entity_id: str
    target_entity_id: str
    edge_type: IndustryEdgeType
    description_zh_tw: str
    directionality: str = "directed"
    strength: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    lead_lag_months: int | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    active: bool = True

    @model_validator(mode="after")
    def no_self_edge(self):
        if self.source_entity_id == self.target_entity_id:
            raise ValueError("industry edge cannot be a self-edge")
        return self


class IndustryExposure(StrictModel):
    exposure_id: str
    company_id: str
    entity_id: str
    exposure_type: str
    direction: str
    materiality: str
    weight: float | None = Field(default=None, ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    rationale_zh_tw: str
    driver_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class IndustryGraphSnapshot(StrictModel):
    graph_snapshot_id: str
    as_of_date: str
    edge_ids: list[str]
    exposure_ids: list[str]
    notes_zh_tw: str = ""
