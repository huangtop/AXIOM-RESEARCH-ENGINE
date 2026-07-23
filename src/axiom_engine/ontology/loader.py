from __future__ import annotations
import json
from pathlib import Path
from .models import EntityType, RelationType, OntologyEntity, OntologyRelation, OntologyBundle

def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def load_ontology(root: str | Path = "data/ontology") -> OntologyBundle:
    root = Path(root)
    ets = tuple(EntityType(**x) for x in _read(root / "entity_types.json"))
    rts = tuple(RelationType(**{**x, "source_types": tuple(x["source_types"]), "target_types": tuple(x["target_types"])}) for x in _read(root / "relation_types.json"))
    ents = tuple(OntologyEntity(**{**x, "aliases": tuple(x.get("aliases", []))}) for x in _read(root / "canonical_entities.json"))
    rels = tuple(OntologyRelation(**x) for x in _read(root / "canonical_relations.json"))
    return OntologyBundle(ets, rts, ents, rels, _read(root / "ontology_manifest.json"))
