#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/'src') not in sys.path: sys.path.insert(0,str(ROOT/'src'))
from axiom_engine.production_refresh import build_provider_delivery_reconciliation
def load(path,default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
def main():
    p=argparse.ArgumentParser(); p.add_argument('--repository-root',default='.'); p.add_argument('--contracts-dir',default='data/generated/production_refresh/provider_contracts'); p.add_argument('--accepted-dir',default='data/provider_intake/accepted'); p.add_argument('--receipts-dir',default='data/provider_intake/receipts'); p.add_argument('--processed-dir',default='data/provider_intake/processed'); p.add_argument('--output',default='data/generated/production_refresh/provider_delivery_reconciliation.json'); p.add_argument('--strict',action='store_true'); a=p.parse_args()
    root=Path(a.repository_root).resolve(); c=root/a.contracts_dir; accepted=root/a.accepted_dir; receipts_dir=root/a.receipts_dir; processed=root/a.processed_dir
    aggregate=load(c/'provider_batch_contracts.json',{}); batches=aggregate.get('batches',{})
    if not batches:
        for layer in ('financial','market','estimate'): batches[layer]=load(c/f'{layer}_batch_request.json',{})
    ledgers={layer:load(accepted/f'{layer}_facts.json',[]) for layer in ('financial','market','estimate')}
    receipts=[load(p,{}) for p in receipts_dir.glob('*.json')] if receipts_dir.exists() else []
    dup={layer:len(list(processed.glob(f'{layer}_batch_response.duplicate.*.json'))) if processed.exists() else 0 for layer in ('financial','market','estimate')}
    report=build_provider_delivery_reconciliation(batches,ledgers,receipts,dup)
    out=root/a.output; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,indent=2))
    return 2 if a.strict and report['request_count']==0 else 0
if __name__=='__main__': raise SystemExit(main())
