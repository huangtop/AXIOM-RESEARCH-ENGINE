#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from axiom_engine.valuation_engine import ValuationEngineError, build_valuation_engine, write_valuation_engine

def main() -> int:
    parser = argparse.ArgumentParser(description="Build V030.13.0 multiple valuation engine foundation snapshot")
    parser.add_argument("--root", default=".")
    parser.add_argument("--input", default="data/generated/valuation_method_inputs/valuation_method_inputs.json")
    parser.add_argument("--output", default="data/generated/valuation_engine/valuation_snapshot.json")
    parser.add_argument("--diagnostic", default="data/generated/valuation_engine/valuation_engine_diagnostic.json")
    parser.add_argument("--write", action="store_true"); parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(); root = Path(args.root).resolve()
    try: report = build_valuation_engine(root, input_path=args.input)
    except ValuationEngineError as exc:
        print(f"ValuationEngineError: {exc}"); return 2
    summary = report["summary"]
    print(f"Companies: {summary['company_count']}"); print(f"Methods: {summary['method_count']}")
    for method, counts in summary["method_engine_counts"].items():
        print(f"{method}: calculated={counts['calculated']} blocked={counts['blocked']} invalid={counts['invalid']}")
    print(f"Calculated method records: {summary['calculated_method_record_count']}")
    print(f"Blocked method records: {summary['blocked_method_record_count']}")
    print(f"Invalid method records: {summary['invalid_method_record_count']}")
    if args.write:
        write_valuation_engine(report, root / args.output, root / args.diagnostic)
        print(f"Output: {args.output}"); print(f"Diagnostic: {args.diagnostic}")
    else: print(json.dumps(summary, indent=2))
    return 1 if args.strict and summary["invalid_method_record_count"] else 0
if __name__ == "__main__": raise SystemExit(main())
