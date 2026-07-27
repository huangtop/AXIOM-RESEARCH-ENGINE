#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from axiom_engine.valuation_qa import ValuationQAError, run_valuation_qa, write_valuation_qa


def main() -> int:
    parser = argparse.ArgumentParser(description="Run V030.12.3 valuation QA gates")
    parser.add_argument("--root", default=".")
    parser.add_argument("--eligibility", default="data/generated/valuation_eligibility/valuation_method_eligibility.json")
    parser.add_argument("--method-inputs", default="data/generated/valuation_method_inputs/valuation_method_inputs.json")
    parser.add_argument("--output", default="data/generated/valuation_qa/valuation_qa_report.json")
    parser.add_argument("--tolerance", type=float, default=1e-8)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        report = run_valuation_qa(root, eligibility_path=args.eligibility, method_inputs_path=args.method_inputs, tolerance=args.tolerance)
    except ValuationQAError as exc:
        print(f"ValuationQAError: {exc}")
        return 2
    summary = report["summary"]
    print(f"Status: {summary['status']}")
    print(f"Companies: {summary['company_count']}")
    print(f"Methods checked: {summary['method_record_count']}")
    print(f"Prepared methods: {summary['prepared_method_count']}")
    print(f"Blocked methods: {summary['blocked_method_count']}")
    print(f"Invalid methods: {summary['invalid_method_count']}")
    print(f"Critical issues: {summary['critical_issue_count']}")
    print(f"Warnings: {summary['warning_issue_count']}")
    for gate, state in report["gates"].items():
        print(f"Gate {gate}: {state}")
    if args.write:
        write_valuation_qa(report, root / args.output)
        print(f"Output: {args.output}")
    else:
        print(json.dumps(summary, indent=2))
    if args.strict and summary["status"] != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
