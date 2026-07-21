from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class UniverseModel(BaseModel):
    """Strict base model for market-universe records."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CompanyStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DELISTED = "delisted"
    ACQUIRED = "acquired"
    BANKRUPT = "bankrupt"


class SecurityStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DELISTED = "delisted"


class ResearchLevel(StrEnum):
    NONE = "none"
    BASIC = "basic"
    FOCUS = "focus"
    CORE = "core"


class ClassificationType(StrEnum):
    SECTOR = "sector"
    INDUSTRY = "industry"
    SUB_INDUSTRY = "sub_industry"
    THEME = "theme"
    TECHNOLOGY = "technology"
    BUSINESS_MODEL = "business_model"


class AssignmentMethod(StrEnum):
    MANUAL = "manual"
    RULE = "rule"
    IMPORTED = "imported"
    MODEL = "model"


class ClassificationNode(UniverseModel):
    classification_id: str = Field(min_length=3)
    classification_type: ClassificationType
    name: str = Field(min_length=1)
    name_zh_tw: str | None = None
    parent_id: str | None = None
    taxonomy_path: list[str] = Field(default_factory=list)
    description: str | None = None
    active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("classification_id")
    @classmethod
    def validate_classification_id(cls, value: str) -> str:
        if ":" not in value:
            raise ValueError("classification_id must be a stable namespaced ID")
        return value

    @model_validator(mode="after")
    def validate_path(self) -> "ClassificationNode":
        if self.taxonomy_path and self.taxonomy_path[-1] != self.classification_id:
            raise ValueError("taxonomy_path must end with classification_id")
        if self.parent_id == self.classification_id:
            raise ValueError("classification cannot be its own parent")
        return self


class CompanyClassificationAssignment(UniverseModel):
    assignment_id: str = Field(min_length=3)
    company_id: str = Field(pattern=r"^company:")
    classification_id: str = Field(min_length=3)
    is_primary: bool = False
    weight: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    method: AssignmentMethod = AssignmentMethod.MANUAL
    source_ids: list[str] = Field(default_factory=list)
    valid_from: str | None = None
    valid_to: str | None = None
    notes_zh_tw: str | None = None


class ValuationProfileAssignment(UniverseModel):
    assignment_id: str = Field(min_length=3)
    company_id: str = Field(pattern=r"^company:")
    profile_id: str = Field(pattern=r"^valuation_profile:")
    applicability: str = Field(default="primary")
    priority: int = Field(default=1, ge=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    method: AssignmentMethod = AssignmentMethod.MANUAL
    source_ids: list[str] = Field(default_factory=list)
    valid_from: str | None = None
    valid_to: str | None = None
    reason_zh_tw: str | None = None


class CompanyMaster(UniverseModel):
    company_id: str = Field(pattern=r"^company:")
    legal_name: str = Field(min_length=1)
    display_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    country: str = Field(min_length=2, max_length=2)
    status: CompanyStatus = CompanyStatus.ACTIVE
    primary_security_id: str | None = Field(default=None, pattern=r"^security:")
    research_level: ResearchLevel = ResearchLevel.NONE
    classification_ids: list[str] = Field(default_factory=list)
    valuation_profile_ids: list[str] = Field(default_factory=list)
    website: str | None = None
    founded_year: int | None = Field(default=None, ge=1600, le=2200)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        return value.upper()

    @field_validator("classification_ids", "valuation_profile_ids")
    @classmethod
    def unique_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("ID collections must not contain duplicates")
        return value


class SecurityMaster(UniverseModel):
    security_id: str = Field(pattern=r"^security:")
    company_id: str = Field(pattern=r"^company:")
    exchange: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    security_type: str = Field(default="common_stock")
    currency: str = Field(min_length=3, max_length=3)
    status: SecurityStatus = SecurityStatus.ACTIVE
    primary_listing: bool = False
    isin: str | None = None
    figi: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("exchange", "ticker", "currency")
    @classmethod
    def normalize_codes(cls, value: str) -> str:
        return value.upper()


class UniverseManifest(UniverseModel):
    schema_version: str = "1.0.0"
    as_of_date: str
    company_count: int = Field(ge=0)
    security_count: int = Field(ge=0)
    classification_count: int = Field(ge=0)
    valuation_profile_assignment_count: int = Field(ge=0)
    source_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
