from pathlib import Path

import pytest

from axiom_engine.models.universe import CompanyMaster, ResearchLevel, SecurityMaster
from axiom_engine.universe_repository import (
    UniverseAmbiguousLookupError,
    UniverseIntegrityError,
    UniverseRecordNotFoundError,
    UniverseRepository,
)


UNIVERSE_DIR = Path(__file__).resolve().parents[1] / "data" / "universe"


def test_repository_loads_and_resolves_official_company() -> None:
    repo = UniverseRepository.from_directory(UNIVERSE_DIR)

    nvda = repo.resolve_company("NVDA")

    assert nvda.company_id == "company:US-CIK0001045810"
    assert nvda.name == "NVIDIA Corporation"
    assert nvda.research_level == ResearchLevel.NONE
    assert nvda.primary_security is not None
    assert nvda.primary_security.security_id == "security:NASDAQ-NVDA"

    # Official Universe records contain market identity data only.
    # Research classifications and valuation assignments are separate enrichments.
    assert nvda.themes == ()
    assert nvda.primary_valuation_profile is None
    assert nvda.primary_model_types == ()
    assert nvda.business_model_ids == ()


def test_repository_supports_company_security_and_exchange_lookup() -> None:
    repo = UniverseRepository.from_directory(UNIVERSE_DIR)

    assert repo.resolve_company("company:US-CIK0001045810").company_id == "company:US-CIK0001045810"
    assert (
        repo.resolve_company("security:NASDAQ-NVDA").company_id
        == "company:US-CIK0001045810"
    )
    assert (
        repo.get_security_by_ticker("nvda", exchange="nasdaq").security_id
        == "security:NASDAQ-NVDA"
    )


def test_missing_records_raise_domain_error() -> None:
    repo = UniverseRepository.from_directory(UNIVERSE_DIR)

    with pytest.raises(UniverseRecordNotFoundError):
        repo.resolve_company("MISSING")


def test_ambiguous_ticker_requires_exchange() -> None:
    company_a = CompanyMaster(company_id="company:US-A", legal_name="A", country="US")
    company_b = CompanyMaster(company_id="company:TW-A", legal_name="A TW", country="TW")
    security_a = SecurityMaster(
        security_id="security:NYSE-DUAL",
        company_id=company_a.company_id,
        exchange="NYSE",
        ticker="DUAL",
        currency="USD",
    )
    security_b = SecurityMaster(
        security_id="security:TWSE-DUAL",
        company_id=company_b.company_id,
        exchange="TWSE",
        ticker="DUAL",
        currency="TWD",
    )
    repo = UniverseRepository(
        companies=[company_a, company_b],
        securities=[security_a, security_b],
        classifications=[],
        valuation_profile_assignments=[],
        valuation_profiles=[],
    )

    with pytest.raises(UniverseAmbiguousLookupError):
        repo.get_security_by_ticker("DUAL")
    assert repo.get_security_by_ticker("DUAL", exchange="TWSE") == security_b


def test_integrity_validation_rejects_broken_references() -> None:
    company = CompanyMaster(
        company_id="company:US-BROKEN",
        legal_name="Broken Company",
        country="US",
        primary_security_id="security:NASDAQ-MISSING",
        classification_ids=["theme:missing"],
    )

    with pytest.raises(UniverseIntegrityError) as exc_info:
        UniverseRepository(
            companies=[company],
            securities=[],
            classifications=[],
            valuation_profile_assignments=[],
            valuation_profiles=[],
        )

    message = str(exc_info.value)
    assert "missing primary security" in message
    assert "missing classification" in message
