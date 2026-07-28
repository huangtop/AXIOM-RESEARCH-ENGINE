#!/usr/bin/env python3
from pathlib import Path

from axiom_engine.company_signals import build_company_signals, write_company_signals


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_company_signals(root)
    write_company_signals(report, root / "data/generated/company_signals/company_signals.json")
    print(report["summary"])


if __name__ == "__main__":
    main()
