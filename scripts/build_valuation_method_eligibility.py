#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from axiom_engine.valuation_eligibility import (
    ValuationEligibilityError,
    build_valuation_method_eligibility,
    write_valuation_method_eligibility,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build V030.12.1 valuation method eligibility snapshot")
    parser.add_argument("--root", default=".")
    parser.add_argument("--input", default="data/generated/valuation_input/valuation_input_snapshot.json")
    parser.add_argument("--output", default="data/generated/valuation_eligibility/valuation_method_eligibility.json")
    parser.add_argument("--diagnostic", default="data/generated/valuation_eligibility/valuation_method_eligibility_diagnostic.json")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    try:
        report = build_valuation_method_eligibility(root, input_path=args.input)
    except ValuationEligibilityError as exc:
        print(f"ValuationEligibilityError: {exc}")
        return 2

    summary = report["summary"]
    print(f"Companies: {summary['company_count']}")
    print(f"Methods: {summary['method_count']}")
    for method, counts in summary["method_eligibility_counts"].items():
        print(f"{method}: eligible={counts['eligible']} blocked={counts['blocked']}")
    print(f"Blocked method records: {summary['blocked_method_record_count']}")

    if args.write:
        output = root / args.output
        diagnostic = root / args.diagnostic
        write_valuation_method_eligibility(report, output, diagnostic)
        print(f"Output: {args.output}")
        print(f"Diagnostic: {args.diagnostic}")
    else:
        print(json.dumps(summary, indent=2))

    if args.strict and summary["company_count"] == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
