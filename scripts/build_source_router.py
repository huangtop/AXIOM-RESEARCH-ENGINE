#!/usr/bin/env python3
from __future__ import annotations
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/'src') not in sys.path: sys.path.insert(0,str(ROOT/'src'))
from axiom_engine.source_router import build_source_router,write_source_router

def main()->int:
 p=argparse.ArgumentParser(description='Build V030.11.2 SEC-first financial source router')
 p.add_argument('--write',action='store_true'); p.add_argument('--strict',action='store_true')
 p.add_argument('--timeline',default='data/generated/financial_timeline/financial_timeline.json')
 p.add_argument('--yahoo',default='data/generated/company/yahoo_company_snapshot.json')
 p.add_argument('--output',default='data/generated/source_router/financial_source_snapshot.json')
 p.add_argument('--diagnostic',default='data/generated/source_router/source_router_diagnostic.json')
 a=p.parse_args(); r=build_source_router(ROOT,timeline_path=a.timeline,yahoo_path=a.yahoo); s=r['summary']
 print(f"Companies: {s['company_count']}"); print(f"Yahoo cached symbols: {s['yahoo_cached_symbol_count']}"); print(f"Yahoo matched companies: {s['yahoo_matched_company_count']}")
 print(f"SEC selected metrics: {s['provider_metric_counts']['sec_companyfacts']}"); print(f"Yahoo fallback metrics: {s['provider_metric_counts']['yahoo_finance']}"); print(f"Missing metrics: {s['missing_metric_count']}")
 if a.write: write_source_router(r,ROOT/a.output,ROOT/a.diagnostic); print(f"Output: {a.output}"); print(f"Diagnostic: {a.diagnostic}")
 return 1 if a.strict and s['company_count']==0 else 0
if __name__=='__main__': raise SystemExit(main())
