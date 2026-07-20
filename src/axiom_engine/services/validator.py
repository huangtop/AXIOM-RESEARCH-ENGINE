from __future__ import annotations

from dataclasses import dataclass

from ..repository import RepositoryBundle


@dataclass(frozen=True)
class ValidationSummary:
    entities: int
    securities: int
    relations: int
    evidence: int
    sources: int
    financial_facts: int
    estimates: int
    valuation_profiles: int
    company_valuation_profiles: int
    valuation_scenarios: int
    valuation_assumptions: int

    def compact(self) -> str:
        return (
            f"entities={self.entities} securities={self.securities} "
            f"relations={self.relations} evidence={self.evidence} "
            f"sources={self.sources} financial_facts={self.financial_facts} "
            f"estimates={self.estimates} valuation_profiles={self.valuation_profiles} "
            f"company_profiles={self.company_valuation_profiles} "
            f"scenarios={self.valuation_scenarios} "
            f"assumptions={self.valuation_assumptions}"
        )


def validate_bundle(bundle: RepositoryBundle) -> ValidationSummary:
    entity_ids = {x.entity_id for x in bundle.entities}
    security_ids = {x.security_id for x in bundle.securities}
    evidence_ids = {x.evidence_id for x in bundle.evidence}
    source_ids = {x.source_id for x in bundle.sources}
    profile_ids = {x.profile_id for x in bundle.valuation_profiles}
    scenario_ids = {x.scenario_id for x in bundle.valuation_scenarios}
    estimate_ids = {x.estimate_id for x in bundle.estimates}
    fact_ids = {x.fact_id for x in bundle.financial_facts}

    def unique(values: list[str], label: str) -> None:
        if len(values) != len(set(values)):
            raise ValueError(f"Duplicate {label}")

    unique([x.entity_id for x in bundle.entities], "entity_id")
    unique([x.security_id for x in bundle.securities], "security_id")
    unique([x.relation_id for x in bundle.relations], "relation_id")
    unique([x.evidence_id for x in bundle.evidence], "evidence_id")
    unique([x.source_id for x in bundle.sources], "source_id")
    unique([x.fact_id for x in bundle.financial_facts], "fact_id")
    unique([x.estimate_id for x in bundle.estimates], "estimate_id")
    unique([x.profile_id for x in bundle.valuation_profiles], "profile_id")
    unique([x.scenario_id for x in bundle.valuation_scenarios], "scenario_id")
    unique([x.assumption_id for x in bundle.valuation_assumptions], "assumption_id")

    for security in bundle.securities:
        if security.company_id not in entity_ids:
            raise ValueError(f"Unknown company for security {security.security_id}")

    for relation in bundle.relations:
        if relation.subject_id not in entity_ids:
            raise ValueError(f"Unknown relation subject {relation.subject_id}")
        if relation.object_id not in entity_ids:
            raise ValueError(f"Unknown relation object {relation.object_id}")
        missing = set(relation.evidence_ids) - evidence_ids
        if missing:
            raise ValueError(f"Unknown evidence in {relation.relation_id}: {sorted(missing)}")

    for evidence in bundle.evidence:
        missing = set(evidence.source_ids) - source_ids
        if missing:
            raise ValueError(f"Unknown source in {evidence.evidence_id}: {sorted(missing)}")

    for fact in bundle.financial_facts:
        if fact.company_id not in entity_ids:
            raise ValueError(f"Unknown company in fact {fact.fact_id}")
        if fact.security_id and fact.security_id not in security_ids:
            raise ValueError(f"Unknown security in fact {fact.fact_id}")
        if set(fact.source_ids) - source_ids:
            raise ValueError(f"Unknown source in fact {fact.fact_id}")
        if set(fact.input_fact_ids) - fact_ids:
            raise ValueError(f"Unknown input fact in {fact.fact_id}")

    for estimate in bundle.estimates:
        if estimate.company_id not in entity_ids:
            raise ValueError(f"Unknown company in estimate {estimate.estimate_id}")
        if estimate.security_id and estimate.security_id not in security_ids:
            raise ValueError(f"Unknown security in estimate {estimate.estimate_id}")
        if set(estimate.source_ids) - source_ids:
            raise ValueError(f"Unknown source in estimate {estimate.estimate_id}")

    for company_profile in bundle.company_valuation_profiles:
        if company_profile.company_id not in entity_ids:
            raise ValueError(f"Unknown company in company profile {company_profile.company_id}")
        missing = set(company_profile.profile_ids) - profile_ids
        if missing:
            raise ValueError(f"Unknown valuation profiles: {sorted(missing)}")

    for scenario in bundle.valuation_scenarios:
        if scenario.company_id not in entity_ids:
            raise ValueError(f"Unknown company in scenario {scenario.scenario_id}")

    for assumption in bundle.valuation_assumptions:
        if assumption.scenario_id not in scenario_ids:
            raise ValueError(f"Unknown scenario in assumption {assumption.assumption_id}")
        refs = set(assumption.source_ref_ids)
        known_refs = source_ids | estimate_ids | fact_ids
        if refs - known_refs:
            raise ValueError(
                f"Unknown assumption refs in {assumption.assumption_id}: "
                f"{sorted(refs - known_refs)}"
            )

    return ValidationSummary(
        entities=len(bundle.entities),
        securities=len(bundle.securities),
        relations=len(bundle.relations),
        evidence=len(bundle.evidence),
        sources=len(bundle.sources),
        financial_facts=len(bundle.financial_facts),
        estimates=len(bundle.estimates),
        valuation_profiles=len(bundle.valuation_profiles),
        company_valuation_profiles=len(bundle.company_valuation_profiles),
        valuation_scenarios=len(bundle.valuation_scenarios),
        valuation_assumptions=len(bundle.valuation_assumptions),
    )
