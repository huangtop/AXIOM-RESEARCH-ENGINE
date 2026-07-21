from __future__ import annotations
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from pydantic import Field, model_validator
from .core import StrictModel


class DriverKind(StrEnum):
    structural = "structural"
    cyclical = "cyclical"


class DriverStatus(StrEnum):
    active = "active"
    monitoring = "monitoring"
    invalidated = "invalidated"
    archived = "archived"


class ResearchDriver(StrictModel):
    driver_id: str
    company_id: str
    name: str
    name_zh_tw: str
    driver_kind: DriverKind
    status: DriverStatus = DriverStatus.monitoring
    description_zh_tw: str
    entity_ids: list[str] = Field(default_factory=list)
    affected_periods: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    materiality: str
    evidence_ids: list[str] = Field(default_factory=list)


class CatalystStatus(StrEnum):
    expected = "expected"
    on_track = "on_track"
    delayed = "delayed"
    achieved = "achieved"
    missed = "missed"
    cancelled = "cancelled"


class Catalyst(StrictModel):
    catalyst_id: str
    company_id: str
    name: str
    name_zh_tw: str
    catalyst_type: str
    status: CatalystStatus
    subject_entity_ids: list[str]
    driver_ids: list[str]
    expected_date: date | None = None
    affected_periods: list[str] = Field(default_factory=list)
    market_materiality: str
    expectation_state: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)


class ImpactDirection(StrEnum):
    increase = "increase"
    decrease = "decrease"
    neutral = "neutral"
    uncertain = "uncertain"


class DriverImpact(StrictModel):
    impact_id: str
    company_id: str
    driver_id: str
    catalyst_id: str | None = None
    target_type: str
    target_ref_id: str
    metric: str
    fiscal_period: str
    direction: ImpactDirection
    effect_type: str
    low: float | None = None
    base: float | None = None
    high: float | None = None
    unit: str | None = None
    confidence: float = Field(ge=0, le=1)
    rationale_zh_tw: str
    evidence_ids: list[str] = Field(default_factory=list)


class ThesisStatus(StrEnum):
    active = "active"
    challenged = "challenged"
    invalidated = "invalidated"
    archived = "archived"


class InvestmentThesis(StrictModel):
    thesis_id: str
    company_id: str
    title: str
    title_zh_tw: str
    summary_zh_tw: str
    status: ThesisStatus
    driver_ids: list[str]
    catalyst_ids: list[str] = Field(default_factory=list)
    risk_driver_ids: list[str] = Field(default_factory=list)
    affected_periods: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class ResearchSnapshot(StrictModel):
    research_snapshot_id: str
    company_id: str
    research_period: str
    revision: int = Field(ge=1)
    as_of_date: date
    thesis_ids: list[str]
    driver_ids: list[str]
    catalyst_ids: list[str]
    estimate_ids: list[str] = Field(default_factory=list)
    summary_zh_tw: str
    created_at: datetime


class ResearchRevision(StrictModel):
    research_revision_id: str
    company_id: str
    research_period: str
    revision: int = Field(ge=1)
    previous_snapshot_id: str | None = None
    snapshot_id: str
    changed_at: datetime
    changed_by: str
    change_summary_zh_tw: str
    changed_refs: list[str] = Field(default_factory=list)


class AdmissionStatus(StrEnum):
    accepted = "accepted"
    watchlist = "watchlist"
    rejected = "rejected"
    pending = "pending"


class RawArticle(StrictModel):
    raw_article_id: str
    source_id: str
    canonical_url: str
    title: str
    published_at: datetime | None = None
    fetched_at: datetime
    content_hash: str
    raw_payload_ref: str | None = None
    ingestion_status: str = "fetched"


class EntityMention(StrictModel):
    mention_id: str
    raw_article_id: str
    mention_text: str
    resolved_entity_id: str | None = None
    entity_type_hint: str | None = None
    confidence: float = Field(ge=0, le=1)
    evidence_span: str | None = None


class ExtractedClaim(StrictModel):
    claim_id: str
    raw_article_id: str
    subject_entity_id: str | None = None
    predicate: str
    object_value: Any
    evidence_span: str
    confidence: float = Field(ge=0, le=1)


class ArticleAdmission(StrictModel):
    admission_id: str
    raw_article_id: str
    status: AdmissionStatus
    entity_confidence: float = Field(ge=0, le=1)
    event_confidence: float = Field(ge=0, le=1)
    source_quality: float = Field(ge=0, le=1)
    research_relevance: float = Field(ge=0, le=1)
    financial_materiality: float = Field(ge=0, le=1)
    novelty_score: float = Field(ge=0, le=1)
    market_expectation_delta: float = Field(ge=-1, le=1)
    reasons: list[str] = Field(default_factory=list)
    rejected_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def rejected_has_reason(self):
        if self.status == AdmissionStatus.rejected and not self.rejected_reasons:
            raise ValueError("rejected admission must include rejected_reasons")
        return self
