from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class CompanyMaster(UniverseModel):
    company_id: str = Field(pattern=r"^company:")
    legal_name: str = Field(min_length=1)
    display_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    country: str = Field(min_length=2, max_length=2)
    status: CompanyStatus = CompanyStatus.ACTIVE
    primary_security_id: str | None = Field(default=None, pattern=r"^security:")
    research_level: ResearchLevel = ResearchLevel.NONE
    website: str | None = None
    founded_year: int | None = Field(default=None, ge=1600, le=2200)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        return value.upper()


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
    source_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
