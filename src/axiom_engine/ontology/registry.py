from __future__ import annotations
from collections import deque
from .models import OntologyBundle

class OntologyRegistry:
    def __init__(self, bundle: OntologyBundle):
        self.bundle=bundle; self.entities={x.entity_id:x for x in bundle.entities}
    def parents(self, entity_id: str):
        return tuple(sorted(r.target_entity_id for r in self.bundle.relations if r.source_entity_id==entity_id))
    def children(self, entity_id: str):
        return tuple(sorted(r.source_entity_id for r in self.bundle.relations if r.target_entity_id==entity_id))
    def path(self, source_id: str, target_id: str):
        q=deque([(source_id,(source_id,))]); seen={source_id}
        while q:
            node,path=q.popleft()
            if node==target_id:return path
            nxt=sorted(r.target_entity_id for r in self.bundle.relations if r.source_entity_id==node)
            for n in nxt:
                if n not in seen: seen.add(n); q.append((n,path+(n,)))
        return ()
