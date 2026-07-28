#!/usr/bin/env python3
from pathlib import Path

from axiom_engine.multiple_policy import build_multiple_policy, write_multiple_policy


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_multiple_policy(root)
    write_multiple_policy(report, root / "data/knowledge/valuation_assumptions.json")
    print(report["summary"])


if __name__ == "__main__":
    main()
