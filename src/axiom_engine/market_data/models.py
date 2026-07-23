from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MarketModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class MarketProvenance(MarketModel):
    provenance_id: str = Field(pattern=r"^provenance:")
    provider_id: str = Field(pattern=r"^provider:")
    source_type: Literal["exchange", "licensed_vendor", "company_filing", "manual_fixture"]
    source_name: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    retrieved_at: datetime
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarketObservation(MarketModel):
    market_observation_id: str = Field(pattern=r"^market_observation:")
    company_id: str = Field(pattern=r"^company:")
    security_id: str = Field(pattern=r"^security:")
    metric: Literal[
        "current_price",
        "previous_close",
        "market_cap",
        "enterprise_value",
        "shares_outstanding",
    ]
    value: Decimal = Field(ge=0)
    unit: Literal["currency", "shares"]
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    observed_at: datetime
    trading_date: date
    session: Literal["regular", "pre_market", "after_hours", "completed_session"]
    provenance_ids: list[str] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @field_validator("provenance_ids")
    @classmethod
    def validate_provenance_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("provenance_ids must be unique")
        if any(not value.startswith("provenance:") for value in values):
            raise ValueError("provenance_ids must use provenance: namespace")
        return values

    @model_validator(mode="after")
    def validate_units(self) -> "MarketObservation":
        currency_metrics = {"current_price", "previous_close", "market_cap", "enterprise_value"}
        if self.metric in currency_metrics:
            if self.unit != "currency" or not self.currency:
                raise ValueError(f"{self.metric} requires unit=currency and currency")
        elif self.metric == "shares_outstanding":
            if self.unit != "shares" or self.currency is not None:
                raise ValueError("shares_outstanding requires unit=shares without currency")
        if self.observed_at.date() < self.trading_date:
            raise ValueError("observed_at cannot precede trading_date")
        return self


class TradingStatus(MarketModel):
    trading_status_id: str = Field(pattern=r"^trading_status:")
    company_id: str = Field(pattern=r"^company:")
    security_id: str = Field(pattern=r"^security:")
    status: Literal["active", "halted", "suspended", "delisted", "unknown"]
    observed_at: datetime
    trading_date: date
    provenance_ids: list[str] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provenance_ids")
    @classmethod
    def validate_provenance_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("provenance_ids must be unique")
        if any(not value.startswith("provenance:") for value in values):
            raise ValueError("provenance_ids must use provenance: namespace")
        return values


class MarketDataSource(MarketModel):
    schema_version: str = "1.0.0"
    provider_id: str = Field(pattern=r"^provider:")
    provider_name: str = Field(min_length=1)
    as_of_date: date
    provenance: list[MarketProvenance] = Field(min_length=1)
    observations: list[MarketObservation] = Field(min_length=1)
    trading_statuses: list[TradingStatus] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "MarketDataSource":
        provenance_ids = [x.provenance_id for x in self.provenance]
        observation_ids = [x.market_observation_id for x in self.observations]
        status_ids = [x.trading_status_id for x in self.trading_statuses]
        for name, values in (("provenance_id", provenance_ids), ("market_observation_id", observation_ids), ("trading_status_id", status_ids)):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {name}")
        known = set(provenance_ids)
        for item in self.provenance:
            if item.provider_id != self.provider_id:
                raise ValueError(f"provenance {item.provenance_id} provider mismatch")
        for item in [*self.observations, *self.trading_statuses]:
            missing = set(item.provenance_ids) - known
            if missing:
                raise ValueError(f"{item.__class__.__name__} has missing provenance: {sorted(missing)}")
        return self


class MarketImportReport(MarketModel):
    schema_version: str = "1.0.0"
    provider_id: str
    as_of_date: date
    dry_run: bool
    observations_found: int
    trading_statuses_found: int
    companies_found: int
    securities_found: int
    metrics_found: int
    provenance_records: int
    output_directory: str
    written_files: list[str] = Field(default_factory=list)
