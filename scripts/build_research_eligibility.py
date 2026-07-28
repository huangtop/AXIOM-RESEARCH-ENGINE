#!/usr/bin/env python3
from pathlib import Path

from axiom_engine.research_eligibility import build_research_eligibility, write_research_eligibility


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_research_eligibility(root)
    write_research_eligibility(report, root / "data/generated/research_eligibility/research_eligibility.json")
    print(report["summary"])


if __name__ == "__main__":
    main()
