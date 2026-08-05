import json
from datetime import date, datetime, timezone
from pathlib import Path

from axiom_engine.sec_filing_refresh import build_sec_filing_refresh_plan


def write(root: Path, relative: str, payload):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def test_new_sec_accession_triggers_companyfacts_refresh_without_yahoo_calendar(tmp_path: Path):
    write(tmp_path, "data/universe/companies.json", [{"company_id": "c1", "metadata": {"cik": 1}}])
    write(tmp_path, "data/generated/canonical_financial_population/financial_facts.json", [{"company_id": "c1", "accession_number": "old"}])
    write(tmp_path, "data/generated/provider_cache/sec/submissions/CIK0000000001.json", {"filings": {"recent": {"form": ["10-Q"], "filingDate": ["2026-07-28"], "reportDate": ["2026-06-30"], "accessionNumber": ["new"], "isXBRL": [1]}}})
    report = build_sec_filing_refresh_plan(tmp_path, as_of=date.today())
    assert report["worklist"][0]["reason_codes"] == ["NEW_FINANCIAL_FILING_ACCESSION"]
    assert report["policy"]["yahoo_earnings_calendar_role"] == "advisory_only"


def test_known_accession_does_not_refresh_before_safety_ttl(tmp_path: Path):
    write(tmp_path, "data/universe/companies.json", [{"company_id": "c1", "metadata": {"cik": 1}}])
    write(tmp_path, "data/generated/canonical_financial_population/financial_facts.json", [{"company_id": "c1", "accession_number": "same"}])
    cache = write(tmp_path, "data/generated/provider_cache/sec/submissions/CIK0000000001.json", {"filings": {"recent": {"form": ["10-Q"], "filingDate": ["2026-02-01"], "reportDate": ["2025-12-31"], "accessionNumber": ["same"], "isXBRL": [1]}}})
    today = datetime.now(timezone.utc).timestamp()
    cache.touch()
    report = build_sec_filing_refresh_plan(tmp_path, as_of=datetime.fromtimestamp(today, timezone.utc).date())
    assert report["worklist"] == []


def test_accession_already_in_raw_companyfacts_is_treated_as_consumed(tmp_path: Path):
    write(tmp_path, "data/universe/companies.json", [{"company_id": "c1", "metadata": {"cik": 1}}])
    write(tmp_path, "data/generated/canonical_financial_population/financial_facts.json", [])
    write(tmp_path, "data/generated/provider_cache/sec/submissions/CIK0000000001.json", {"filings": {"recent": {"form": ["10-Q"], "filingDate": ["2026-07-28"], "reportDate": ["2026-06-30"], "accessionNumber": ["new"], "isXBRL": [1]}}})
    write(tmp_path, "data/generated/provider_cache/sec/companyfacts/CIK0000000001.json", {"facts": {"us-gaap": {"Revenue": {"units": {"USD": [{"accn": "new", "val": 1}]}}}}})
    assert build_sec_filing_refresh_plan(tmp_path, as_of=date.today())["worklist"] == []


def test_accession_ledger_prevents_repeat_and_annual_filing_requests_business_evidence(tmp_path: Path):
    write(tmp_path, "data/universe/companies.json", [{"company_id": "c1", "metadata": {"cik": 1}}])
    write(tmp_path, "data/generated/canonical_financial_population/financial_facts.json", [])
    write(tmp_path, "data/generated/provider_cache/sec/submissions/CIK0000000001.json", {"filings": {"recent": {
        "form": ["10-K", "10-Q"], "filingDate": ["2026-02-01", "2025-11-01"],
        "reportDate": ["2025-12-31", "2025-09-30"], "accessionNumber": ["annual-new", "quarter-done"], "isXBRL": [1, 1],
    }}})
    write(tmp_path, "data/generated/sec_filing_refresh/accession_ledger.json", {
        "processed_accessions": [{"accession_number": "quarter-done"}]
    })
    row = build_sec_filing_refresh_plan(tmp_path, as_of=date.today())["worklist"][0]
    assert [item["accession_number"] for item in row["pending_filings"]] == ["annual-new"]
    assert row["requires_business_evidence_refresh"] is True


def test_annual_accession_retries_until_business_evidence_is_saved(tmp_path: Path):
    write(tmp_path, "data/universe/companies.json", [{"company_id": "c1", "metadata": {"cik": 1}}])
    write(tmp_path, "data/generated/canonical_financial_population/financial_facts.json", [{"company_id": "c1", "accession_number": "annual"}])
    write(tmp_path, "data/generated/sec_filing_refresh/accession_ledger.json", {"processed_accessions": [{
        "accession_number": "annual", "financial_processed_at": "2026-02-01T00:00:00Z", "business_evidence_processed_at": None,
    }]})
    write(tmp_path, "data/generated/provider_cache/sec/submissions/CIK0000000001.json", {"filings": {"recent": {
        "form": ["10-K"], "filingDate": ["2026-02-01"], "reportDate": ["2025-12-31"], "accessionNumber": ["annual"], "isXBRL": [1],
    }}})
    report = build_sec_filing_refresh_plan(tmp_path, as_of=date.today())
    assert report["worklist"][0]["requires_business_evidence_refresh"] is True
    assert report["worklist"][0]["requires_financial_refresh"] is False
    write(tmp_path, "data/generated/canonical_business_evidence/business_evidence.json", [{"accession_number": "annual"}])
    assert build_sec_filing_refresh_plan(tmp_path, as_of=date.today())["worklist"] == []


def test_preledger_annual_history_is_baselined_without_mass_evidence_replay(tmp_path: Path):
    write(tmp_path, "data/universe/companies.json", [{"company_id": "c1", "metadata": {"cik": 1}}])
    write(tmp_path, "data/generated/canonical_financial_population/financial_facts.json", [{"company_id": "c1", "accession_number": "historical-annual"}])
    write(tmp_path, "data/generated/provider_cache/sec/submissions/CIK0000000001.json", {"filings": {"recent": {
        "form": ["10-K"], "filingDate": ["2025-02-01"], "reportDate": ["2024-12-31"], "accessionNumber": ["historical-annual"], "isXBRL": [1],
    }}})
    report = build_sec_filing_refresh_plan(tmp_path, as_of=date.today())
    assert report["worklist"] == []
    assert report["summary"]["annual_evidence_refresh_company_count"] == 0


def test_quarterly_artifact_accession_bootstraps_without_false_daily_refresh(tmp_path: Path):
    write(tmp_path, "data/universe/companies.json", [{"company_id": "c1", "metadata": {"cik": 1}}])
    write(tmp_path, "data/generated/canonical_financial_population/financial_facts.json", [])
    write(tmp_path, "data/generated/canonical_financial_population/quarterly_index.json", {
        "company_id_to_file": {"c1": "quarterly/c1.json"}
    })
    write(tmp_path, "data/generated/canonical_financial_population/quarterly/c1.json", [{"accession_number": "quarter-known"}])
    write(tmp_path, "data/generated/provider_cache/sec/submissions/CIK0000000001.json", {"filings": {"recent": {
        "form": ["10-Q"], "filingDate": ["2026-05-01"], "reportDate": ["2026-03-31"], "accessionNumber": ["quarter-known"], "isXBRL": [1],
    }}})
    assert build_sec_filing_refresh_plan(tmp_path, as_of=date.today())["worklist"] == []
