#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.sec_business_evidence import (  # noqa: E402
    build_sec_business_evidence,
    write_sec_business_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract verifiable Business sections from SEC annual filings.")
    parser.add_argument("--user-agent", default="")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--write-cache", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--merge-existing", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--company-id", action="append", default=[])
    parser.add_argument("--delay", type=float, default=0.11)
    parser.add_argument("--output-dir", type=Path, default=Path("data/generated/canonical_business_evidence"))
    args = parser.parse_args()
    if args.resume and args.offset:
        parser.error("--resume and --offset cannot be combined")
    offset = args.offset
    manifest_path = ROOT / args.output_dir / "manifest.json"
    if args.resume and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        summary = manifest.get("summary") or {}
        offset = int(summary.get("batch_offset") or 0) + int(
            summary.get("filings_requested") or 0
        )
    report = build_sec_business_evidence(
        ROOT,
        allow_live=args.allow_live,
        user_agent=args.user_agent,
        limit=args.limit,
        offset=offset,
        company_ids=args.company_id,
        write_cache=args.write_cache,
        request_delay_seconds=args.delay,
    )
    if args.write:
        write_sec_business_evidence(report, ROOT / args.output_dir, merge_existing=args.merge_existing)
    for key, value in report["summary"].items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
