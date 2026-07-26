#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from axiom_engine.production_refresh import validate_provider_batch_response

def main()->int:
 p=argparse.ArgumentParser(); p.add_argument('--request',required=True); p.add_argument('--response',required=True); p.add_argument('--output'); p.add_argument('--strict',action='store_true'); a=p.parse_args()
 request=json.loads(Path(a.request).read_text(encoding='utf-8')); response=json.loads(Path(a.response).read_text(encoding='utf-8'))
 result=validate_provider_batch_response(response,request)
 text=json.dumps(result,ensure_ascii=False,indent=2); print(text)
 if a.output: Path(a.output).write_text(text,encoding='utf-8')
 return 2 if a.strict and not result['valid'] else 0
if __name__=='__main__': raise SystemExit(main())
