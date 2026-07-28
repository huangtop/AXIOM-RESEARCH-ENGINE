#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.sec_financial_population import (  # noqa: E402
    build_sec_financial_population,
    write_sec_financial_population,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build full-scope SEC Companyfacts financial population.")
    parser.add_argument("--bulk-zip", type=Path)
    parser.add_argument("--download-bulk", action="store_true")
    parser.add_argument("--user-agent", default="")
    parser.add_argument("--write-cache", action="store_true")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.download_bulk:
        if not args.bulk_zip:
            parser.error("--download-bulk requires --bulk-zip")
        if not re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", args.user_agent):
            parser.error("--user-agent must include a contact email")
        request = urllib.request.Request(
            "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip",
            headers={"User-Agent": args.user_agent},
        )
        args.bulk_zip.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.bulk_zip.with_suffix(".zip.tmp")
        with urllib.request.urlopen(request, timeout=300) as response:
            temporary.write_bytes(response.read())
        temporary.replace(args.bulk_zip)
    report = build_sec_financial_population(
        ROOT, bulk_zip=args.bulk_zip, limit=args.limit, offset=args.offset, write_cache=args.write_cache
    )
    if args.write:
        write_sec_financial_population(report, ROOT / "data/generated/canonical_financial_population")
    print(report["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
