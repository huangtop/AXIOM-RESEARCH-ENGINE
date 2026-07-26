#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path: sys.path.insert(0, str(ROOT / "src"))
from axiom_engine.production_source_expansion import expand_production_sources, write_expansion_outputs

def main() -> int:
    p=argparse.ArgumentParser(description="Normalize provider data into canonical production sources")
    p.add_argument("--repository-root", default=".")
    p.add_argument("--population-dir", default="data/universe")
    p.add_argument("--config", default="config/production_source_expansion.v030.6.1.json")
    p.add_argument("--output-dir", default="data/generated/production_sources")
    p.add_argument("--write", action="store_true")
    p.add_argument("--strict", action="store_true")
    a=p.parse_args(); root=Path(a.repository_root).resolve()
    cfg_path=root/a.config; config=json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    payload=expand_production_sources(root, Path(a.population_dir), config)
    if a.write: write_expansion_outputs(payload, root/a.output_dir)
    summary={k:v for k,v in payload.items() if k not in {"outputs","rejected_records"}}
    summary["rejected_record_count"]=len(payload["rejected_records"])
    summary["output_dir"]=str((root/a.output_dir).resolve()); summary["dry_run"]=not a.write
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if a.strict and any(x["rejected_rows"] for x in payload["source_summaries"]): return 2
    return 0
if __name__ == "__main__": raise SystemExit(main())
