#!/usr/bin/env python3
from __future__ import annotations
import argparse, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path: sys.path.insert(0, str(ROOT / "src"))
from axiom_engine.financial_timeline import build_financial_timeline, write_financial_timeline

def main() -> int:
    p=argparse.ArgumentParser(description="Build V030.11.1 financial timeline")
    p.add_argument("--write",action="store_true"); p.add_argument("--strict",action="store_true")
    p.add_argument("--input",default="data/generated/financial_bridge/canonical_financial_snapshot.json")
    p.add_argument("--output",default="data/generated/financial_timeline/financial_timeline.json")
    p.add_argument("--diagnostic",default="data/generated/financial_timeline/financial_timeline_diagnostic.json")
    p.add_argument("--as-of")
    a=p.parse_args(); r=build_financial_timeline(ROOT,financial_snapshot_path=a.input,as_of_date=a.as_of); s=r["summary"]
    print(f"Companies: {s['company_count']}"); print(f"Annual periods: {s['annual_period_count']}"); print(f"Quarterly periods: {s['quarterly_period_count']}")
    print(f"TTM four-quarter: {s['ttm_state_counts'].get('four_quarter_sum',0)}"); print(f"TTM annual proxy: {s['ttm_state_counts'].get('annual_proxy',0)}"); print(f"TTM missing: {s['ttm_state_counts'].get('missing',0)}")
    print(f"Fresh: {s['freshness_counts'].get('fresh',0)}"); print(f"Current: {s['freshness_counts'].get('current',0)}"); print(f"Stale: {s['freshness_counts'].get('stale',0)}")
    print(f"Invalid periods: {s['invalid_period_count']}"); print(f"Future periods: {s['future_period_count']}")
    if a.write: write_financial_timeline(r,ROOT/a.output,ROOT/a.diagnostic); print(f"Output: {a.output}"); print(f"Diagnostic: {a.diagnostic}")
    return 1 if a.strict and s['invalid_period_count'] else 0
if __name__=='__main__': raise SystemExit(main())
