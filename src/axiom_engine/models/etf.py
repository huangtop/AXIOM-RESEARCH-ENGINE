from __future__ import annotations

from datetime import date
from pydantic import Field, model_validator
from .core import StrictModel


class ETFProfile(StrictModel):
    etf_id: str
    entity_id: str
    ticker: str
    issuer: str
    benchmark: str
    currency: str = "USD"
    expense_ratio: float | None = Field(default=None, ge=0, le=1)
    inception_date: date | None = None
    active: bool = True
    notes_zh_tw: str = ""


class ETFHolding(StrictModel):
    holding_id: str
    etf_id: str
    company_id: str
    security_id: str | None = None
    weight: float = Field(gt=0, le=1)
    shares: float | None = Field(default=None, ge=0)
    market_value: float | None = Field(default=None, ge=0)
    as_of_date: date
    source_ids: list[str] = Field(default_factory=list)


class ETFThemeExposure(StrictModel):
    exposure_id: str
    etf_id: str
    entity_id: str
    exposure_type: str
    derived_weight: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    as_of_date: date
    source_holding_ids: list[str] = Field(default_factory=list)
    methodology: str = "holding_weight_x_company_exposure_weight"


class ETFValuationSnapshot(StrictModel):
    snapshot_id: str
    etf_id: str
    as_of_date: date
    weighted_upside: float | None = None
    valuation_coverage: float = Field(ge=0, le=1)
    covered_holding_ids: list[str] = Field(default_factory=list)
    missing_company_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def covered_or_missing(self):
        if not self.covered_holding_ids and not self.missing_company_ids:
            raise ValueError("ETF valuation snapshot must identify coverage")
        return self
