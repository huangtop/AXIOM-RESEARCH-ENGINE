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


def _resume_company_ids(root: Path, output_dir: Path) -> list[str]:
    evidence_path = root / output_dir / "business_evidence.json"
    relevance_path = root / "data/generated/research_relevance_gate/research_relevance_gate.json"
    prior_evidence = (
        json.loads(evidence_path.read_text(encoding="utf-8"))
        if evidence_path.is_file()
        else []
    )
    covered = {str(row.get("company_id") or "") for row in prior_evidence}
    if not relevance_path.is_file():
        return []
    relevance = json.loads(relevance_path.read_text(encoding="utf-8"))
    records = relevance.get("records") or []
    eligibility_path = root / "data/generated/research_eligibility/research_eligibility.json"
    eligibility = (
        json.loads(eligibility_path.read_text(encoding="utf-8"))
        if eligibility_path.is_file()
        else {"records": []}
    )
    event_triggered = {
        str(row.get("company_id") or "")
        for row in eligibility.get("records") or []
        if row.get("deep_research_triggers")
    }
    priority = {"priority_candidate": 0, "evidence_required": 1}
    candidates = [
        row
        for row in records
        if row.get("status") in priority
        and str(row.get("company_id") or "") not in covered
    ]
    candidates.sort(
        key=lambda row: (
            0 if str(row.get("company_id") or "") in event_triggered else 1,
            priority[str(row["status"])],
            str(row.get("company_id") or ""),
        )
    )
    return [str(row["company_id"]) for row in candidates]


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
    company_ids = args.company_id
    if args.resume:
        company_ids = _resume_company_ids(ROOT, args.output_dir)
    report = build_sec_business_evidence(
        ROOT,
        allow_live=args.allow_live,
        user_agent=args.user_agent,
        limit=args.limit,
        offset=offset,
        company_ids=company_ids,
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
