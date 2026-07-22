#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from axiom_engine.financial_statement_builder import FinancialStatementBuilder


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Company Facts input must be a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build canonical statements from SEC Company Facts")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fiscal-year", type=int)
    parser.add_argument("--fiscal-period", default="FY")
    args = parser.parse_args()
    statements = FinancialStatementBuilder().build(
        _read_json(args.input),
        fiscal_year=args.fiscal_year,
        fiscal_period=args.fiscal_period,
    )
    rendered = json.dumps(statements.to_dict(), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"wrote canonical financial statements to {args.output}")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
