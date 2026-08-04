from __future__ import annotations

import json
from datetime import datetime, timezone

from axiom_engine.sec_financial_population import build_sec_financial_population, write_sec_financial_population


def _fact(label, value, unit="USD"):
    return {"label": label, "units": {unit: [{"val": value, "start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-01", "form": "10-K", "fy": 2025, "fp": "FY", "accn": "0001-26-1"}]}}


def _root(tmp_path):
    universe = tmp_path / "data/universe"
    universe.mkdir(parents=True)
    universe.joinpath("companies.json").write_text(json.dumps([
        {"company_id": "company:1", "metadata": {"cik": 1}},
        {"company_id": "company:excluded", "metadata": {"cik": 2}},
    ]), encoding="utf-8")
    identity = tmp_path / "data/generated/security_identity"
    identity.mkdir(parents=True)
    identity.joinpath("security_identity_normalization.json").write_text(json.dumps({"companies": [
        {"company_id": "company:1", "valuation_scope_status": "included"},
        {"company_id": "company:excluded", "valuation_scope_status": "excluded"},
    ]}), encoding="utf-8")
    cache = tmp_path / "data/generated/provider_cache/sec/companyfacts"
    cache.mkdir(parents=True)
    payload = {"facts": {"us-gaap": {
        "Revenues": _fact("Revenue", 1000),
        "NetIncomeLoss": _fact("Net income", 100),
        "StockholdersEquity": _fact("Equity", 500),
        "CommonStockSharesOutstanding": _fact("Shares", 100, "shares"),
    }}}
    cache.joinpath("CIK0000000001.json").write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


def test_population_consumes_only_normalized_valuation_scope_and_derives_book_value(tmp_path):
    report = build_sec_financial_population(_root(tmp_path), now=datetime(2026, 7, 28, tzinfo=timezone.utc))
    assert report["summary"]["cik_scope_company_count"] == 1
    assert report["summary"]["companies_with_financial_facts"] == 1
    facts = {row["metric"]: row for row in report["financial_facts"]}
    assert facts["revenue"]["value"] == "1000"
    assert facts["book_value_per_share"]["value"] == "5"
    assert facts["book_value_per_share"]["source"]["formula_version"] == "book_value_per_share.v031v.3"
    assert "ebitda" not in facts


def test_missing_companyfacts_is_diagnostic_not_zero(tmp_path):
    root = _root(tmp_path)
    (root / "data/generated/provider_cache/sec/companyfacts/CIK0000000001.json").unlink()
    report = build_sec_financial_population(root)
    assert report["financial_facts"] == []
    assert report["diagnostics"][0]["reason_code"] == "SEC_COMPANYFACTS_NOT_AVAILABLE"


def test_population_retains_up_to_eight_discrete_quarters_for_eps_chart(tmp_path):
    root = _root(tmp_path)
    path = root / "data/generated/provider_cache/sec/companyfacts/CIK0000000001.json"
    payload = json.loads(path.read_text())
    payload["facts"]["us-gaap"]["EarningsPerShareDiluted"] = {
        "label": "Diluted EPS",
        "units": {
            "USD/shares": [
                {
                    "val": index / 10,
                    "start": f"{year}-{month:02d}-01",
                    "end": f"{year}-{month + 2:02d}-28",
                    "filed": f"{year}-{month + 3:02d}-15",
                    "form": "10-Q",
                    "fy": year,
                    "fp": f"Q{quarter}",
                    "accn": f"{year}-{quarter}",
                }
                for index, (year, quarter, month) in enumerate(
                    [
                        (2023, 1, 1), (2023, 2, 4), (2023, 3, 7),
                        (2024, 1, 1), (2024, 2, 4), (2024, 3, 7),
                        (2025, 1, 1), (2025, 2, 4), (2025, 3, 7),
                    ],
                    start=1,
                )
            ] + [{
                    "val": 3.8,
                    "start": "2025-01-01",
                    "end": "2025-12-31",
                    "filed": "2026-02-15",
                    "form": "10-K",
                    "fy": 2025,
                    "fp": "FY",
                    "accn": "2025-FY",
                }]
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    report = build_sec_financial_population(root)
    quarters = [
        row for row in report["quarterly_financial_facts"]
        if row["metric"] == "diluted_eps"
    ]
    assert len(quarters) == 8
    assert quarters[-1]["fiscal_year"] == 2025
    assert quarters[-1]["fiscal_period"] == "Q4"
    assert quarters[-1]["value"] == "1.4"
    assert quarters[-1]["source"]["period_selection"] == "annual_less_q1_q2_q3"
    output = root / "out"
    write_sec_financial_population(report, output)
    index = json.loads((output / "quarterly_index.json").read_text())
    quarterly_file = output / index["company_id_to_file"]["company:1"]
    assert quarterly_file.is_file()
    assert len(json.loads(quarterly_file.read_text())) >= 8
