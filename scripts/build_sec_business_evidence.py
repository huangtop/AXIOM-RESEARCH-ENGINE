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
from axiom_engine.business_evidence_store import load_business_evidence  # noqa: E402


def _resume_company_ids(root: Path, output_dir: Path, priority_symbols: Path | None = None) -> list[str]:
    evidence_path = root / output_dir / "business_evidence.json"
    relevance_path = root / "data/generated/research_relevance_gate/research_relevance_gate.json"
    prior_evidence = load_business_evidence(evidence_path)
    covered = {str(row.get("company_id") or "") for row in prior_evidence}
    diagnostics_path = root / output_dir / "diagnostics.json"
    prior_diagnostics = (
        json.loads(diagnostics_path.read_text(encoding="utf-8"))
        if diagnostics_path.is_file()
        else []
    )
    attempted = covered | {
        str(row.get("company_id") or "")
        for row in prior_diagnostics
        if row.get("company_id")
    }
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
    priority = {"priority_candidate": 0, "evidence_required": 1, "market_coverage": 2}
    candidates = [
        row
        for row in records
        if row.get("status") in priority
        and str(row.get("company_id") or "") not in attempted
    ]
    # Evidence coverage is market-wide.  The relevance gate controls research
    # actions, not whether an otherwise eligible public company gets a first
    # evidence attempt.  Only enqueue companies that have a filing manifest;
    # foreign/OTC identities without one are handled by their own providers.
    identity_path = root / "data/generated/security_identity/security_identity_normalization.json"
    filing_path = root / "data/generated/canonical_company_evidence/filing_documents.json"
    market_actionable_ids: set[str] | None = None
    if identity_path.is_file() and filing_path.is_file():
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        filing_rows = json.loads(filing_path.read_text(encoding="utf-8"))
        eligible_ids = {
            str(row.get("company_id"))
            for row in identity.get("securities") or []
            if row.get("valuation_eligible") is True and row.get("company_id")
        }
        filing_ids = {
            str(row.get("company_id")) for row in filing_rows if row.get("company_id")
        }
        market_actionable_ids = eligible_ids & filing_ids
        candidate_ids = {str(row.get("company_id") or "") for row in candidates}
        candidates.extend(
            {"company_id": company_id, "status": "market_coverage"}
            for company_id in sorted((eligible_ids & filing_ids) - attempted - candidate_ids)
        )
    priority_ids: set[str] = set()
    if priority_symbols:
        symbols = {str(value).upper() for value in json.loads(priority_symbols.read_text()).get("symbols") or []}
        securities = json.loads((root / "data/universe/securities.json").read_text(encoding="utf-8"))
        priority_ids = {
            str(row.get("company_id")) for row in securities
            if str(row.get("ticker") or "").upper() in symbols
        }
        # Priority coverage is a hard inclusion set, not merely a sort hint.
        # Previously a company first had to pass the relevance gate, so missing
        # evidence could prevent it from ever entering the evidence worklist.
        candidate_ids = {str(row.get("company_id") or "") for row in candidates}
        candidates.extend(
            {"company_id": company_id, "status": "evidence_required"}
            for company_id in sorted(priority_ids - attempted - candidate_ids)
        )
    if market_actionable_ids is not None:
        candidates = [
            row for row in candidates
            if str(row.get("company_id") or "") in market_actionable_ids
        ]
    candidates.sort(
        key=lambda row: (
            0 if str(row.get("company_id") or "") in priority_ids else 1,
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
    parser.add_argument("--refresh-plan")
    parser.add_argument("--priority-symbols", type=Path)
    parser.add_argument("--delay", type=float, default=0.11)
    parser.add_argument("--output-dir", type=Path, default=Path("data/generated/canonical_business_evidence"))
    args = parser.parse_args()
    if args.resume and args.offset:
        parser.error("--resume and --offset cannot be combined")
    offset = args.offset
    company_ids = args.company_id
    if args.refresh_plan:
        refresh = json.loads((ROOT / args.refresh_plan).read_text(encoding="utf-8"))
        company_ids = [
            str(row["company_id"])
            for row in refresh.get("worklist") or []
            if row.get("requires_business_evidence_refresh")
        ]
    if args.resume:
        company_ids = _resume_company_ids(ROOT, args.output_dir, args.priority_symbols)
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
