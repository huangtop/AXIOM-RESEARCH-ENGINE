#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.automation import run_scheduled_automation


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AXIOM V030.8.3 automation under scheduler safety controls")
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--automation-config", default="config/automation.v030.8.3.json")
    parser.add_argument("--scheduler-config", default="config/automation_scheduler.v030.8.3.json")
    parser.add_argument("--output-dir", default="data/generated/automation")
    parser.add_argument("--lock-path", default="data/generated/automation/automation_scheduler.lock")
    parser.add_argument("--trigger", choices=["manual", "cron", "launchd", "github_actions"], default="manual")
    parser.add_argument("--trigger-id")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.repository_root).resolve()
    scheduler_config = json.loads((root / args.scheduler_config).read_text(encoding="utf-8"))
    command = [
        sys.executable,
        "scripts/run_automation.py",
        "--config", args.automation_config,
    ]
    if args.strict:
        command.append("--strict")
    if args.dry_run:
        command.append("--dry-run")
    report = run_scheduled_automation(
        root,
        command,
        root / args.output_dir,
        root / args.lock_path,
        trigger=args.trigger,
        trigger_id=args.trigger_id,
        timeout_seconds=int(scheduler_config.get("timeout_seconds", 7200)),
        stale_lock_seconds=int(scheduler_config.get("stale_lock_seconds", 10800)),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"completed", "skipped_locked"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
