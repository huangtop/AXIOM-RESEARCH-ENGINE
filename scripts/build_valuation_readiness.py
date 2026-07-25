#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from axiom_engine.valuation_readiness import build_valuation_readiness

p=argparse.ArgumentParser(description="Build V030.3 valuation readiness for the full canonical universe.")
p.add_argument("--repository-root", default=".")
p.add_argument("--population-dir", default="data/universe")
p.add_argument("--output-dir", default="data/generated/valuation_readiness")
p.add_argument("--strict", action="store_true")
p.add_argument("--write", action="store_true")
a=p.parse_args()
result=build_valuation_readiness(repository_root=a.repository_root,population_dir=a.population_dir,output_dir=a.output_dir,write=a.write,strict=a.strict)
print(json.dumps(result,ensure_ascii=False,indent=2))
