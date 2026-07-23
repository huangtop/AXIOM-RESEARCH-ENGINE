from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class EntityType:
    entity_type_id: str
    name: str
    description: str

@dataclass(frozen=True)
class RelationType:
    relation_type_id: str
    category: str
    source_types: tuple[str, ...]
    target_types: tuple[str, ...]
    directed: bool
    allow_self: bool
    definition: str

@dataclass(frozen=True)
class OntologyEntity:
    entity_id: str
    entity_type_id: str
    canonical_name: str
    name_zh_tw: str | None = None
    description: str = ""
    status: str = "active"
    aliases: tuple[str, ...] = ()

@dataclass(frozen=True)
class OntologyRelation:
    relation_id: str
    source_entity_id: str
    relation_type_id: str
    target_entity_id: str
    status: str = "approved"
    evidence_policy: str = "ontology_definition"

@dataclass(frozen=True)
class OntologyBundle:
    entity_types: tuple[EntityType, ...]
    relation_types: tuple[RelationType, ...]
    entities: tuple[OntologyEntity, ...]
    relations: tuple[OntologyRelation, ...]
    manifest: dict[str, Any]
