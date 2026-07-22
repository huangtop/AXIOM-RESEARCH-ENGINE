#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from axiom_engine.previous_close import YahooPreviousCloseAdapter
from axiom_engine.valuation_api import (
    BackendValuationAPIService,
    ValuationAPIError,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run AXIOM canonical repository valuation locally "
            "without Streamlit or HTTP."
        )
    )
    parser.add_argument(
        "symbol",
        help="Security ticker, for example NVDA.",
    )
    parser.add_argument(
        "--scenario-id",
        default=None,
        help="Optional canonical valuation scenario ID.",
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help=(
            "Optional timezone-aware ISO-8601 datetime, "
            "for example 2026-07-22T12:00:00+08:00."
        ),
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    return parser.parse_args()


def build_request(args: argparse.Namespace) -> dict[str, Any]:
    request: dict[str, Any] = {
        "symbol": args.symbol.strip().upper(),
    }

    if args.scenario_id:
        request["scenario_id"] = args.scenario_id.strip()

    if args.as_of:
        request["as_of"] = args.as_of.strip()

    return request


def main() -> int:
    args = parse_args()

    service = BackendValuationAPIService(
        close_provider=YahooPreviousCloseAdapter(),
    )

    try:
        result = service.calculate(build_request(args))
    except ValuationAPIError as exc:
        print(
            json.dumps(
                {
                    "error": "invalid_request",
                    "message": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": type(exc).__name__,
                    "message": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())