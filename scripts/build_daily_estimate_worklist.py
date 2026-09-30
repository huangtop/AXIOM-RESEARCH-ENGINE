#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Select the daily missing/stale Yahoo estimate batch"
    )
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--ttl-days", type=int, default=30)
    parser.add_argument(
        "--severe-stale-days",
        type=int,
        default=60,
        help="Age threshold that promotes severely stale snapshots ahead of the normal queue",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Include fresh companies so a full priority batch is actually refetched",
    )
    parser.add_argument(
        "--priority-symbols",
        type=Path,
        help="JSON completion set placed ahead of the general daily queue",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-empty", action="store_true")
    args = parser.parse_args()

    if args.limit < 1 or args.ttl_days < 1 or args.severe_stale_days < 1:
        parser.error("--limit, --ttl-days and --severe-stale-days must be positive")
    if args.severe_stale_days < args.ttl_days:
        parser.error("--severe-stale-days must be >= --ttl-days")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=args.ttl_days)
    severe_cutoff = now - timedelta(days=args.severe_stale_days)

    catalog = json.loads(
        Path("data/generated/publication_gate/company_catalog.json").read_text(
            encoding="utf-8"
        )
    )
    snapshots = (
        json.loads(
            Path("data/generated/company/yahoo_company_snapshot.json").read_text(
                encoding="utf-8"
            )
        ).get("symbols")
        or {}
    )

    def snapshot_stamp(row: dict[str, Any]) -> datetime | None:
        value = row.get("fetched_at") or row.get("last_refresh")
        if not value:
            return None
        try:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc)

    def schema_incomplete(row: dict[str, Any]) -> bool:
        # Key presence, rather than a non-null value, marks the normalized PEG
        # migration complete because Yahoo may legitimately have no +1y growth.
        if "normalized_peg_growth" not in row:
            return True
        if "normalized_peg_growth_basis" not in row:
            return True

        annual = row.get("annual_estimates")
        if not isinstance(annual, dict) or not all(
            isinstance(annual.get(basis), dict)
            for basis in ("CURRENT_FY", "NEXT_FY")
        ):
            return True

        if not isinstance(row.get("current_fiscal_year"), int):
            return True

        return False

    def needs_refresh(symbol: str) -> bool:
        row = snapshots.get(symbol) or {}

        if schema_incomplete(row):
            return True

        stamp = snapshot_stamp(row)
        if stamp is None:
            return True

        return stamp < cutoff

    def queue_age_key(row: dict[str, Any]) -> float:
        stamp = snapshot_stamp(row)
        if stamp is None:
            # Missing or malformed timestamps are effectively older than any
            # valid checkpoint and must not starve behind parseable snapshots.
            return float("-inf")
        return stamp.timestamp()

    def candidate(
        symbol: str,
        *,
        tech_tier: int,
        valuation_tier: int,
    ) -> tuple[str, bool, bool, int, int, float]:
        row = snapshots.get(symbol) or {}
        stamp = snapshot_stamp(row)

        severe_stale = stamp is None or stamp < severe_cutoff
        incomplete = schema_incomplete(row)

        return (
            symbol,
            severe_stale,
            incomplete,
            tech_tier,
            valuation_tier,
            queue_age_key(row),
        )

    candidates: list[tuple[str, bool, bool, int, int, float]] = []
    catalog_symbols: set[str] = set()

    for company in catalog.get("companies") or []:
        symbol = str(company.get("ticker") or "").strip().upper()
        if not symbol or (not args.force and not needs_refresh(symbol)):
            continue

        catalog_symbols.add(symbol)

        axes = company.get("scope_axes") or {}
        scope = str(company.get("research_scope") or "contextual")

        tech_tier = (
            0
            if axes.get("news_ai")
            else {"core": 1, "coverage": 2, "candidate": 3}.get(scope, 4)
        )
        valuation_tier = {
            "unavailable": 0,
            "partial": 1,
            "ready": 2,
        }.get(str(company.get("valuation_status")), 3)

        candidates.append(
            candidate(
                symbol,
                tech_tier=tech_tier,
                valuation_tier=valuation_tier,
            )
        )

    priority: set[str] = set()

    if args.priority_symbols:
        priority = {
            str(value).strip().upper()
            for value in json.loads(
                args.priority_symbols.read_text(encoding="utf-8")
            ).get("symbols")
            or []
            if str(value).strip()
        }

        for symbol in sorted(priority - catalog_symbols):
            if args.force or needs_refresh(symbol):
                candidates.append(
                    candidate(
                        symbol,
                        tech_tier=0,
                        valuation_tier=0,
                    )
                )

    # Queue contract:
    #
    #   frontier priority
    #   -> severe stale (> severe_stale_days)
    #   -> schema incomplete
    #   -> tech tier
    #   -> valuation tier
    #   -> oldest fetched_at
    #   -> ticker
    #
    # The age key is deliberately ahead of ticker so equal-tier companies make
    # forward progress instead of repeatedly selecting alphabetically early names.
    ordered = sorted(
        candidates,
        key=lambda row: (
            0 if row[0] in priority else 1,
            0 if row[1] else 1,
            0 if row[2] else 1,
            row[3],
            row[4],
            row[5],
            row[0],
        ),
    )

    symbols = [row[0] for row in ordered[: args.limit]]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "\n".join(symbols) + ("\n" if symbols else ""),
        encoding="utf-8",
    )

    severe_count = sum(1 for row in candidates if row[1])
    incomplete_count = sum(1 for row in candidates if row[2])

    print(
        {
            "eligible_missing_or_stale": len(candidates),
            "severe_stale": severe_count,
            "schema_incomplete": incomplete_count,
            "selected": len(symbols),
            "limit": args.limit,
            "ttl_days": args.ttl_days,
            "severe_stale_days": args.severe_stale_days,
        }
    )

    if not symbols and not args.allow_empty:
        raise SystemExit("no missing or stale estimate symbols selected")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
