#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.bridge_qa import build_bridge_qa, write_bridge_qa


def main() -> int:
    parser = argparse.ArgumentParser(description="Run V030.11.3 bridge quality gates")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--identity", default="data/generated/identity/company_identity_map.json")
    parser.add_argument("--bridge", default="data/generated/financial_bridge/canonical_financial_snapshot.json")
    parser.add_argument("--timeline", default="data/generated/financial_timeline/financial_timeline.json")
    parser.add_argument("--router", default="data/generated/source_router/financial_source_snapshot.json")
    parser.add_argument("--output", default="data/generated/bridge_qa/bridge_qa_report.json")
    args = parser.parse_args()

    report = build_bridge_qa(ROOT, identity_path=args.identity, bridge_path=args.bridge, timeline_path=args.timeline, router_path=args.router)
    summary = report["summary"]
    print(f"Status: {summary['status']}")
    print(f"Identity companies: {summary['identity_company_count']}")
    print(f"Bridge companies: {summary['bridge_company_count']}")
    print(f"Timeline companies: {summary['timeline_company_count']}")
    print(f"Router companies: {summary['router_company_count']}")
    print(f"Bridge facts checked: {summary['bridge_fact_count']}")
    print(f"Routed metrics checked: {summary['routed_metric_count']}")
    print(f"Missing metrics checked: {summary['missing_metric_count']}")
    print(f"Critical issues: {summary['critical_issue_count']}")
    print(f"Warnings: {summary['warning_issue_count']}")
    for name, state in report["gates"].items():
        print(f"Gate {name}: {state}")
    if args.write:
        write_bridge_qa(report, ROOT / args.output)
        print(f"Output: {args.output}")
    return 1 if args.strict and report["status"] != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
