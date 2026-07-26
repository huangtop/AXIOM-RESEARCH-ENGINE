#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/'src') not in sys.path: sys.path.insert(0,str(ROOT/'src'))
from axiom_engine.production_refresh import import_provider_batch_response, merge_intake_ledger_into_production_source

def rows(path: Path):
    if not path.exists(): return []
    obj=json.loads(path.read_text(encoding='utf-8'))
    if isinstance(obj,list): return [x for x in obj if isinstance(x,dict)]
    if isinstance(obj,dict):
        for key in ('records','rows','data'):
            if isinstance(obj.get(key),list): return [x for x in obj[key] if isinstance(x,dict)]
    return []

def main():
    p=argparse.ArgumentParser(description='Validate and import one provider batch response into the persistent intake ledger and canonical production source')
    p.add_argument('--request',required=True); p.add_argument('--response',required=True)
    p.add_argument('--repository-root',default='.')
    p.add_argument('--ledger'); p.add_argument('--production-output'); p.add_argument('--report')
    p.add_argument('--strict',action='store_true')
    a=p.parse_args(); root=Path(a.repository_root).resolve()
    request=json.loads((root/a.request).read_text(encoding='utf-8'))
    response=json.loads((root/a.response).read_text(encoding='utf-8'))
    layer=str(request.get('target_layer') or '')
    ledger=root/(a.ledger or f'data/provider_intake/accepted/{layer}_facts.json')
    production=root/(a.production_output or f'data/generated/production_sources/{layer}_facts.json')
    report_path=root/(a.report or f'data/generated/production_refresh/provider_imports/{layer}_import_report.json')
    result=import_provider_batch_response(response,request,rows(ledger))
    report_path.parent.mkdir(parents=True,exist_ok=True); report_path.write_text(json.dumps({k:v for k,v in result.items() if k not in ('ledger_rows','canonical_rows')},ensure_ascii=False,indent=2),encoding='utf-8')
    if result['valid']:
        ledger.parent.mkdir(parents=True,exist_ok=True); ledger.write_text(json.dumps(result['ledger_rows'],ensure_ascii=False,indent=2),encoding='utf-8')
        production.parent.mkdir(parents=True,exist_ok=True); production.write_text(json.dumps(merge_intake_ledger_into_production_source(result['ledger_rows'],rows(production)),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('ledger_rows','canonical_rows')},ensure_ascii=False,indent=2))
    return 0 if result['valid'] or not a.strict else 2
if __name__=='__main__': raise SystemExit(main())
