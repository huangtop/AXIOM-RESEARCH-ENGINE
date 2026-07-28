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
    cache = write(tmp_path, "data/generated/provider_cache/sec/submissions/CIK0000000001.json", {"filings": {"recent": {"form": ["10-K"], "filingDate": ["2026-02-01"], "reportDate": ["2025-12-31"], "accessionNumber": ["same"], "isXBRL": [1]}}})
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
