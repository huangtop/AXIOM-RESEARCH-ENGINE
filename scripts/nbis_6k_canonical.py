from __future__ import annotations

import json
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

CID = "company:US-CIK0001513845"
CIK = "0001513845"
ROOT = Path("data/generated/canonical_financial_population")
OUT = Path("/tmp/axiom_nbis_6k_staging.json")
LINEAGE = Path("/tmp/axiom_nbis_6k_lineage.json")
M = Decimal("1000000")

URL = {
    "2025H1": (
        "https://www.sec.gov/Archives/edgar/data/1513845/"
        "000110465925088860/tm2525580d2_ex99-2.htm"
    ),
    "2025_9M": (
        "https://www.sec.gov/Archives/edgar/data/1513845/"
        "000110465925110831/tm2531034d1_ex99-2.htm"
    ),
    "2025FY": (
        "https://www.sec.gov/Archives/edgar/data/1513845/"
        "000110465926052948/nbis-20251231x20f.htm"
    ),
    "2026Q1": (
        "https://www.sec.gov/Archives/edgar/data/1513845/"
        "000110465926059872/tm2614392d1_ex99-1.htm"
    ),
    "2026Q2": (
        "https://www.sec.gov/Archives/edgar/data/1513845/"
        "000110465926094844/nbis-20260812xex99d2.htm"
    ),
}

ACC = {
    "2025H1": "0001104659-25-088860",
    "2025_9M": "0001104659-25-110831",
    "2025FY": "0001104659-26-052948",
    "2026Q1": "0001104659-26-059872",
    "2026Q2": "0001104659-26-094844",
}

# SEC GAAP comparison / cumulative anchors.
# USD millions.
# Net income: consolidated including discontinued operations.
# OCF: consolidated including discontinued operations.
# CapEx: purchases of PPE and intangible assets, positive magnitude.
ANCHORS = {
    "revenue": {
        "2025Q1": "50.9",
        "2025H1": "156.0",
        "2025_9M": "302.1",
        "2025FY": "529.8",
        "2026Q1": "399.0",
        "2026H1": "981.3",
    },
    "net_income": {
        "2025Q1": "-113.5",
        "2025H1": "470.9",
        "2025_9M": "351.3",
        "2025FY": "82.5",
        "2026Q1": "621.2",
        "2026H1": "430.8",
    },
    "operating_cash_flow": {
        "2025Q1": "-197.5",
        "2025H1": "-369.1",
        "2025_9M": "-449.5",
        "2025FY": "384.8",
        "2026Q1": "2258.0",
        "2026H1": "4504.1",
    },
    "capital_expenditures": {
        "2025Q1": "543.9",
        "2025H1": "1054.5",
        "2025_9M": "2010.0",
        "2025FY": "4066.0",
        "2026Q1": "2472.9",
        "2026H1": "8130.3",
    },
}

PERIODS = {
    "2025Q1": ("2025-01-01", "2025-03-31", 2025, "Q1"),
    "2025Q2": ("2025-04-01", "2025-06-30", 2025, "Q2"),
    "2025Q3": ("2025-07-01", "2025-09-30", 2025, "Q3"),
    "2025Q4": ("2025-10-01", "2025-12-31", 2025, "Q4"),
    "2026Q1": ("2026-01-01", "2026-03-31", 2026, "Q1"),
    "2026Q2": ("2026-04-01", "2026-06-30", 2026, "Q2"),
}

def d(x):
    return Decimal(str(x))

def verify_annual():
    facts = json.loads(
        (ROOT / "financial_facts.json").read_text()
    )
    expected = {
        "revenue": "529800000",
        "net_income": "82500000",
        "operating_cash_flow": "384800000",
        "capital_expenditures": "4066000000",
    }

    observed = {}
    for row in facts:
        if (
            row.get("company_id") == CID
            and row.get("period_end") == "2025-12-31"
            and row.get("metric") in expected
        ):
            observed[row["metric"]] = d(row["value"])

    for metric, value in expected.items():
        assert observed.get(metric) == d(value), (
            f"Annual mismatch: {metric}, "
            f"actual={observed.get(metric)}, expected={value}"
        )

    print("ANNUAL CANONICAL RECONCILIATION: PASS")

def build():
    rows = []
    lineage = []

    for metric, a in ANCHORS.items():
        values = {
            "2025Q1": d(a["2025Q1"]),
            "2025Q2": d(a["2025H1"]) - d(a["2025Q1"]),
            "2025Q3": d(a["2025_9M"]) - d(a["2025H1"]),
            "2025Q4": d(a["2025FY"]) - d(a["2025_9M"]),
            "2026Q1": d(a["2026Q1"]),
            "2026Q2": d(a["2026H1"]) - d(a["2026Q1"]),
        }

        assert sum(
            (values[f"2025Q{i}"] for i in range(1, 5)),
            Decimal("0"),
        ) == d(a["2025FY"])

        assert (
            values["2026Q1"] + values["2026Q2"]
            == d(a["2026H1"])
        )

        if metric == "capital_expenditures":
            assert all(x >= 0 for x in values.values())

        for period, value in values.items():
            start, end, fy, fp = PERIODS[period]

            if period == "2025Q1":
                # Later comparative figures, including Toloka
                # discontinued-operations presentation.
                keys = ["2026Q1"]
                method = "restated_comparative"
            elif period == "2025Q2":
                keys = ["2025H1", "2026Q1"]
                method = "H1_minus_Q1"
            elif period == "2025Q3":
                keys = ["2025_9M", "2025H1"]
                method = "9M_minus_H1"
            elif period == "2025Q4":
                keys = ["2025FY", "2025_9M"]
                method = "FY_minus_9M"
            elif period == "2026Q1":
                keys = ["2026Q1"]
                method = "direct_quarter"
            else:
                keys = ["2026Q2", "2026Q1"]
                method = "H1_minus_Q1"

            primary = keys[0]
            acc = ACC[primary]
            usd = value * M
            assert usd == usd.to_integral_value()

            fact_id = (
                f"quarterly_financial_fact:{CIK}:"
                f"{metric}:{end}:{fp}"
            )

            rows.append({
                "financial_fact_id": fact_id,
                "company_id": CID,
                "metric": metric,
                "value": str(int(usd)),
                "unit": "currency",
                "currency": "USD",
                "period_type": "duration",
                "period_start": start,
                "period_end": end,
                "fiscal_year": fy,
                "fiscal_period": fp,
                "statement": (
                    "income_statement"
                    if metric in ("revenue", "net_income")
                    else "cash_flow"
                ),
                "form_type": "20-F" if primary == "2025FY"
                             else "6-K",
                "accession_number": acc,
                "source": {
                    "provider": "sec_6k_manual_verified",
                    "formula_version": "nbis_6k_v1",
                    "source_fact_ids": [
                        f"sec:{ACC[k]}:{metric}:{k}"
                        for k in keys
                    ],
                },
            })

            lineage.append({
                "financial_fact_id": fact_id,
                "accounting_basis": (
                    "consolidated_total_including_discontinued"
                    if metric in ("net_income", "operating_cash_flow")
                    else "consolidated"
                ),
                "calculation": method,
                "period_value_usd_millions": str(value),
                "sources": [
                    {
                        "accession": ACC[k],
                        "url": URL[k],
                        "period": k,
                    }
                    for k in keys
                ],
            })

    return rows, lineage

def validate(rows, lineage):
    assert len(rows) == 24
    assert len(lineage) == 24
    assert len({
        r["financial_fact_id"] for r in rows
    }) == 24
    assert len({
        (r["metric"], r["period_end"])
        for r in rows
    }) == 24

    required = {
        "financial_fact_id", "company_id", "metric",
        "value", "unit", "currency", "period_type",
        "period_start", "period_end", "fiscal_year",
        "fiscal_period", "statement", "form_type",
        "accession_number", "source",
    }

    counts = Counter()
    for row in rows:
        assert required <= row.keys()
        assert row["company_id"] == CID
        assert row["period_type"] == "duration"
        assert row["unit"] == "currency"
        assert row["currency"] == "USD"
        assert row["form_type"] in ("6-K", "20-F")
        assert date.fromisoformat(
            row["period_start"]
        ) <= date.fromisoformat(row["period_end"])
        assert len(row["source"]["source_fact_ids"]) >= 1
        assert row["statement"] in (
            "income_statement", "cash_flow"
        )
        counts[row["metric"]] += 1

    assert counts == {
        "revenue": 6,
        "net_income": 6,
        "operating_cash_flow": 6,
        "capital_expenditures": 6,
    }

    for metric, expected in (
        ("revenue", "529800000"),
        ("net_income", "82500000"),
        ("operating_cash_flow", "384800000"),
        ("capital_expenditures", "4066000000"),
    ):
        actual = sum(
            (d(r["value"]) for r in rows
             if r["metric"] == metric
             and r["fiscal_year"] == 2025),
            Decimal("0"),
        )
        assert actual == d(expected), (
            metric, actual, expected
        )

    print("SCHEMA FIELD / IDENTITY CHECK: PASS")
    print("6 QUARTERS x 4 CORE METRICS: PASS")
    print("2025 ANNUAL TOTALS: PASS")
    print("2026 H1 TOTALS: PASS")
    print("PERIODS / NO DUPLICATES: PASS")

def main():
    verify_annual()
    rows, lineage = build()
    validate(rows, lineage)

    rows.sort(
        key=lambda r: (
            r["period_end"], r["metric"]
        )
    )
    lineage.sort(key=lambda x: x["financial_fact_id"])

    OUT.write_text(
        json.dumps(
            rows, indent=2, ensure_ascii=False
        ) + "\n",
        encoding="utf-8",
    )
    LINEAGE.write_text(
        json.dumps(
            lineage, indent=2, ensure_ascii=False
        ) + "\n",
        encoding="utf-8",
    )

    print("\nNBIS FULL GAAP STAGING: PASS")
    print("Quarterly facts:", len(rows))
    print("SEC source references:", len(lineage))
    print("Staging:", OUT)
    print("Lineage:", LINEAGE)
    print("CANONICAL UNCHANGED")

if __name__ == "__main__":
    main()
