#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Mark successfully refreshed SEC filing accessions as processed")
    parser.add_argument("--plan", default="data/generated/sec_filing_refresh/refresh_plan.json")
    parser.add_argument("--ledger", default="data/generated/sec_filing_refresh/accession_ledger.json")
    parser.add_argument("--business-evidence", default="data/generated/canonical_business_evidence/business_evidence.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    plan = json.loads((root / args.plan).read_text(encoding="utf-8"))
    ledger_path = root / args.ledger
    prior = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.is_file() else {}
    records = {
        str(row["accession_number"]): row
        for row in prior.get("processed_accessions") or []
        if row.get("accession_number")
    }
    evidence_path = root / args.business_evidence
    evidence = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.is_file() else []
    evidence_accessions = {str(row.get("accession_number") or "") for row in evidence}
    annual_forms = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
    deferred_annual = []
    processed_at = datetime.now(timezone.utc).isoformat()
    for company in plan.get("worklist") or []:
        for filing in company.get("pending_filings") or []:
            accession = str(filing.get("accession_number") or "")
            if not accession:
                continue
            form = str(filing.get("form") or "").upper()
            if form in annual_forms and accession not in evidence_accessions:
                deferred_annual.append(accession)
                continue
            records[accession] = {
                "accession_number": accession,
                "company_id": company.get("company_id"),
                "form": form,
                "filing_date": filing.get("filing_date"),
                "report_date": filing.get("report_date"),
                "processed_at": processed_at,
            }
    payload = {
        "schema_version": "sec-accession-ledger.v031c.2",
        "updated_at": processed_at,
        "processed_accessions": sorted(records.values(), key=lambda row: (str(row.get("filing_date") or ""), str(row["accession_number"]))),
    }
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ledger_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(ledger_path)
    print({"processed_accession_count": len(records), "deferred_annual_evidence_accessions": deferred_annual})


if __name__ == "__main__":
    main()
