import pytest
from pydantic import ValidationError

from axiom_engine.models.universe import CompanyMaster, ResearchLevel, SecurityMaster


def test_company_master_accepts_existing_axiom_ids() -> None:
    company = CompanyMaster(
        company_id="company:US-NVDA",
        legal_name="NVIDIA Corporation",
        display_name="NVIDIA",
        country="us",
        primary_security_id="security:NASDAQ-NVDA",
        research_level=ResearchLevel.CORE,
    )
    assert company.country == "US"
    assert company.research_level == ResearchLevel.CORE


def test_company_master_rejects_retired_taxonomy_fields() -> None:
    with pytest.raises(ValidationError):
        CompanyMaster(
            company_id="company:US-NVDA",
            legal_name="NVIDIA Corporation",
            country="US",
            classification_ids=["theme:ai"],
        )


def test_security_is_separate_from_company() -> None:
    security = SecurityMaster(
        security_id="security:NASDAQ-NVDA",
        company_id="company:US-NVDA",
        exchange="nasdaq",
        ticker="nvda",
        currency="usd",
        primary_listing=True,
    )
    assert security.exchange == "NASDAQ"
    assert security.ticker == "NVDA"
    assert security.currency == "USD"
