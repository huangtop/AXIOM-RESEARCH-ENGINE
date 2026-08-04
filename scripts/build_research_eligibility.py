#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.research_eligibility import (  # noqa: E402
    build_research_eligibility,
    write_research_eligibility,
)


def main() -> None:
    root = ROOT
    report = build_research_eligibility(root)
    write_research_eligibility(report, root / "data/generated/research_eligibility/research_eligibility.json")
    print(report["summary"])


if __name__ == "__main__":
    main()
