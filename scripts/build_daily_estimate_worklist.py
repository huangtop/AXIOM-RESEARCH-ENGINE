#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Select the daily missing/stale Yahoo estimate batch")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--ttl-days", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.limit < 1 or args.ttl_days < 1:
        parser.error("--limit and --ttl-days must be positive")

    catalog = json.loads(Path("data/generated/publication_gate/company_catalog.json").read_text())
    snapshots = json.loads(Path("data/generated/company/yahoo_company_snapshot.json").read_text()).get("symbols") or {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.ttl_days)

    def needs_refresh(symbol: str) -> bool:
        row = snapshots.get(symbol) or {}
        value = row.get("fetched_at") or row.get("last_refresh")
        if not value:
            return True
        try:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return stamp < cutoff
        except ValueError:
            return True

    candidates = []
    for company in catalog.get("companies") or []:
        symbol = str(company.get("ticker") or "").strip().upper()
        if not symbol or not needs_refresh(symbol):
            continue
        axes = company.get("scope_axes") or {}
        scope = str(company.get("research_scope") or "contextual")
        tech_tier = 0 if axes.get("news_ai") else {"core": 1, "coverage": 2, "candidate": 3}.get(scope, 4)
        valuation_tier = {"unavailable": 0, "partial": 1, "ready": 2}.get(str(company.get("valuation_status")), 3)
        candidates.append((tech_tier, valuation_tier, symbol))
    symbols = [row[2] for row in sorted(candidates)[: args.limit]]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(symbols) + ("\n" if symbols else ""), encoding="utf-8")
    print({"eligible_missing_or_stale": len(candidates), "selected": len(symbols), "limit": args.limit})
    if not symbols:
        raise SystemExit("no missing or stale estimate symbols selected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
