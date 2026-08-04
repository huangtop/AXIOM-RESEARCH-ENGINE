#!/usr/bin/env python3
from pathlib import Path

from axiom_engine.classification_population import build_research_relevance_gate, write_research_relevance_gate


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_research_relevance_gate(root)
    write_research_relevance_gate(report, root / "data/generated/research_relevance_gate/research_relevance_gate.json")
    print(report["summary"])


if __name__ == "__main__":
    main()
