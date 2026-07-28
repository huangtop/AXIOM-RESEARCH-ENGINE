from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from axiom_engine.sec_company_evidence import build_sec_company_evidence, write_sec_company_evidence


NOW = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)


def _registry(root: Path) -> None:
    path = root / "data/universe/companies.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps([
        {"company_id": "company:US-CIK0000000001", "metadata": {"cik": 1}},
        {"company_id": "company:US-CIK0000000002", "metadata": {"cik": 2}},
        {"company_id": "company:NON-US", "metadata": {}},
    ]), encoding="utf-8")


def _submission(cik: str) -> dict:
    return {
        "cik": cik,
        "sic": "3674",
        "sicDescription": "Semiconductors and Related Devices",
        "filings": {"recent": {
            "form": ["10-Q", "10-K/A", "10-K", "10-K"],
            "accessionNumber": ["0001-26-000004", "0001-26-000003", "0001-26-000002", "0001-25-000001"],
            "filingDate": ["2026-06-01", "2026-03-15", "2026-03-01", "2025-03-01"],
            "reportDate": ["2026-03-31", "2025-12-31", "2025-12-31", "2024-12-31"],
            "primaryDocument": ["q.htm", "amendment.htm", "annual.htm", "old.htm"],
        }},
    }


def test_bulk_projection_builds_sic_filing_manifest_provenance_and_coverage(tmp_path):
    _registry(tmp_path)
    archive = tmp_path / "submissions.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("CIK0000000001.json", json.dumps(_submission("0000000001")))
        output.writestr("CIK9999999999.json", json.dumps(_submission("9999999999")))
    report = build_sec_company_evidence(tmp_path, bulk_zip=archive, now=NOW)
    assert report["summary"] == {
        "registry_company_count": 3,
        "submissions_available_count": 1,
        "sic_classification_count": 1,
        "annual_filing_manifest_count": 1,
        "missing_submissions_count": 2,
        "submissions_coverage_ratio": 0.333333,
        "sic_coverage_ratio": 0.333333,
        "annual_filing_coverage_ratio": 0.333333,
        "source_mode_counts": {"sec_bulk": 1},
    }
    classification = report["official_classifications"][0]
    assert classification["classification_scheme"] == "SEC_SIC"
    assert classification["classification_code"] == "3674"
    filing = report["filing_documents"][0]
    assert filing["form"] == "10-K"
    assert filing["filing_date"] == "2026-03-01"
    assert filing["document_url"].endswith("/000126000002/annual.htm")
    assert {row["reason_code"] for row in report["coverage_audit"]["missing_companies"]} == {"SEC_SUBMISSIONS_NOT_AVAILABLE", "REGISTRY_CIK_MISSING"}


def test_cache_precedes_bulk_and_outputs_are_separate_canonical_artifacts(tmp_path):
    _registry(tmp_path)
    cache = tmp_path / "data/generated/provider_cache/sec/submissions/CIK0000000001.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps(_submission("0000000001")), encoding="utf-8")
    report = build_sec_company_evidence(tmp_path, now=NOW)
    output = tmp_path / "out"
    write_sec_company_evidence(report, output)
    assert report["summary"]["source_mode_counts"] == {"cache": 1}
    assert {path.name for path in output.iterdir()} == {"manifest.json", "official_classifications.json", "filing_documents.json", "provenance.json", "coverage_audit.json"}
    assert not (tmp_path / "data/company_registry/business_descriptions.json").exists()


def test_no_cache_or_bulk_reports_missing_without_network_or_fabrication(tmp_path):
    _registry(tmp_path)
    report = build_sec_company_evidence(tmp_path, now=NOW)
    assert report["official_classifications"] == []
    assert report["filing_documents"] == []
    assert report["summary"]["missing_submissions_count"] == 3
