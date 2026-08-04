#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.coverage_policy import build_coverage_policy, write_coverage_policy  # noqa: E402


def main() -> None:
    root = ROOT
    report = build_coverage_policy(root)
    write_coverage_policy(report, root / "data/generated/coverage_policy/coverage_policy.json")
    print(report["summary"])


if __name__ == "__main__":
    main()
