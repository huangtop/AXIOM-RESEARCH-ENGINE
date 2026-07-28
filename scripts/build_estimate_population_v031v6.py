#!/usr/bin/env python3
from pathlib import Path

from axiom_engine.estimate_population import build_estimate_population, write_estimate_population


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_estimate_population(root)
    write_estimate_population(report, root / "data/estimate_data/consensus_estimates.json")
    print(report["summary"])


if __name__ == "__main__":
    main()
