#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from axiom_engine.company_profile_v2.batch import (
    CENSUS_OUTPUT,
    build_company_profile_census,
    write_company_profile_census,
)

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "V2.6 full-market Company Profile census "
            "over canonical business evidence."
        )
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help=(
            "Optional ticker subset for a smoke run. "
            "Omit to scan the full evidence universe."
        ),
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=100,
        help="Write a checkpoint every N processed companies. Default: 100.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Print progress every N processed companies. Default: 25.",
    )
    parser.add_argument(
        "--output",
        default=str(CENSUS_OUTPUT),
        help="Census JSON output path relative to repo root.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = ROOT / Path(args.output)

    def progress(
        position: int,
        total: int,
        symbol: str,
        generated: int,
        failed: int,
    ) -> None:
        every = max(int(args.progress_every), 1)
        if position == 1 or position == total or position % every == 0:
            print(
                "[V2.6 census] "
                f"{position}/{total} "
                f"symbol={symbol} "
                f"generated={generated} "
                f"failed={failed}",
                flush=True,
            )

    report = build_company_profile_census(
        ROOT,
        symbols=args.symbols,
        checkpoint_every=max(int(args.checkpoint_every), 0),
        checkpoint_path=output,
        progress_callback=progress,
    )

    path = write_company_profile_census(
        ROOT,
        report,
        output_path=output,
    )

    summary = report.get("summary") or {}

    print()
    print("=== V2.6 Company Profile Census ===")
    print("Evidence companies:       ", summary.get("evidence_company_count"))
    print("Resolved symbols:         ", summary.get("resolved_unique_symbol_count"))
    print("Attempted:                ", summary.get("attempted_company_count"))
    print("Generated:                ", summary.get("generated_company_count"))
    print("Build failed:             ", summary.get("build_failed_company_count"))
    print("Production ready:         ", summary.get("production_ready_count"))
    print("Not production ready:     ", summary.get("not_production_ready_count"))

    print()
    print(
        "Failure reasons:",
        json.dumps(
            report.get("failure_reasons") or {},
            ensure_ascii=False,
            sort_keys=True,
        ),
    )
    print(
        "Readiness reasons:",
        json.dumps(
            report.get("readiness_reasons") or {},
            ensure_ascii=False,
            sort_keys=True,
        ),
    )

    print()
    print("Census report:", path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())