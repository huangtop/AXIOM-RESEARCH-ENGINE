#!/usr/bin/env python3
import argparse
from pathlib import Path

from axiom_engine.sec_filing_refresh import build_sec_filing_refresh_plan, write_sec_filing_refresh_plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan event-driven SEC filing refresh")
    parser.add_argument("--submissions-bulk-zip")
    parser.add_argument(
        "--output",
        default="data/generated/sec_filing_refresh/refresh_plan.json",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = build_sec_filing_refresh_plan(
        root,
        submissions_bulk_zip=args.submissions_bulk_zip,
    )
    write_sec_filing_refresh_plan(report, root / args.output)
    print(report["summary"])


if __name__ == "__main__":
    main()
