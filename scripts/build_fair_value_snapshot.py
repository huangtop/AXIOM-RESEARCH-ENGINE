#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
from axiom_engine.fair_value_snapshot import FairValueSnapshotError,build_fair_value_snapshot,write_fair_value_snapshot

def main():
 p=argparse.ArgumentParser(description="Build Production Fair Value Beta snapshot")
 p.add_argument("--root",default="."); p.add_argument("--config",default="config/fair_value_snapshot.v030.14.0.json"); p.add_argument("--write",action="store_true"); p.add_argument("--strict",action="store_true"); a=p.parse_args(); root=Path(a.root).resolve(); cfg=json.loads((root/a.config).read_text())
 try: report,diag=build_fair_value_snapshot(root,valuation_input_path=cfg["valuation_input"],historical_benchmark_path=cfg["historical_benchmark"],target_company_count=int(cfg.get("target_company_count",100)),dcf_policy=cfg.get("dcf"))
 except FairValueSnapshotError as e: print(f"ERROR: {e}"); return 2
 s=report["summary"]
 print(f"Companies: {s['company_count']} / target {s['target_company_count']}")
 print(f"Historical ready: {s['model_ready_counts']['historical']}")
 print(f"Peer ready: {s['model_ready_counts']['peer']}")
 print(f"DCF ready: {s['model_ready_counts']['dcf']}")
 print(f"Composite ready: {s['composite_ready_count']}")
 print(f"Valuation cards ready: {s['valuation_card_ready_count']}")
 if a.write:
  out=root/cfg["snapshot_output"]; dg=root/cfg["diagnostic_output"]; write_fair_value_snapshot(report,diag,out,dg); print(f"Output: {out.relative_to(root)}"); print(f"Diagnostic: {dg.relative_to(root)}")
 if a.strict and (not s["target_count_met"] or s["valuation_card_ready_count"]<s["target_company_count"]): return 1
 return 0
if __name__=="__main__": raise SystemExit(main())
