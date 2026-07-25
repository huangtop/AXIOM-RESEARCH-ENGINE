#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; SRC=ROOT/"src"
if str(SRC) not in sys.path: sys.path.insert(0,str(SRC))
from axiom_engine.population_discovery import validate_manifest

def main()->int:
 p=argparse.ArgumentParser(); p.add_argument("--repository-root",default="."); p.add_argument("--output-dir",default="data/generated/population_manifest"); p.add_argument("--strict",action="store_true"); a=p.parse_args()
 root=Path(a.repository_root).resolve(); path=root/a.output_dir/"population_manifest.json"
 if not path.exists(): print(json.dumps({"valid":False,"errors":["manifest_missing"],"path":str(path)},indent=2)); return 2
 result=validate_manifest(json.loads(path.read_text()),root); result["manifest_path"]=str(path); print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if result["valid"] else 2
if __name__=="__main__": raise SystemExit(main())
