#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.financial_bridge import build_financial_bridge, write_financial_bridge


def main() -> int:
    parser = argparse.ArgumentParser(description="Build V030.11.0 canonical SEC financial snapshot")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--facts", default="data/financial_data/financial_facts.json")
    parser.add_argument("--identity", default="data/generated/identity/company_identity_map.json")
    parser.add_argument("--output", default="data/generated/financial_bridge/canonical_financial_snapshot.json")
    parser.add_argument("--diagnostic", default="data/generated/financial_bridge/financial_bridge_diagnostic.json")
    args = parser.parse_args()

    report = build_financial_bridge(ROOT, financial_facts_path=args.facts, identity_map_path=args.identity)
    summary = report["summary"]
    print(f"Source facts: {summary['source_fact_count']}")
    print(f"Canonical facts: {summary['canonical_fact_count']}")
    print(f"Source companies: {summary['source_company_count']}")
    print(f"Canonical companies: {summary['canonical_company_count']}")
    print(f"Unmapped companies: {summary['unmapped_company_count']}")
    print(f"Unmapped facts: {summary['unmapped_fact_count']}")
    print(f"Invalid rows: {summary['invalid_row_count']}")
    print(f"Duplicate fact IDs: {summary['duplicate_fact_id_count']}")
    if args.write:
        write_financial_bridge(report, ROOT / args.output, ROOT / args.diagnostic)
        print(f"Output: {args.output}")
        print(f"Diagnostic: {args.diagnostic}")
    if args.strict and (
        summary["invalid_row_count"]
        or summary["duplicate_fact_id_count"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
