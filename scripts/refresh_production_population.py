#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.production_refresh import run_refresh


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the canonical AXIOM production population refresh pipeline")
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--config", default="config/production_refresh.v030.6.5.json")
    parser.add_argument("--output", default="data/generated/production_refresh/refresh_report.json")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    root = Path(args.repository_root).resolve()
    config = json.loads((root / args.config).read_text(encoding="utf-8"))
    commands = config.get("commands", [])
    if args.strict:
        for spec in commands:
            if "--strict" not in spec["argv"] and spec.get("supports_strict", True):
                spec["argv"].append("--strict")
    report = run_refresh(root, commands, root / args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
