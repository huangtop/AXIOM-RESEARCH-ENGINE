#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from axiom_engine.company_overview import (
    build_company_overviews,
    write_company_overviews,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """
    Rebuild canonical Company Overview for the full eligible market universe.

    Production contract:
    - Do not pre-filter by research eligibility.
    - Do not pre-filter to companies already having theme+sector inference.
    - Consume the complete knowledge-inference population.
    - Recompute historical automatic classifications instead of replaying
      stale published locks.
    - Curated overrides remain authoritative because they are applied by
      build_company_overviews() from company_overview.v031c.6.json.
    - The writer replaces the canonical full snapshot and removes stale
      per-company overview files.
    """
    report = build_company_overviews(
        ROOT,
        respect_existing_locks=False,
    )

    write_company_overviews(
        report,
        ROOT / "data/generated/company_overview",
        preserve_existing=False,
    )

    summary = report["summary"]

    print(
        "=== Full-Market Company Overview Rebuild ==="
    )
    print(
        f"Companies:                       "
        f"{summary['company_count']}"
    )
    print(
        f"Classified:                      "
        f"{summary['classified_count']}"
    )
    print(
        f"Evidence available, unclassified:"
        f" {summary['evidence_available_unclassified_count']}"
    )
    print(
        f"Awaiting business evidence:      "
        f"{summary['awaiting_evidence_count']}"
    )
    print(
        "Output: data/generated/company_overview"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())