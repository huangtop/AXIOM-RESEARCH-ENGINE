#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path: sys.path.insert(0, str(ROOT / "src"))
from axiom_engine.production_population import build_population, write_population

p=argparse.ArgumentParser()
p.add_argument("--repository-root", default=".")
p.add_argument("--population-dir", default="data/universe")
p.add_argument("--manifest", default="data/generated/population_manifest/population_manifest.json")
p.add_argument("--output-dir", default="data/generated/production_population")
p.add_argument("--write", action="store_true")
p.add_argument("--strict", action="store_true")
a=p.parse_args()
root=Path(a.repository_root).resolve()
result=build_population(root, Path(a.population_dir), Path(a.manifest), strict=a.strict)
out=Path(a.output_dir); out=out if out.is_absolute() else root/out
if a.write: write_population(result,out)
payload=dict(result["summary"], output_dir=str(out), dry_run=not a.write, valid=not result["diagnostics"]["errors"])
print(json.dumps(payload,ensure_ascii=False,indent=2))
