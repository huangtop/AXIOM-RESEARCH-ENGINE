#!/usr/bin/env python3
from pathlib import Path

from axiom_engine.classification_quality import build_classification_quality_audit, write_classification_quality_audit


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_classification_quality_audit(root)
    write_classification_quality_audit(report, root / "data/generated/classification_quality/coverage_audit.json")
    print(report["summary"])


if __name__ == "__main__":
    main()
