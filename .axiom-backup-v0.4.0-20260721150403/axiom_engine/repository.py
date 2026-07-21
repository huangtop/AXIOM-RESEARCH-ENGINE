from __future__ import annotations
from dataclasses import dataclass
from .config import CANONICAL_DIR, INGESTION_DIR, RESEARCH_DIR, VALUATION_DIR
from .io import load_models
from .models import (
    ArticleAdmission,
    Catalyst,
    CompanyValuationProfile,
    DriverImpact,
    Entity,
    EntityMention,
    Estimate,
    Evidence,
    ExtractedClaim,
    FinancialFact,
    InvestmentThesis,
    RawArticle,
    Relation,
    ResearchDriver,
    ResearchRevision,
    ResearchSnapshot,
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
    research_drivers: list[ResearchDriver]
    catalysts: list[Catalyst]
    driver_impacts: list[DriverImpact]
    investment_theses: list[InvestmentThesis]
    research_snapshots: list[ResearchSnapshot]
    research_revisions: list[ResearchRevision]
    raw_articles: list[RawArticle]
    entity_mentions: list[EntityMention]
    extracted_claims: list[ExtractedClaim]
    article_admissions: list[ArticleAdmission]


def _load(path, model):
    return load_models(path, model) if path.exists() else []


def load_bundle() -> RepositoryBundle:
    return RepositoryBundle(
        _load(CANONICAL_DIR / "entities.json", Entity),
        _load(CANONICAL_DIR / "securities.json", Security),
        _load(CANONICAL_DIR / "relations.json", Relation),
        _load(CANONICAL_DIR / "evidence.json", Evidence),
        _load(CANONICAL_DIR / "sources.json", Source),
        _load(VALUATION_DIR / "financial_facts.json", FinancialFact),
        _load(VALUATION_DIR / "estimates.json", Estimate),
        _load(VALUATION_DIR / "valuation_profiles.json", ValuationProfile),
        _load(VALUATION_DIR / "company_valuation_profiles.json", CompanyValuationProfile),
        _load(VALUATION_DIR / "valuation_scenarios.json", ValuationScenario),
        _load(VALUATION_DIR / "valuation_assumptions.json", ValuationAssumption),
        _load(RESEARCH_DIR / "research_drivers.json", ResearchDriver),
        _load(RESEARCH_DIR / "catalysts.json", Catalyst),
        _load(RESEARCH_DIR / "driver_impacts.json", DriverImpact),
        _load(RESEARCH_DIR / "investment_theses.json", InvestmentThesis),
        _load(RESEARCH_DIR / "research_snapshots.json", ResearchSnapshot),
        _load(RESEARCH_DIR / "research_revisions.json", ResearchRevision),
        _load(INGESTION_DIR / "raw_articles.json", RawArticle),
        _load(INGESTION_DIR / "entity_mentions.json", EntityMention),
        _load(INGESTION_DIR / "extracted_claims.json", ExtractedClaim),
        _load(INGESTION_DIR / "article_admissions.json", ArticleAdmission),
    )
