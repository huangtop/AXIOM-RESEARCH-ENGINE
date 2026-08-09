#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a production refresh summary")
    parser.add_argument("--before", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    coverage = load(Path("data/generated/full_market_coverage/full_market_coverage.json")).get("summary") or {}
    before = (load(args.before).get("summary") or {}) if args.before else {}
    financial = load(Path("data/generated/canonical_financial_population/manifest.json")).get("summary") or {}
    market = load(Path("data/generated/provider_cache/yahoo/daily_close_refresh_report.json"))
    estimate = load(Path("data/generated/provider_cache/yahoo/company_snapshot_refresh_report.json"))
    statuses = coverage.get("status_counts") or {}
    old_statuses = before.get("status_counts") or {}

    def change(name: str) -> str:
        current = int(statuses.get(name) or 0)
        return f"{current} ({current - int(old_statuses.get(name) or current):+d})"

    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    lines = [
        "## Daily production refresh summary",
        "",
        f"- Workflow: {os.environ.get('GITHUB_WORKFLOW', 'local')}",
        f"- Commit SHA: `{sha}`",
        f"- Stock prices: succeeded {market.get('succeeded', 'n/a')} / failed {market.get('failed', 'n/a')} / requested {market.get('requested', 'n/a')}",
        f"- Financial data: {financial.get('companies_with_financial_facts', coverage.get('financial_present_company_count', 'n/a'))} companies present",
        f"- Estimates: present {coverage.get('estimate_present_company_count', 'n/a')}; batch succeeded {estimate.get('succeeded', 'n/a')} / failed {estimate.get('failed', 'n/a')}",
        f"- Valuation (all {coverage.get('company_count', 'n/a')} companies): ready {change('ready')}, partial {change('partial')}, unavailable {change('unavailable')}",
    ]
    text = "\n".join(lines) + "\n"
    print(text)
    destination = args.output or (Path(os.environ["GITHUB_STEP_SUMMARY"]) if os.environ.get("GITHUB_STEP_SUMMARY") else None)
    if destination:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
