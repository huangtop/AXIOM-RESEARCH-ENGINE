#!/usr/bin/env python3
from pathlib import Path
from axiom_engine.company_overview import build_company_overviews, write_company_overviews

root = Path(__file__).resolve().parents[1]
report = build_company_overviews(root)
write_company_overviews(report, root / "data/generated/company_overview")
print(report["summary"])
