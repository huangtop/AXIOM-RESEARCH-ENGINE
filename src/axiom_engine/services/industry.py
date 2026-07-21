from __future__ import annotations
from collections import defaultdict, deque
from ..repository import RepositoryBundle


def industry_summary(bundle: RepositoryBundle, company_id: str) -> dict:
    entities = {x.entity_id: x for x in bundle.entities}
    exposures = [x for x in bundle.industry_exposures if x.company_id == company_id]
    relevant = {company_id, *(x.entity_id for x in exposures)}
    edges = [x for x in bundle.industry_edges if x.source_entity_id in relevant or x.target_entity_id in relevant]
    relevant.update(x.source_entity_id for x in edges)
    relevant.update(x.target_entity_id for x in edges)
    return {
        "company_id": company_id,
        "entities": [entities[x].model_dump(mode="json", exclude_none=True) for x in sorted(relevant) if x in entities],
        "exposures": [x.model_dump(mode="json", exclude_none=True) for x in exposures],
        "edges": [x.model_dump(mode="json", exclude_none=True) for x in edges],
    }


def find_paths(bundle: RepositoryBundle, source_id: str, target_id: str, max_depth: int = 6) -> list[list[str]]:
    graph: dict[str, list[str]] = defaultdict(list)
    for edge in bundle.industry_edges:
        if edge.active:
            graph[edge.source_entity_id].append(edge.target_entity_id)
    paths: list[list[str]] = []
    q = deque([[source_id]])
    while q:
        path = q.popleft()
        if len(path) - 1 > max_depth:
            continue
        node = path[-1]
        if node == target_id:
            paths.append(path)
            continue
        for nxt in graph[node]:
            if nxt not in path:
                q.append(path + [nxt])
    return paths
