#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from axiom_engine.valuation_readiness import validate_valuation_readiness

p=argparse.ArgumentParser(description="Validate V030.3 valuation readiness artifacts.")
p.add_argument("--repository-root", default=".")
p.add_argument("--population-dir", default="data/universe")
p.add_argument("--output-dir", default="data/generated/valuation_readiness")
p.add_argument("--strict", action="store_true")
a=p.parse_args()
result=validate_valuation_readiness(repository_root=a.repository_root,population_dir=a.population_dir,output_dir=a.output_dir,strict=a.strict)
print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(0 if result["valid"] else 1)
