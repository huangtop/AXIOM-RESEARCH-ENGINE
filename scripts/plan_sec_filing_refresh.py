#!/usr/bin/env python3
from pathlib import Path

from axiom_engine.sec_filing_refresh import build_sec_filing_refresh_plan, write_sec_filing_refresh_plan


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_sec_filing_refresh_plan(root)
    write_sec_filing_refresh_plan(report, root / "data/generated/sec_filing_refresh/refresh_plan.json")
    print(report["summary"])


if __name__ == "__main__":
    main()
