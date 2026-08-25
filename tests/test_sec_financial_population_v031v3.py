from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

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


def test_population_retains_only_eight_latest_direct_discrete_quarters(tmp_path):
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
    assert quarters[0]["fiscal_year"] == 2023
    assert quarters[0]["fiscal_period"] == "Q2"
    assert quarters[0]["value"] == "0.2"
    assert quarters[-1]["fiscal_year"] == 2025
    assert quarters[-1]["fiscal_period"] == "Q3"
    assert quarters[-1]["value"] == "0.9"
    assert quarters[-1]["source"]["period_selection"] == "discrete_quarter_60_to_120_days"
    assert all(row["fiscal_period"] != "Q4" for row in quarters)
    output = root / "out"
    write_sec_financial_population(report, output)
    index = json.loads((output / "quarterly_index.json").read_text())
    quarterly_file = output / index["company_id_to_file"]["company:1"]
    assert quarterly_file.is_file()
    written = json.loads(quarterly_file.read_text())
    assert len({row["period_end"] for row in written}) == 8
    assert "2023-03-28" not in {row["period_end"] for row in written}
    assert all(row.get("accession_number") for row in written)
    assert all(row.get("source") == {"provider": "sec_companyfacts"} for row in written)
    assert all("xbrl_tag" not in row.get("source", {}) for row in written)
    assert all("period_selection" not in row.get("source", {}) for row in written)
    assert all("source_accessions" not in row.get("source", {}) for row in written)


def test_public_annual_snapshot_keeps_accession_but_strips_parser_provenance(tmp_path):
    root = _root(tmp_path)
    report = build_sec_financial_population(root)
    internal_revenue = next(
        row for row in report["financial_facts"] if row["metric"] == "revenue"
    )
    assert internal_revenue["source"]["xbrl_tag"] == "Revenues"

    output = root / "out"
    write_sec_financial_population(report, output)
    public_revenue = next(
        row
        for row in json.loads((output / "financial_facts.json").read_text())
        if row["metric"] == "revenue"
    )
    assert public_revenue["accession_number"] == "0001-26-1"
    assert public_revenue["source"] == {"provider": "sec_companyfacts"}


def test_population_does_not_derive_discrete_q2_cash_flow_from_ytd(tmp_path):
    root = _root(tmp_path)
    path = root / "data/generated/provider_cache/sec/companyfacts/CIK0000000001.json"
    payload = json.loads(path.read_text())
    def rows(q1, half):
        return {"units": {"USD": [
            {"val": q1, "start": "2026-01-01", "end": "2026-03-31", "filed": "2026-04-25", "form": "10-Q", "fy": 2026, "fp": "Q1", "accn": "q1"},
            {"val": half, "start": "2026-01-01", "end": "2026-06-30", "filed": "2026-07-25", "form": "10-Q", "fy": 2026, "fp": "Q2", "accn": "q2"},
        ]}}
    payload["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"] = rows(45_790, 84_859)
    payload["facts"]["us-gaap"]["PaymentsToAcquirePropertyPlantAndEquipment"] = rows(35_674, 80_598)
    path.write_text(json.dumps(payload), encoding="utf-8")
    report = build_sec_financial_population(root)
    q2 = [row for row in report["quarterly_financial_facts"] if row["period_end"] == "2026-06-30"]
    assert q2 == []


def test_comparative_row_does_not_replace_original_fiscal_identity(tmp_path):
    root = _root(tmp_path)
    path = root / "data/generated/provider_cache/sec/companyfacts/CIK0000000001.json"
    payload = json.loads(path.read_text())
    payload["facts"]["us-gaap"]["EarningsPerShareDiluted"] = {"units": {"USD/shares": [
        {"val": 0.76, "start": "2025-01-27", "end": "2025-04-27", "filed": "2025-05-28", "form": "10-Q", "fy": 2026, "fp": "Q1", "accn": "original", "frame": "CY2025Q1"},
        {"val": 0.76, "start": "2025-01-27", "end": "2025-04-27", "filed": "2026-05-20", "form": "10-Q", "fy": 2027, "fp": "Q1", "accn": "comparative", "frame": "CY2025Q1"},
        {"val": 2.39, "start": "2026-01-26", "end": "2026-04-26", "filed": "2026-05-20", "form": "10-Q", "fy": 2027, "fp": "Q1", "accn": "current", "frame": "CY2026Q1"},
    ]}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    rows = [row for row in build_sec_financial_population(root)["quarterly_financial_facts"] if row["metric"] == "diluted_eps"]
    assert [(row["fiscal_year"], row["period_end"], row["accession_number"]) for row in rows] == [
        (2026, "2025-04-27", "comparative"), (2027, "2026-04-26", "current")
    ]


def test_q4_derivation_never_subtracts_weighted_average_shares(tmp_path):
    root = _root(tmp_path)
    path = root / "data/generated/provider_cache/sec/companyfacts/CIK0000000001.json"
    payload = json.loads(path.read_text())
    payload["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"] = {
        "units": {"shares": [
            {"val": 100, "start": "2025-01-01", "end": "2025-03-31", "filed": "2025-04-20", "form": "10-Q", "fy": 2025, "fp": "Q1", "accn": "q1"},
            {"val": 101, "start": "2025-04-01", "end": "2025-06-30", "filed": "2025-07-20", "form": "10-Q", "fy": 2025, "fp": "Q2", "accn": "q2"},
            {"val": 102, "start": "2025-07-01", "end": "2025-09-30", "filed": "2025-10-20", "form": "10-Q", "fy": 2025, "fp": "Q3", "accn": "q3"},
            {"val": 101, "start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-01", "form": "10-K", "fy": 2025, "fp": "FY", "accn": "fy"},
        ]}
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    shares = [row for row in build_sec_financial_population(root)["quarterly_financial_facts"] if row["metric"] == "diluted_shares_outstanding"]
    assert all(row["fiscal_period"] != "Q4" for row in shares)
    assert all(Decimal(row["value"]) > 0 for row in shares)


def test_foreign_issuer_6k_discrete_quarter_is_retained(tmp_path):
    root = _root(tmp_path)
    path = root / "data/generated/provider_cache/sec/companyfacts/CIK0000000001.json"
    payload = json.loads(path.read_text())
    payload["facts"]["us-gaap"]["EarningsPerShareDiluted"] = {"units": {"USD/shares": [
        {"val": 0.25, "start": "2026-04-01", "end": "2026-06-30", "filed": "2026-07-29", "form": "6-K", "fy": 2027, "fp": "Q1", "accn": "foreign-q1"}
    ]}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    eps = [row for row in build_sec_financial_population(root)["quarterly_financial_facts"] if row["metric"] == "diluted_eps"]
    assert [(row["period_end"], row["value"], row["form_type"]) for row in eps] == [("2026-06-30", "0.25", "6-K")]


def test_partial_writer_keeps_unaffected_company_history(tmp_path):
    output = tmp_path / "out"
    output.mkdir()
    (output / "financial_facts.json").write_text(json.dumps([{"company_id": "company:old", "metric": "revenue"}]))
    (output / "quarterly_index.json").write_text(json.dumps({"company_id_to_file": {"company:old": "quarterly/old.json"}}))
    report = build_sec_financial_population(_root(tmp_path), company_ids=["company:1"])
    write_sec_financial_population(report, output, merge_existing=True)
    assert "company:old" in {row["company_id"] for row in json.loads((output / "financial_facts.json").read_text())}
    assert "company:old" in json.loads((output / "quarterly_index.json").read_text())["company_id_to_file"]
