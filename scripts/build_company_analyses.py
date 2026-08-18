#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.company_analysis import build_company_analyses, write_company_analyses  # noqa: E402
from axiom_engine.company_signals import build_company_signals  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic SEC-backed company analyses.")
    parser.add_argument("--symbol", action="append", default=[])
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    company_ids = None
    if args.symbol:
        wanted = {str(value).upper() for value in args.symbol}
        securities = json.loads((ROOT / "data/universe/securities.json").read_text())
        company_ids = {str(row["company_id"]) for row in securities if str(row.get("ticker") or "").upper() in wanted}
    signals = build_company_signals(ROOT, company_ids=company_ids)
    report = build_company_analyses(ROOT, company_ids=company_ids, signals_payload=signals)
    if args.write:
        if args.symbol:
            raise SystemExit(
                "--write cannot be combined with --symbol because a partial build "
                "would replace the published company_analysis index. "
                "Run without --symbol to publish the full cohort."
            )

        write_company_analyses(
            report,
            ROOT / "data/generated/company_analysis",
        )
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
