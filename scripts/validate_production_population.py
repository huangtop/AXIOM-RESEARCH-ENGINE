#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/"src") not in sys.path: sys.path.insert(0,str(ROOT/"src"))
from axiom_engine.production_population import validate_population
p=argparse.ArgumentParser(); p.add_argument("--repository-root",default="."); p.add_argument("--population-dir",default="data/universe"); p.add_argument("--output-dir",default="data/generated/production_population"); p.add_argument("--strict",action="store_true"); a=p.parse_args()
root=Path(a.repository_root).resolve(); out=Path(a.output_dir); out=out if out.is_absolute() else root/out
result=validate_population(root,Path(a.population_dir),out); print(json.dumps(result,ensure_ascii=False,indent=2))
if a.strict and not result["valid"]: raise SystemExit(1)
