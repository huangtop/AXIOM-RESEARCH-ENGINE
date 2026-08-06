#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


CANARY_CIKS = {
    "NVDA": "0001045810",
    "MU": "0000723125",
    "AMD": "0000002488",
    "GOOGL": "0001652044",
    "INTC": "0000050863",
    "TSLA": "0001318605",
    "TSM": "0001046179",
    "ARM": "0001973239",
}


def _download(url: str, output: Path, user_agent: str) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch eight SEC financial canaries only.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--user-agent", required=True)
    args = parser.parse_args()
    if not re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", args.user_agent):
        parser.error("--user-agent must contain a contact email")

    manifest = {"generated_at": datetime.now(timezone.utc).isoformat(), "companies": []}
    for ticker, cik in CANARY_CIKS.items():
        fact_path = args.output / "companyfacts" / f"CIK{cik}.json"
        submission_path = args.output / "submissions" / f"CIK{cik}.json"
        _download(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", fact_path, args.user_agent)
        _download(f"https://data.sec.gov/submissions/CIK{cik}.json", submission_path, args.user_agent)
        manifest["companies"].append(
            {"ticker": ticker, "cik": cik, "companyfacts": str(fact_path), "submissions": str(submission_path)}
        )
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print({"company_count": len(manifest["companies"]), "output": str(args.output)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
