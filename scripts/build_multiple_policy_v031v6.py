#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.multiple_policy import build_multiple_policy, write_multiple_policy  # noqa: E402


def main() -> None:
    root = ROOT
    report = build_multiple_policy(root)
    write_multiple_policy(report, root / "data/knowledge/valuation_assumptions.json")
    print(report["summary"])


if __name__ == "__main__":
    main()
