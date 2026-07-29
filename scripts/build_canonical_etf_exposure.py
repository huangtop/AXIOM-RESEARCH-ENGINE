#!/usr/bin/env python3
from pathlib import Path

from axiom_engine.canonical_etf_exposure import build_canonical_etf_exposure, write_canonical_etf_exposure


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_canonical_etf_exposure(root)
    write_canonical_etf_exposure(report, root / "data/generated/canonical_etf_exposure")
    print(report["summary"])


if __name__ == "__main__":
    main()
