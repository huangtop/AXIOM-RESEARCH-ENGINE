#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.sec_company_evidence import (  # noqa: E402
    build_sec_company_evidence,
    download_submissions_bulk,
    write_sec_company_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build canonical SEC company evidence for the full Registry.")
    parser.add_argument("--bulk-zip", type=Path)
    parser.add_argument("--download-bulk", action="store_true")
    parser.add_argument("--user-agent", default="")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--write-cache", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("data/generated/canonical_company_evidence"))
    args = parser.parse_args()
    if args.download_bulk:
        if not args.bulk_zip:
            parser.error("--download-bulk requires --bulk-zip")
        download_submissions_bulk(target=args.bulk_zip, user_agent=args.user_agent)
    report = build_sec_company_evidence(
        ROOT,
        bulk_zip=args.bulk_zip,
        allow_live=args.allow_live,
        user_agent=args.user_agent,
        write_cache=args.write_cache,
    )
    if args.write:
        write_sec_company_evidence(report, ROOT / args.output_dir)
    for key, value in report["summary"].items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
