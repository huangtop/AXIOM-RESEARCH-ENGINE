from __future__ import annotations
from .models import OntologyBundle

FORBIDDEN_KEYS = {"ticker", "symbol", "theme_ids", "classification_ids", "current_price", "revenue_ttm", "eps", "analyst_target", "valuation", "logic_type", "default_params"}

def validate_ontology(bundle: OntologyBundle) -> dict[str, int]:
    def unique(values, label):
        if len(values) != len(set(values)): raise ValueError(f"duplicate {label}")
    unique([x.entity_type_id for x in bundle.entity_types], "entity_type_id")
    unique([x.relation_type_id for x in bundle.relation_types], "relation_type_id")
    unique([x.entity_id for x in bundle.entities], "entity_id")
    unique([x.relation_id for x in bundle.relations], "relation_id")
    etypes={x.entity_type_id for x in bundle.entity_types}; entities={x.entity_id:x for x in bundle.entities}; rtypes={x.relation_type_id:x for x in bundle.relation_types}
    for e in bundle.entities:
        if e.entity_type_id not in etypes: raise ValueError(f"unknown entity type: {e.entity_id}")
        if e.entity_type_id == "company" or e.entity_id.startswith(("company:", "ticker:", "security:")): raise ValueError("company/security membership is forbidden in V016 ontology")
    for r in bundle.relations:
        if r.status != "approved": raise ValueError("canonical relations must be approved")
        if r.source_entity_id not in entities or r.target_entity_id not in entities: raise ValueError(f"dangling relation: {r.relation_id}")
        if r.relation_type_id not in rtypes: raise ValueError(f"unknown relation type: {r.relation_id}")
        rt=rtypes[r.relation_type_id]; s=entities[r.source_entity_id]; t=entities[r.target_entity_id]
        if s.entity_type_id not in rt.source_types or t.entity_type_id not in rt.target_types: raise ValueError(f"illegal endpoint types: {r.relation_id}")
        if s.entity_id == t.entity_id and not rt.allow_self: raise ValueError(f"illegal self relation: {r.relation_id}")
    # taxonomic cycle guard
    graph={e.entity_id:[] for e in bundle.entities}
    for r in bundle.relations:
        if r.relation_type_id in {"is_a", "belongs_to", "part_of"}: graph[r.source_entity_id].append(r.target_entity_id)
    visiting=set(); visited=set()
    def dfs(n):
        if n in visiting: raise ValueError("taxonomy cycle")
        if n in visited: return
        visiting.add(n)
        for m in graph[n]: dfs(m)
        visiting.remove(n); visited.add(n)
    for n in sorted(graph): dfs(n)
    return {"entity_types":len(bundle.entity_types),"relation_types":len(bundle.relation_types),"entities":len(bundle.entities),"relations":len(bundle.relations)}
