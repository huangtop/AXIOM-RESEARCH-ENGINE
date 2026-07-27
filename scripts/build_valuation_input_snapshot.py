#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from axiom_engine.valuation_input import ValuationInputError, build_valuation_input_snapshot, write_valuation_input_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the V030.12.0 valuation input snapshot.")
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--router", default="data/generated/source_router/financial_source_snapshot.json")
    parser.add_argument("--bridge-qa", default="data/generated/bridge_qa/bridge_qa_report.json")
    parser.add_argument("--market", default="data/generated/market/previous_close_cache.json")
    parser.add_argument("--output", type=Path, default=Path("data/generated/valuation_input/valuation_input_snapshot.json"))
    parser.add_argument("--diagnostic", type=Path, default=Path("data/generated/valuation_input/valuation_input_diagnostic.json"))
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    root = args.repository_root.resolve()
    try:
        report = build_valuation_input_snapshot(root, router_path=args.router, qa_path=args.bridge_qa, market_path=args.market, as_of=args.as_of)
    except ValuationInputError as exc:
        print(f"ValuationInputError: {exc}")
        return 2

    if args.write:
        write_valuation_input_snapshot(report, root / args.output, root / args.diagnostic)
    summary = report["summary"]
    print(f"Companies: {summary['company_count']}")
    print(f"Valuation ready: {summary['valuation_ready_company_count']}")
    print(f"Market cached symbols: {summary['market_cached_symbol_count']}")
    print(f"Market matched companies: {summary['market_matched_company_count']}")
    print(f"Financial only: {summary['input_state_counts'].get('financial_only', 0)}")
    print(f"Market only: {summary['input_state_counts'].get('market_only', 0)}")
    print(f"Insufficient: {summary['input_state_counts'].get('insufficient', 0)}")
    print(f"Missing market: {summary['missing_market_company_count']}")
    print(f"Invalid market: {summary['invalid_market_company_count']}")
    if args.write:
        print(f"Output: {args.output}")
        print(f"Diagnostic: {args.diagnostic}")
    if args.strict and summary["invalid_market_company_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
