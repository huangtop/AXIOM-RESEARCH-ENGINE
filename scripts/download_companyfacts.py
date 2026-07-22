#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

from axiom_engine.sec_financial_connector import SECConnectorConfig, SECFinancialConnector


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download a SEC XBRL Company Facts snapshot.")
    parser.add_argument("--cik", required=True, help="SEC CIK, with or without zero padding")
    parser.add_argument("--output", type=Path, required=True, help="Output JSON path")
    parser.add_argument(
        "--user-agent",
        default=os.environ.get("SEC_USER_AGENT"),
        help="Descriptive SEC User-Agent; defaults to SEC_USER_AGENT",
    )
    parser.add_argument("--cache-dir", type=Path, help="Optional connector cache directory")
    parser.add_argument("--refresh", action="store_true", help="Ignore a fresh cached response")
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.user_agent:
        raise SystemExit("--user-agent or SEC_USER_AGENT is required")
    connector = SECFinancialConnector(
        SECConnectorConfig(
            user_agent=args.user_agent,
            timeout_seconds=args.timeout,
            cache_directory=args.cache_dir,
        )
    )
    facts = connector.company_facts(args.cik, refresh=args.refresh)
    target = facts.write_json(args.output)
    print(f"CIK: {facts.cik}")
    print(f"Entity: {facts.entity_name}")
    print(f"Facts: {facts.fact_count}")
    print(f"Observations: {facts.observation_count}")
    print(f"Saved: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
