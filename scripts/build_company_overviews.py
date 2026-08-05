#!/usr/bin/env python3
import json
from pathlib import Path
from axiom_engine.company_overview import build_company_overviews, write_company_overviews

root = Path(__file__).resolve().parents[1]
eligibility = json.loads(
    (root / "data/generated/research_eligibility/research_eligibility.json").read_text(
        encoding="utf-8"
    )
)
company_ids = {
    str(row["company_id"])
    for row in eligibility.get("records") or []
    if row.get("research_universe_status") == "selected"
}
report = build_company_overviews(root, company_ids=company_ids)
write_company_overviews(report, root / "data/generated/company_overview")
print(report["summary"])
