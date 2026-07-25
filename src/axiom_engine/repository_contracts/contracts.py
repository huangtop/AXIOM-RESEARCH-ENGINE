from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Iterable


class ContractOwner(StrEnum):
    PRODUCTION_REGISTRY = "production_registry"
    PRODUCTION_FINANCIAL = "production_financial"
    PRODUCTION_MARKET = "production_market"
    PRODUCTION_ESTIMATE = "production_estimate"
    PRODUCTION_BUILD = "production_build"
    PRODUCTION_RESEARCH_CARD = "production_research_card"
    CANONICAL_RESEARCH = "canonical_research_repository"
    STRUCTURE_MIGRATION = "structure_migration_pending"


class ContractStatus(StrEnum):
    ACTIVE = "active"
    LEGACY_INPUT = "legacy_input"
    STAGING = "staging"
    PENDING = "pending"


@dataclass(frozen=True, slots=True)
class ContractDefinition:
    contract_id: str
    description: str
    canonical_owner: ContractOwner
    status: ContractStatus
    canonical_paths: tuple[str, ...]
    accepted_inputs: tuple[str, ...] = ()
    legacy_paths: tuple[str, ...] = ()
    forbidden_fields: tuple[str, ...] = ()
    downstream_consumers: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _t(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(values)


CONTRACTS: tuple[ContractDefinition, ...] = (
    ContractDefinition(
        contract_id="company_identity",
        description="Durable company identity and legal/display metadata.",
        canonical_owner=ContractOwner.PRODUCTION_REGISTRY,
        status=ContractStatus.ACTIVE,
        canonical_paths=_t(("data/production/registry/companies.json", "data/generated/production_registry/companies.json")),
        accepted_inputs=_t(("data/universe/companies.json", "data/company_registry/companies.json")),
        legacy_paths=_t(("data/universe/companies.json",)),
        forbidden_fields=_t(("current_price", "revenue_ttm", "analyst_target", "valuation", "logic_type", "default_params")),
        downstream_consumers=_t(("production_financial", "production_market", "production_estimate", "production_research_card")),
        notes="data/universe is an accepted legacy universe source, not a second runtime owner.",
    ),
    ContractDefinition(
        contract_id="security_identity",
        description="Listed security, exchange, ticker, currency and primary-listing relationship.",
        canonical_owner=ContractOwner.PRODUCTION_REGISTRY,
        status=ContractStatus.ACTIVE,
        canonical_paths=_t(("data/production/registry/securities.json", "data/generated/production_registry/securities.json")),
        accepted_inputs=_t(("data/universe/securities.json", "data/company_registry/securities.json")),
        legacy_paths=_t(("data/universe/securities.json",)),
        downstream_consumers=_t(("production_market", "production_research_card")),
    ),
    ContractDefinition(
        contract_id="official_classification",
        description="Externally sourced official sector/industry classification with provenance.",
        canonical_owner=ContractOwner.PRODUCTION_REGISTRY,
        status=ContractStatus.ACTIVE,
        canonical_paths=_t(("data/production/registry/official_classifications.json", "data/generated/production_registry/official_classifications.json")),
        accepted_inputs=_t(("data/company_registry/official_classifications.json",)),
        forbidden_fields=_t(("theme", "cluster", "logic_type", "default_params")),
        downstream_consumers=_t(("structure_migration_pending", "production_research_card")),
        notes="Official classification is distinct from AXIOM investment themes and value-chain roles.",
    ),
    ContractDefinition(
        contract_id="business_description",
        description="Sourced company business description and durable business metadata.",
        canonical_owner=ContractOwner.PRODUCTION_REGISTRY,
        status=ContractStatus.ACTIVE,
        canonical_paths=_t(("data/production/registry/business_descriptions.json", "data/generated/production_registry/business_descriptions.json")),
        accepted_inputs=_t(("data/company_registry/business_descriptions.json",)),
        downstream_consumers=_t(("structure_migration_pending", "production_research_card")),
    ),
    ContractDefinition(
        contract_id="financial_facts",
        description="Normalized point-in-time and duration financial facts with provenance.",
        canonical_owner=ContractOwner.PRODUCTION_FINANCIAL,
        status=ContractStatus.ACTIVE,
        canonical_paths=_t(("data/production/financial/financial_facts.json", "data/generated/production_financial/financial_facts.json")),
        accepted_inputs=_t(("data/financial_data", "data/generated/financial_population_baseline", "data/canonical/financial")),
        legacy_paths=_t(("data/valuation/valuation_facts.json",)),
        downstream_consumers=_t(("production_build", "production_research_card")),
    ),
    ContractDefinition(
        contract_id="market_observations",
        description="Timestamped prices and market observations; no company taxonomy.",
        canonical_owner=ContractOwner.PRODUCTION_MARKET,
        status=ContractStatus.ACTIVE,
        canonical_paths=_t(("data/production/market/market_observations.json", "data/generated/production_market/market_observations.json")),
        accepted_inputs=_t(("data/cache", "data/market_data", "data/onboarding")),
        downstream_consumers=_t(("production_build", "production_research_card")),
    ),
    ContractDefinition(
        contract_id="estimate_observations",
        description="Provider estimates with as-of date and provenance.",
        canonical_owner=ContractOwner.PRODUCTION_ESTIMATE,
        status=ContractStatus.ACTIVE,
        canonical_paths=_t(("data/production/estimate/estimate_observations.json", "data/generated/production_estimate/estimate_observations.json")),
        accepted_inputs=_t(("data/onboarding", "data/estimate_data")),
        downstream_consumers=_t(("production_build", "production_research_card")),
    ),
    ContractDefinition(
        contract_id="valuation_outputs",
        description="Deterministic model outputs derived from canonical registry/financial/market/estimate inputs.",
        canonical_owner=ContractOwner.PRODUCTION_BUILD,
        status=ContractStatus.ACTIVE,
        canonical_paths=_t(("data/production/build/valuations.json", "data/generated/production_build/valuations.json")),
        accepted_inputs=_t(("data/valuation", "data/valuation_assumptions.json")),
        downstream_consumers=_t(("production_research_card",)),
        notes="Legacy valuation data may be parity input but must not silently overwrite production output.",
    ),
    ContractDefinition(
        contract_id="frontend_research_card",
        description="Read-only frontend contract assembled from production outputs.",
        canonical_owner=ContractOwner.PRODUCTION_RESEARCH_CARD,
        status=ContractStatus.ACTIVE,
        canonical_paths=_t(("data/production/research_cards", "data/generated/production_research_cards")),
        accepted_inputs=_t(("data/public",)),
        downstream_consumers=_t(("frontend", "Render preview")),
    ),
    ContractDefinition(
        contract_id="investment_classification",
        description="AXIOM themes, value-chain roles, business model and valuation profile assignments.",
        canonical_owner=ContractOwner.STRUCTURE_MIGRATION,
        status=ContractStatus.PENDING,
        canonical_paths=_t(("data/canonical/company_classifications.json", "data/canonical/valuation_profile_assignments.json")),
        accepted_inputs=_t(("structure.json", "data/taxonomy", "data/universe/valuation_profile_assignments.json")),
        legacy_paths=_t(("structure.json",)),
        downstream_consumers=_t(("automatic_classification", "valuation_model_policy", "production_research_card")),
        notes="V030.3 will migrate structure.json; V030.2 only reserves the contract and detects existing candidates.",
    ),
    ContractDefinition(
        contract_id="deep_research",
        description="Evidence, claims, news, catalysts, research drivers, industry graph and causal impacts for core stocks.",
        canonical_owner=ContractOwner.CANONICAL_RESEARCH,
        status=ContractStatus.ACTIVE,
        canonical_paths=_t(("data/ingestion", "data/research", "data/industry", "data/impact")),
        downstream_consumers=_t(("production_research_card",)),
        notes="Independent from valuation-only market coverage and populated only by research tier.",
    ),
)


def contract_map() -> dict[str, ContractDefinition]:
    return {contract.contract_id: contract for contract in CONTRACTS}
