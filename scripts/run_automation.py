#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.automation import run_automation


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the AXIOM V030.8.1 automation orchestrator")
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--config", default="config/automation.v030.8.1.json")
    parser.add_argument("--output-dir", default="data/generated/automation")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--continue-on-failure", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.repository_root).resolve()
    config_path = root / args.config
    config = json.loads(config_path.read_text(encoding="utf-8"))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output_dir = root / args.output_dir
    report = run_automation(
        root,
        config.get("stages", []),
        output_dir / f"automation_run_{stamp}.json",
        strict=args.strict,
        continue_on_failure=args.continue_on_failure,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"completed", "completed_with_warnings", "planned"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
