#!/usr/bin/env python3
from pathlib import Path

from axiom_engine.knowledge_inference import build_knowledge_inference, write_knowledge_inference


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_knowledge_inference(root)
    write_knowledge_inference(report, root / "data/generated/knowledge_inference/knowledge_inference.json")
    print(report["summary"])


if __name__ == "__main__":
    main()
