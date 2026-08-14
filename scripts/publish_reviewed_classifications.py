#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.company_overview import (  # noqa: E402
    build_company_overviews,
    write_company_overviews,
)
from axiom_engine.company_signals import build_company_signals  # noqa: E402
from axiom_engine.knowledge_inference import build_knowledge_inference  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish an offering-backed, locally reviewed classification cohort."
    )
    parser.add_argument("--ticker", action="append", required=True)
    args = parser.parse_args()
    requested = {str(value).strip().upper() for value in args.ticker if str(value).strip()}

    securities = json.loads((ROOT / "data/universe/securities.json").read_text())
    company_by_ticker = {
        str(row.get("ticker") or "").upper(): str(row.get("company_id") or "")
        for row in securities
        if row.get("ticker") and row.get("company_id")
    }
    missing = sorted(requested - company_by_ticker.keys())
    if missing:
        raise SystemExit(f"unknown tickers: {', '.join(missing)}")
    company_ids = {company_by_ticker[ticker] for ticker in requested}

    signals = build_company_signals(ROOT, company_ids=company_ids)
    knowledge = build_knowledge_inference(ROOT, signals_payload=signals)
    report = build_company_overviews(
        ROOT,
        company_ids=company_ids,
        knowledge_payload=knowledge,
        respect_existing_locks=False,
        strict_company_scope=True,
    )
    knowledge_by_company = {
        str(row["company_id"]): row for row in knowledge.get("records") or []
    }
    published_tickers = {str(row.get("ticker") or "") for row in report["records"]}
    if published_tickers != requested:
        raise SystemExit(
            f"publication scope mismatch: requested={sorted(requested)} "
            f"generated={sorted(published_tickers)}"
        )
    for row in report["records"]:
        if row.get("status") != "classified":
            raise SystemExit(f"classification is not publishable: {row.get('ticker')}")
        sector_id = str(((row.get("path") or {}).get("sector") or {}).get("id") or "")
        sector = next(
            (
                item
                for item in knowledge_by_company[row["company_id"]].get("knowledge") or []
                if item.get("knowledge_id") == sector_id
            ),
            None,
        )
        if not sector or int(sector.get("primary_business_score") or 0) != 3:
            raise SystemExit(f"classification is not company-offering backed: {row.get('ticker')}")
        row["classification_source"] = "reviewed_automatic_inference"

    write_company_overviews(
        report,
        ROOT / "data/generated/company_overview",
        preserve_existing=True,
    )
    print(json.dumps({"published": sorted(requested), "count": len(requested)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
