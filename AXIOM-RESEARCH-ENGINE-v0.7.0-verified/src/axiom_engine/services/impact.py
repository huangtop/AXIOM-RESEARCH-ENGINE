from __future__ import annotations

from collections import defaultdict, deque
from datetime import date
from ..models import CompanyImpactSnapshot, ETFImpactSnapshot, ImpactNode, PropagationMode
from ..repository import RepositoryBundle


def _cap(value: float) -> float:
    return round(max(-1.0, min(1.0, value)), 6)


def propagate_shock(bundle: RepositoryBundle, shock_id: str, max_hops: int = 6) -> list[ImpactNode]:
    shock = next((x for x in bundle.shocks if x.shock_id == shock_id), None)
    if shock is None:
        raise ValueError(f"Unknown shock: {shock_id}")
    rules = {x.edge_id: x for x in bundle.propagation_rules}
    outgoing = defaultdict(list)
    for edge in bundle.industry_edges:
        if edge.active:
            outgoing[edge.source_entity_id].append(edge)

    queue = deque([(shock.entity_id, shock.signed_magnitude, shock.confidence, 0, [shock.entity_id], [])])
    results = []
    best_abs: dict[str, float] = {shock.entity_id: abs(shock.signed_magnitude)}
    while queue:
        entity_id, impact, confidence, lag, path, edge_ids = queue.popleft()
        results.append(ImpactNode(entity_id=entity_id, impact=_cap(impact), confidence=round(confidence, 6), lag_months=lag, path=path, edge_ids=edge_ids))
        if len(edge_ids) >= max_hops:
            continue
        for edge in outgoing.get(entity_id, []):
            rule = rules.get(edge.edge_id)
            if rule and rule.propagation_mode == PropagationMode.blocked:
                continue
            elasticity = rule.elasticity if rule else 1.0
            attenuation = rule.attenuation if rule else 1.0
            next_impact = impact * edge.strength * elasticity * attenuation
            next_confidence = confidence * edge.confidence
            next_lag = lag + (edge.lead_lag_months or 0)
            target = edge.target_entity_id
            if target in path:
                continue
            if abs(next_impact) <= best_abs.get(target, 0.0) + 1e-12:
                continue
            best_abs[target] = abs(next_impact)
            queue.append((target, next_impact, next_confidence, next_lag, path + [target], edge_ids + [edge.edge_id]))
    return results


def company_impacts(bundle: RepositoryBundle, shock_id: str) -> list[CompanyImpactSnapshot]:
    nodes = propagate_shock(bundle, shock_id)
    companies = {x.entity_id for x in bundle.entities if x.entity_type.value == "company"}
    output = []
    for node in nodes:
        if node.entity_id not in companies:
            continue
        revenue = node.impact
        eps = _cap(revenue * 1.15)
        fair_value = _cap(eps * 1.10)
        output.append(CompanyImpactSnapshot(
            snapshot_id=f"company_impact:{shock_id}:{node.entity_id}", shock_id=shock_id,
            company_id=node.entity_id, as_of_date=date.today(), estimated_revenue_impact=revenue,
            estimated_eps_impact=eps, estimated_fair_value_impact=fair_value,
            confidence=node.confidence, source_paths=[node.path],
        ))
    return output


def etf_impacts(bundle: RepositoryBundle, shock_id: str) -> list[ETFImpactSnapshot]:
    by_company = {x.company_id: x for x in company_impacts(bundle, shock_id)}
    output = []
    for profile in bundle.etf_profiles:
        holdings = [x for x in bundle.etf_holdings if x.etf_id == profile.etf_id]
        weighted = 0.0
        coverage = 0.0
        conf_num = 0.0
        contributors = []
        for holding in holdings:
            impact = by_company.get(holding.company_id)
            if impact is None:
                continue
            contribution = holding.weight * impact.estimated_fair_value_impact
            weighted += contribution
            coverage += holding.weight
            conf_num += holding.weight * impact.confidence
            contributors.append({"holding_id": holding.holding_id, "company_id": holding.company_id, "weight": holding.weight, "company_fair_value_impact": impact.estimated_fair_value_impact, "contribution": round(contribution, 6)})
        confidence = conf_num / coverage if coverage else 0.0
        output.append(ETFImpactSnapshot(
            snapshot_id=f"etf_impact:{shock_id}:{profile.etf_id}", shock_id=shock_id,
            etf_id=profile.etf_id, as_of_date=date.today(), estimated_fair_value_impact=_cap(weighted),
            impact_coverage=round(coverage, 6), confidence=round(confidence, 6),
            contributors=sorted(contributors, key=lambda x: abs(x["contribution"]), reverse=True),
        ))
    return output


def impact_summary(bundle: RepositoryBundle, shock_id: str) -> dict:
    shock = next((x for x in bundle.shocks if x.shock_id == shock_id), None)
    if shock is None:
        raise ValueError(f"Unknown shock: {shock_id}")
    return {
        "shock": shock.model_dump(mode="json", exclude_none=True),
        "nodes": [x.model_dump(mode="json", exclude_none=True) for x in propagate_shock(bundle, shock_id)],
        "company_impacts": [x.model_dump(mode="json", exclude_none=True) for x in company_impacts(bundle, shock_id)],
        "etf_impacts": [x.model_dump(mode="json", exclude_none=True) for x in etf_impacts(bundle, shock_id)],
        "methodology": {
            "graph_direction": "cause_to_effect",
            "node_impact": "upstream_impact_x_edge_strength_x_elasticity_x_attenuation",
            "confidence": "upstream_confidence_x_edge_confidence",
            "company_mapping": "revenue=node; eps=revenue_x_1.15; fair_value=eps_x_1.10",
            "etf_mapping": "sum(holding_weight_x_company_fair_value_impact)",
        },
    }
