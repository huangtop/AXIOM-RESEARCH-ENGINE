#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from axiom_engine.valuation_method_inputs import ValuationMethodInputsError, build_valuation_method_inputs, write_valuation_method_inputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Build V030.12.2 valuation method inputs snapshot")
    parser.add_argument("--root", default=".")
    parser.add_argument("--input", default="data/generated/valuation_input/valuation_input_snapshot.json")
    parser.add_argument("--eligibility", default="data/generated/valuation_eligibility/valuation_method_eligibility.json")
    parser.add_argument("--output", default="data/generated/valuation_method_inputs/valuation_method_inputs.json")
    parser.add_argument("--diagnostic", default="data/generated/valuation_method_inputs/valuation_method_inputs_diagnostic.json")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        report = build_valuation_method_inputs(root, input_path=args.input, eligibility_path=args.eligibility)
    except ValuationMethodInputsError as exc:
        print(f"ValuationMethodInputsError: {exc}")
        return 2
    summary = report["summary"]
    print(f"Companies: {summary['company_count']}")
    print(f"Methods: {summary['method_count']}")
    for method, counts in summary["method_input_counts"].items():
        print(f"{method}: prepared={counts['prepared']} blocked={counts['blocked']}")
    print(f"Prepared method records: {summary['prepared_method_record_count']}")
    print(f"Blocked method records: {summary['blocked_method_record_count']}")
    print(f"Invalid method records: {summary['invalid_method_record_count']}")
    if args.write:
        write_valuation_method_inputs(report, root / args.output, root / args.diagnostic)
        print(f"Output: {args.output}")
        print(f"Diagnostic: {args.diagnostic}")
    else:
        print(json.dumps(summary, indent=2))
    if args.strict and summary["invalid_method_record_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
