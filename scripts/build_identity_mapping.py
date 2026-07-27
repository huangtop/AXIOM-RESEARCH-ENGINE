#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.identity.core import build_identity_mapping, write_identity_mapping


def main() -> int:
    parser = argparse.ArgumentParser(description="Build canonical Symbol/CIK/company_id identity mapping.")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output", default="data/generated/identity/company_identity_map.json")
    parser.add_argument("--diagnostic", default="data/generated/identity/identity_diagnostic.json")
    args = parser.parse_args()

    root = ROOT
    report = build_identity_mapping(root)
    summary = report["summary"]
    print(f"Companies: {summary['company_count']}")
    print(f"Resolved: {summary['resolved_company_count']}")
    print(f"Partial: {summary['partial_company_count']}")
    print(f"Securities: {summary['security_count']}")
    print(f"Symbol collisions: {summary['symbol_collision_count']}")
    print(f"Yahoo cached symbols: {summary['yahoo_cached_symbol_count']}")
    print(f"Yahoo canonical symbols: {summary['yahoo_canonical_symbol_count']}")
    print(f"Yahoo per-symbol cache: {summary['yahoo_per_symbol_cache_count']}")
    print(f"Yahoo unmapped symbols: {summary['yahoo_unmapped_symbol_count']}")

    if args.write:
        write_identity_mapping(report, root / args.output, root / args.diagnostic)
        print(f"Output: {args.output}")
        print(f"Diagnostic: {args.diagnostic}")

    if args.strict and (
        summary["symbol_collision_count"] > 0
        or summary["yahoo_unmapped_symbol_count"] > 0
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
