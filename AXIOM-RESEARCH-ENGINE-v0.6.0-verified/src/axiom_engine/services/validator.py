from __future__ import annotations
from dataclasses import dataclass
from ..repository import RepositoryBundle


@dataclass(frozen=True)
class ValidationSummary:
    counts: dict[str, int]

    def compact(self):
        return " ".join(f"{k}={v}" for k, v in self.counts.items())


def validate_bundle(b: RepositoryBundle) -> ValidationSummary:
    collections = {k: getattr(b, k) for k in b.__dataclass_fields__}
    id_fields = {
        "entities": "entity_id",
        "securities": "security_id",
        "relations": "relation_id",
        "evidence": "evidence_id",
        "sources": "source_id",
        "financial_facts": "fact_id",
        "estimates": "estimate_id",
        "valuation_profiles": "profile_id",
        "valuation_scenarios": "scenario_id",
        "valuation_assumptions": "assumption_id",
        "research_drivers": "driver_id",
        "catalysts": "catalyst_id",
        "driver_impacts": "impact_id",
        "investment_theses": "thesis_id",
        "research_snapshots": "research_snapshot_id",
        "research_revisions": "research_revision_id",
        "raw_articles": "raw_article_id",
        "entity_mentions": "mention_id",
        "extracted_claims": "claim_id",
        "article_admissions": "admission_id",
        "industry_edges": "edge_id",
        "industry_exposures": "exposure_id",
        "industry_graph_snapshots": "graph_snapshot_id",
        "etf_profiles": "etf_id",
        "etf_holdings": "holding_id",
        "etf_theme_exposures": "exposure_id",
        "etf_valuation_snapshots": "snapshot_id",
    }
    for name, field in id_fields.items():
        vals = [getattr(x, field) for x in collections[name]]
        if len(vals) != len(set(vals)):
            raise ValueError(f"Duplicate {field}")
    entity_ids = {x.entity_id for x in b.entities}
    evidence_ids = {x.evidence_id for x in b.evidence}
    source_ids = {x.source_id for x in b.sources}
    driver_ids = {x.driver_id for x in b.research_drivers}
    catalyst_ids = {x.catalyst_id for x in b.catalysts}
    estimate_ids = {x.estimate_id for x in b.estimates}
    for x in b.research_drivers:
        if x.company_id not in entity_ids:
            raise ValueError(f"Unknown company in {x.driver_id}")
        if set(x.entity_ids) - entity_ids:
            raise ValueError(f"Unknown entities in {x.driver_id}")
        if set(x.evidence_ids) - evidence_ids:
            raise ValueError(f"Unknown evidence in {x.driver_id}")
    for x in b.catalysts:
        if x.company_id not in entity_ids or set(x.subject_entity_ids) - entity_ids:
            raise ValueError(f"Unknown entity in {x.catalyst_id}")
        if set(x.driver_ids) - driver_ids:
            raise ValueError(f"Unknown driver in {x.catalyst_id}")
    for x in b.driver_impacts:
        if x.driver_id not in driver_ids:
            raise ValueError(f"Unknown driver in {x.impact_id}")
        if x.catalyst_id and x.catalyst_id not in catalyst_ids:
            raise ValueError(f"Unknown catalyst in {x.impact_id}")
        if x.target_type == "estimate" and x.target_ref_id not in estimate_ids:
            raise ValueError(f"Unknown estimate in {x.impact_id}")
    for x in b.investment_theses:
        if set(x.driver_ids + x.risk_driver_ids) - driver_ids or set(x.catalyst_ids) - catalyst_ids:
            raise ValueError(f"Unknown research refs in {x.thesis_id}")
    edge_ids = {x.edge_id for x in b.industry_edges}
    exposure_ids = {x.exposure_id for x in b.industry_exposures}
    for x in b.industry_edges:
        if x.source_entity_id not in entity_ids or x.target_entity_id not in entity_ids:
            raise ValueError(f"Unknown entity in {x.edge_id}")
        if set(x.evidence_ids) - evidence_ids:
            raise ValueError(f"Unknown evidence in {x.edge_id}")
    for x in b.industry_exposures:
        if x.company_id not in entity_ids or x.entity_id not in entity_ids:
            raise ValueError(f"Unknown entity in {x.exposure_id}")
        if set(x.driver_ids) - driver_ids:
            raise ValueError(f"Unknown driver in {x.exposure_id}")
        if set(x.evidence_ids) - evidence_ids:
            raise ValueError(f"Unknown evidence in {x.exposure_id}")
    for x in b.industry_graph_snapshots:
        if set(x.edge_ids) - edge_ids or set(x.exposure_ids) - exposure_ids:
            raise ValueError(f"Unknown industry refs in {x.graph_snapshot_id}")

    etf_ids = {x.etf_id for x in b.etf_profiles}
    security_ids = {x.security_id for x in b.securities}
    holding_ids = {x.holding_id for x in b.etf_holdings}
    for x in b.etf_profiles:
        if x.entity_id not in entity_ids:
            raise ValueError(f"Unknown ETF entity in {x.etf_id}")
    for x in b.etf_holdings:
        if x.etf_id not in etf_ids or x.company_id not in entity_ids:
            raise ValueError(f"Unknown ETF/company in {x.holding_id}")
        if x.security_id and x.security_id not in security_ids:
            raise ValueError(f"Unknown security in {x.holding_id}")
    totals = {}
    for x in b.etf_holdings:
        totals[x.etf_id] = totals.get(x.etf_id, 0.0) + x.weight
    for etf_id, total in totals.items():
        if total > 1.000001:
            raise ValueError(f"ETF holding weights exceed 100% for {etf_id}")
    for x in b.etf_theme_exposures:
        if x.etf_id not in etf_ids or x.entity_id not in entity_ids:
            raise ValueError(f"Unknown ETF/entity in {x.exposure_id}")
        if set(x.source_holding_ids) - holding_ids:
            raise ValueError(f"Unknown holding in {x.exposure_id}")
    for x in b.etf_valuation_snapshots:
        if x.etf_id not in etf_ids:
            raise ValueError(f"Unknown ETF in {x.snapshot_id}")
        if set(x.covered_holding_ids) - holding_ids:
            raise ValueError(f"Unknown holding in {x.snapshot_id}")

    for x in b.estimates:
        if (
            set(x.supported_by_driver_ids) - driver_ids
            or set(x.supported_by_catalyst_ids) - catalyst_ids
        ):
            raise ValueError(f"Unknown support refs in {x.estimate_id}")
        if set(x.source_ids) - source_ids:
            raise ValueError(f"Unknown source in {x.estimate_id}")
    return ValidationSummary({k: len(v) for k, v in collections.items()})
