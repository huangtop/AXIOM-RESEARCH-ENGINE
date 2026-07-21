from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class EntityType(StrEnum):
    company = "company"
    organization = "organization"
    product = "product"
    technology = "technology"
    theme = "theme"
    category = "category"
    etf = "etf"
    event = "event"


class Entity(StrictModel):
    entity_id: str
    entity_type: EntityType
    name: str
    name_zh_tw: str | None = None
    aliases: list[str] = Field(default_factory=list)
    country: str | None = None
    active: bool = True


class Security(StrictModel):
    security_id: str
    company_id: str
    ticker: str
    exchange: str
    currency: str
    security_type: str = "common_stock"
    share_class: str | None = None
    provider_symbols: dict[str, str] = Field(default_factory=dict)
    active: bool = True


class SourceTier(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class Source(StrictModel):
    source_id: str
    title: str
    publisher: str
    source_type: str
    credibility_tier: SourceTier
    published_at: date | None = None
    accessed_at: date | None = None
    url: HttpUrl | None = None
    is_primary: bool = False
    source_family: str | None = None


class Evidence(StrictModel):
    evidence_id: str
    source_ids: list[str]
    summary_zh_tw: str
    supports: bool = True
    confidence: float = Field(ge=0, le=1)
    as_of_date: date | None = None
    review_status: str = "approved"


class Relation(StrictModel):
    relation_id: str
    subject_id: str
    predicate: str
    object_id: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    effective_from: date | None = None
    effective_to: date | None = None
    scope_entity_id: str | None = None
    review_status: str = "approved"
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_dates(self) -> "Relation":
        if self.effective_from and self.effective_to:
            if self.effective_to < self.effective_from:
                raise ValueError("effective_to cannot precede effective_from")
        return self
