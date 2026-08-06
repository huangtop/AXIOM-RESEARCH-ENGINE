#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.sec_financial_population.core import _quarterly_facts  # noqa: E402


def _latest_quarter_report(payload: dict) -> dict | None:
    recent = ((payload.get("filings") or {}).get("recent") or {})
    keys = ("accessionNumber", "form", "filingDate", "reportDate")
    rows = [dict(zip(keys, values)) for values in zip(*(recent.get(key) or [] for key in keys))]
    candidates = [row for row in rows if row["form"] in {"10-Q", "10-Q/A"} and row["reportDate"]]
    return max(candidates, key=lambda row: (row["reportDate"], row["filingDate"])) if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate SEC quarterly canaries locally.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.input / "manifest.json").read_text(encoding="utf-8"))
    results, failures = [], []
    for item in manifest["companies"]:
        ticker, cik = item["ticker"], item["cik"]
        facts = json.loads((args.input / "companyfacts" / f"CIK{cik}.json").read_text(encoding="utf-8"))
        submissions = json.loads((args.input / "submissions" / f"CIK{cik}.json").read_text(encoding="utf-8"))
        rows = _quarterly_facts(f"canary:{ticker}", cik, facts)
        eps = sorted((row for row in rows if row["metric"] == "diluted_eps"), key=lambda row: row["period_end"])
        latest_report = _latest_quarter_report(submissions)
        issues = []
        if latest_report and (not eps or eps[-1]["period_end"] != latest_report["reportDate"]):
            issues.append("LATEST_10Q_PERIOD_MISSING")
        if len({row["financial_fact_id"] for row in rows}) != len(rows):
            issues.append("DUPLICATE_FINANCIAL_FACT_ID")
        if any(row["metric"] in {"revenue", "diluted_shares_outstanding"} and float(row["value"]) < 0 for row in rows):
            issues.append("IMPOSSIBLE_NEGATIVE_REVENUE_OR_SHARES")
        result = {
            "ticker": ticker,
            "latest_10q_report_date": latest_report["reportDate"] if latest_report else None,
            "latest_eps_period_end": eps[-1]["period_end"] if eps else None,
            "eps_quarter_count": len(eps),
            "latest_four_eps": [
                {"fiscal_year": row["fiscal_year"], "fiscal_period": row["fiscal_period"], "period_end": row["period_end"], "value": row["value"]}
                for row in eps[-4:]
            ],
            "issues": issues,
        }
        results.append(result)
        failures.extend(f"{ticker}:{issue}" for issue in issues)
    report = {"company_count": len(results), "failure_count": len(failures), "failures": failures, "companies": results}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
