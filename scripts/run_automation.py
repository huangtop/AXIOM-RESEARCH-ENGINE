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

from axiom_engine.automation import load_automation_state, run_automation


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the AXIOM V030.8.2 automation state machine")
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--config", default="config/automation.v030.8.2.json")
    parser.add_argument("--output-dir", default="data/generated/automation")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--continue-on-failure", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", metavar="STATE_JSON", help="Resume an existing state file")
    parser.add_argument("--resume-latest", action="store_true", help="Resume latest_state.json")
    parser.add_argument("--retry-failed", action="store_true", help="Re-run failed stages while preserving completed stages")
    parser.add_argument("--skip-stage", action="append", default=[], metavar="NAME")
    args = parser.parse_args()

    root = Path(args.repository_root).resolve()
    config = json.loads((root / args.config).read_text(encoding="utf-8"))
    output_dir = root / args.output_dir
    resume_path: Path | None = None
    if args.resume and args.resume_latest:
        parser.error("use only one of --resume or --resume-latest")
    if args.resume:
        resume_path = Path(args.resume)
        if not resume_path.is_absolute():
            resume_path = root / resume_path
    elif args.resume_latest:
        resume_path = output_dir / "latest_state.json"
    resume_state = load_automation_state(resume_path) if resume_path else None

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if resume_state:
        run_token = resume_state["run_id"].split(":", 1)[-1]
        output_path = output_dir / f"automation_run_{run_token}_resume_{stamp}.json"
        state_path = resume_path
    else:
        output_path = output_dir / f"automation_run_{stamp}.json"
        state_path = output_dir / f"automation_state_{stamp}.json"

    report = run_automation(
        root, config.get("stages", []), output_path,
        strict=args.strict, continue_on_failure=args.continue_on_failure,
        dry_run=args.dry_run, state_path=state_path, resume_state=resume_state,
        retry_failed=args.retry_failed, skip_stages=args.skip_stage,
    )
    latest_state = output_dir / "latest_state.json"
    latest_state.write_text(Path(report["state_path"]).read_text(encoding="utf-8"), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"completed", "completed_with_warnings", "planned"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
