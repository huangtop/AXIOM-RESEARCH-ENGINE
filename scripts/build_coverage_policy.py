#!/usr/bin/env python3
from pathlib import Path

from axiom_engine.coverage_policy import build_coverage_policy, write_coverage_policy


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_coverage_policy(root)
    write_coverage_policy(report, root / "data/generated/coverage_policy/coverage_policy.json")
    print(report["summary"])


if __name__ == "__main__":
    main()
