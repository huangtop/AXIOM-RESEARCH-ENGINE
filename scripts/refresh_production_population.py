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
    parser.add_argument("--config", default="config/production_refresh.v030.7.2.json")
    parser.add_argument("--output", default="data/generated/production_refresh/refresh_report.json")
    parser.add_argument("--targets-output", default="data/generated/production_refresh/overlap_targets.json")
    parser.add_argument("--worklists-output-dir", default="data/generated/production_refresh/provider_worklists")
    parser.add_argument("--contracts-output-dir", default="data/generated/production_refresh/provider_contracts")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--require-ready", action="store_true", help="Return exit code 3 when readiness gates are blocked")
    args = parser.parse_args()

    root = Path(args.repository_root).resolve()
    config = json.loads((root / args.config).read_text(encoding="utf-8"))
    commands = config.get("commands", [])
    if args.strict:
        for spec in commands:
            if "--strict" not in spec["argv"] and spec.get("supports_strict", True):
                spec["argv"].append("--strict")
    report = run_refresh(
        root,
        commands,
        root / args.output,
        readiness_policy=config.get("readiness_policy"),
        overlap_targeting=config.get("overlap_targeting"),
        targets_output_path=root / args.targets_output,
        worklists_output_dir=root / args.worklists_output_dir,
        max_worklist_rows_per_layer=int(config.get("provider_worklists", {}).get("max_rows_per_layer", 200)),
        contracts_output_dir=root / args.contracts_output_dir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "completed":
        return 2
    if args.require_ready and report["readiness_assessment"]["status"] != "qualified":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
