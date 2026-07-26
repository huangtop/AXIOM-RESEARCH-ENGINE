#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from axiom_engine.automation import plan_incremental_refresh

def main() -> int:
    p = argparse.ArgumentParser(description="Plan AXIOM V030.8.4 incremental refresh")
    p.add_argument("--repository-root", default=".")
    p.add_argument("--config", default="config/incremental_refresh.v030.8.4.json")
    p.add_argument("--output-dir", default="data/generated/automation")
    p.add_argument("--force-full", action="store_true")
    p.add_argument("--force-run", action="store_true")
    a = p.parse_args()
    root = Path(a.repository_root).resolve()
    config = json.loads((root / a.config).read_text(encoding="utf-8"))
    report = plan_incremental_refresh(root, config, root / a.output_dir, force_full=a.force_full, force_run=a.force_run)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
