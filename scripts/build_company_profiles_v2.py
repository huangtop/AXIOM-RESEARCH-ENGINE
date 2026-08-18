#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT / "src") not in sys.path:
    sys.path.insert(
        0,
        str(ROOT / "src"),
    )


from axiom_engine.company_profile_v2.batch import (  # noqa: E402
    CompanyProfileBatchError,
    build_company_profile_batch,
    write_company_profile_batch,
)


def _public_report(
    report: dict,
) -> dict:
    return {
        key: value
        for key, value
        in report.items()
        if not str(key).startswith(
            "_"
        )
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build production Company Profile V2.5 "
            "for a published or evidence-backed cohort."
        )
    )

    parser.add_argument(
        "--scope",
        choices=(
            "published",
            "evidence",
        ),
        default="published",
        help=(
            "published: migrate the current production "
            "company_analysis cohort; "
            "evidence: build every company with canonical "
            "business evidence."
        ),
    )

    parser.add_argument(
        "--symbol",
        action="append",
        default=[],
        help=(
            "Optional explicit symbol. Repeat for "
            "multiple symbols. Overrides --scope."
        ),
    )

    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "Atomically replace the generated V2 profile "
            "indexes after the entire target cohort builds."
        ),
    )

    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help=(
            "Allow writing successfully generated companies "
            "even when some targets fail. Do not use for "
            "production migration."
        ),
    )

    args = parser.parse_args()

    report = (
        build_company_profile_batch(
            ROOT,
            scope=args.scope,
            symbols=args.symbol,
        )
    )

    public = _public_report(
        report
    )

    if args.write:
        try:
            outputs = (
                write_company_profile_batch(
                    ROOT,
                    report,
                    allow_partial=(
                        args.allow_partial
                    ),
                )
            )
        except CompanyProfileBatchError as exc:
            public[
                "write_status"
            ] = "blocked"

            public[
                "write_error"
            ] = str(exc)

            print(
                json.dumps(
                    public,
                    ensure_ascii=False,
                    indent=2,
                )
            )

            return 2

        public[
            "write_status"
        ] = "written"

        public[
            "outputs"
        ] = outputs

    print(
        json.dumps(
            public,
            ensure_ascii=False,
            indent=2,
        )
    )

    if not (
        report[
            "summary"
        ][
            "complete"
        ]
    ):
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())