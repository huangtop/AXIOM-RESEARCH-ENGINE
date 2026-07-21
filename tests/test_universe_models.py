import pytest
from pydantic import ValidationError

from axiom_engine.models.universe import (
    ClassificationNode,
    ClassificationType,
    CompanyMaster,
    ResearchLevel,
    SecurityMaster,
    ValuationProfileAssignment,
)


def test_company_master_accepts_existing_axiom_ids() -> None:
    company = CompanyMaster(
        company_id="company:US-NVDA",
        legal_name="NVIDIA Corporation",
        display_name="NVIDIA",
        country="us",
        primary_security_id="security:NASDAQ-NVDA",
        research_level=ResearchLevel.CORE,
        classification_ids=["industry:fabless-semiconductor", "theme:ai-compute"],
        valuation_profile_ids=["valuation_profile:high-growth-ai-semiconductor"],
    )
    assert company.country == "US"
    assert company.research_level == ResearchLevel.CORE


def test_company_master_rejects_duplicate_ids() -> None:
    with pytest.raises(ValidationError):
        CompanyMaster(
            company_id="company:US-NVDA",
            legal_name="NVIDIA Corporation",
            country="US",
            classification_ids=["theme:ai", "theme:ai"],
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


def test_taxonomy_path_must_end_with_node_id() -> None:
    with pytest.raises(ValidationError):
        ClassificationNode(
            classification_id="theme:ai-compute",
            classification_type=ClassificationType.THEME,
            name="AI Compute",
            taxonomy_path=["theme:ai-tech"],
        )


def test_valuation_profile_assignment_reuses_v07_profile_id() -> None:
    assignment = ValuationProfileAssignment(
        assignment_id="valuation_profile_assignment:US-NVDA:high-growth-ai-semiconductor",
        company_id="company:US-NVDA",
        profile_id="valuation_profile:high-growth-ai-semiconductor",
        reason_zh_tw="高成長且已獲利的 AI 無晶圓廠半導體公司。",
    )
    assert assignment.profile_id.startswith("valuation_profile:")
