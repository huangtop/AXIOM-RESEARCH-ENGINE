from __future__ import annotations

from dataclasses import dataclass

from .config import CANONICAL_DIR, VALUATION_DIR
from .io import load_models
from .models import (
    CompanyValuationProfile,
    Entity,
    Estimate,
    Evidence,
    FinancialFact,
    Relation,
    Security,
    Source,
    ValuationAssumption,
    ValuationProfile,
    ValuationScenario,
)


@dataclass(frozen=True)
class RepositoryBundle:
    entities: list[Entity]
    securities: list[Security]
    relations: list[Relation]
    evidence: list[Evidence]
    sources: list[Source]
    financial_facts: list[FinancialFact]
    estimates: list[Estimate]
    valuation_profiles: list[ValuationProfile]
    company_valuation_profiles: list[CompanyValuationProfile]
    valuation_scenarios: list[ValuationScenario]
    valuation_assumptions: list[ValuationAssumption]


def load_bundle() -> RepositoryBundle:
    return RepositoryBundle(
        entities=load_models(CANONICAL_DIR / "entities.json", Entity),
        securities=load_models(CANONICAL_DIR / "securities.json", Security),
        relations=load_models(CANONICAL_DIR / "relations.json", Relation),
        evidence=load_models(CANONICAL_DIR / "evidence.json", Evidence),
        sources=load_models(CANONICAL_DIR / "sources.json", Source),
        financial_facts=load_models(VALUATION_DIR / "financial_facts.json", FinancialFact),
        estimates=load_models(VALUATION_DIR / "estimates.json", Estimate),
        valuation_profiles=load_models(VALUATION_DIR / "valuation_profiles.json", ValuationProfile),
        company_valuation_profiles=load_models(
            VALUATION_DIR / "company_valuation_profiles.json",
            CompanyValuationProfile,
        ),
        valuation_scenarios=load_models(
            VALUATION_DIR / "valuation_scenarios.json", ValuationScenario
        ),
        valuation_assumptions=load_models(
            VALUATION_DIR / "valuation_assumptions.json",
            ValuationAssumption,
        ),
    )
