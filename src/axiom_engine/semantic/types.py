from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SemanticType(StrEnum):
    FINANCIAL_FACT = "financial_fact"
    MARKET_FACT = "market_fact"
    ESTIMATE_FACT = "estimate_fact"
    VALUATION_RESULT = "valuation_result"
    RESEARCH_OUTPUT = "research_output"
    GENERATED_ARTIFACT = "generated_artifact"
    TEMPLATE = "template"
    FIXTURE = "fixture"
    UNKNOWN = "unknown"


SEMANTIC_ELIGIBLE_LAYERS: dict[SemanticType, tuple[str, ...]] = {
    SemanticType.FINANCIAL_FACT: ("financial",),
    SemanticType.MARKET_FACT: ("market",),
    SemanticType.ESTIMATE_FACT: ("estimate",),
    SemanticType.VALUATION_RESULT: (),
    SemanticType.RESEARCH_OUTPUT: (),
    SemanticType.GENERATED_ARTIFACT: (),
    SemanticType.TEMPLATE: (),
    SemanticType.FIXTURE: (),
    SemanticType.UNKNOWN: (),
}


@dataclass(frozen=True)
class SemanticClassification:
    semantic_type: SemanticType
    confidence: float
    eligible_layers: tuple[str, ...]
    evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "semantic_type": self.semantic_type.value,
            "semantic_confidence": round(self.confidence, 4),
            "eligible_layers": list(self.eligible_layers),
            "semantic_evidence": list(self.evidence),
        }
