from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from axiom_engine.sec_business_evidence import build_sec_business_evidence, extract_business_section, write_sec_business_evidence
from axiom_engine.business_evidence_store import load_business_evidence
from scripts.build_sec_business_evidence import _resume_company_ids


NOW = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)
BODY = " ".join(["We design ethernet switch, SerDes, and data center products."] * 20)


def _html(start: str = "ITEM 1. BUSINESS", end: str = "ITEM 1A. RISK FACTORS") -> bytes:
    return f"<html><script>ignore</script><h1>{start}</h1><p>{BODY}</p><h1>{end}</h1><p>risk</p></html>".encode()


def _manifest(root: Path) -> None:
    path = root / "data/generated/canonical_company_evidence/filing_documents.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps([{
        "filing_document_id": "filing-document:1",
        "company_id": "company:1",
        "form": "10-K",
        "accession_number": "0001-26-000001",
        "filing_date": "2026-03-01",
        "document_url": "https://www.sec.gov/example.htm",
    }]), encoding="utf-8")


def test_extracts_longest_item_one_business_section_and_preserves_source_text():
    result = extract_business_section(_html(), form="10-K")
    assert result["status"] == "available"
    assert result["section_type"] == "item_1_business"
    assert "ethernet switch" in result["text"]
    assert "risk" not in result["text"].lower()
    assert len(result["text_sha256"]) == 64


def test_accepts_combined_items_and_pipe_or_line_break_headings():
    combined = extract_business_section(_html("ITEMS 1. AND 2. BUSINESS AND PROPERTIES"), form="10-K")
    split = extract_business_section(_html("ITEM 1\nBusiness", "ITEM 1A | Risk Factors"), form="10-K")
    assert combined["status"] == "available"
    assert split["status"] == "available"


def test_extracts_foreign_issuer_item_four_company_information():
    result = extract_business_section(_html("ITEM 4. INFORMATION ON THE COMPANY", "ITEM 5. OPERATING AND FINANCIAL REVIEW"), form="20-F")
    assert result["status"] == "available"
    assert result["section_type"] == "item_4_company_information"


def test_missing_boundaries_and_short_sections_have_explicit_reasons():
    assert extract_business_section(b"<p>No headings</p>", form="10-K")["reason_code"] == "BUSINESS_SECTION_BOUNDARY_NOT_FOUND"
    short = extract_business_section(b"<h1>ITEM 1. BUSINESS</h1><p>short</p><h1>ITEM 1A. RISK FACTORS</h1>", form="10-K")
    assert short["reason_code"] == "BUSINESS_SECTION_TOO_SHORT"


def test_cache_first_builder_creates_evidence_without_network(tmp_path):
    _manifest(tmp_path)
    cache = tmp_path / "data/generated/provider_cache/sec/filing_documents/000126000001.html"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(_html())
    report = build_sec_business_evidence(tmp_path, now=NOW)
    assert report["summary"]["business_evidence_available"] == 1
    evidence = report["business_evidence"][0]
    assert evidence["acquisition_mode"] == "cache"
    assert evidence["company_id"] == "company:1"
    assert len(evidence["document_sha256"]) == 64


def test_offline_missing_document_is_diagnostic_not_fabricated(tmp_path):
    _manifest(tmp_path)
    report = build_sec_business_evidence(tmp_path, now=NOW)
    assert report["business_evidence"] == []
    assert report["diagnostics"][0]["reason_code"] == "FILING_DOCUMENT_NOT_CACHED"


def test_offset_supports_resumable_population_batches(tmp_path):
    _manifest(tmp_path)
    manifest = tmp_path / "data/generated/canonical_company_evidence/filing_documents.json"
    first = json.loads(manifest.read_text())[0]
    second = {**first, "company_id": "company:2", "accession_number": "0002-26-000001"}
    manifest.write_text(json.dumps([first, second]), encoding="utf-8")
    report = build_sec_business_evidence(tmp_path, offset=1, limit=1, now=NOW)
    assert report["summary"]["filings_requested"] == 1
    assert report["diagnostics"][0]["company_id"] == "company:2"


def test_selected_company_order_is_preserved_for_priority_batches(tmp_path):
    _manifest(tmp_path)
    manifest = tmp_path / "data/generated/canonical_company_evidence/filing_documents.json"
    first = json.loads(manifest.read_text())[0]
    second = {**first, "company_id": "company:2", "accession_number": "0002-26-000001"}
    manifest.write_text(json.dumps([first, second]), encoding="utf-8")
    report = build_sec_business_evidence(
        tmp_path,
        company_ids=["company:2", "company:1"],
        limit=1,
        now=NOW,
    )
    assert report["diagnostics"][0]["company_id"] == "company:2"


def test_resume_targets_uncovered_priority_candidates_first(tmp_path):
    output = tmp_path / "data/generated/canonical_business_evidence"
    output.mkdir(parents=True)
    (output / "business_evidence.json").write_text(
        json.dumps([{"company_id": "company:covered"}]), encoding="utf-8"
    )
    relevance = tmp_path / "data/generated/research_relevance_gate/research_relevance_gate.json"
    relevance.parent.mkdir(parents=True)
    relevance.write_text(
        json.dumps(
            {
                "records": [
                    {"company_id": "company:required", "status": "evidence_required"},
                    {"company_id": "company:priority", "status": "priority_candidate"},
                    {"company_id": "company:covered", "status": "priority_candidate"},
                    {"company_id": "company:excluded", "status": "deprioritized_non_research"},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert _resume_company_ids(
        tmp_path, Path("data/generated/canonical_business_evidence")
    ) == ["company:priority", "company:required"]


def test_resume_prioritizes_event_triggered_company_without_hardcoded_ticker(tmp_path):
    output = tmp_path / "data/generated/canonical_business_evidence"
    output.mkdir(parents=True)
    (output / "business_evidence.json").write_text("[]", encoding="utf-8")
    relevance = tmp_path / "data/generated/research_relevance_gate/research_relevance_gate.json"
    relevance.parent.mkdir(parents=True)
    relevance.write_text(json.dumps({"records": [
        {"company_id": "company:first-by-id", "status": "priority_candidate"},
        {"company_id": "company:event", "status": "priority_candidate"},
    ]}), encoding="utf-8")
    eligibility = tmp_path / "data/generated/research_eligibility/research_eligibility.json"
    eligibility.parent.mkdir(parents=True)
    eligibility.write_text(json.dumps({"records": [
        {"company_id": "company:event", "deep_research_triggers": [{"trigger_type": "sec_filing"}]}
    ]}), encoding="utf-8")
    assert _resume_company_ids(tmp_path, Path("data/generated/canonical_business_evidence"))[0] == "company:event"


def test_live_fetcher_can_populate_cache_incrementally(tmp_path):
    _manifest(tmp_path)
    calls = []

    def fetcher(url, user_agent):
        calls.append((url, user_agent))
        return _html()

    report = build_sec_business_evidence(tmp_path, allow_live=True, user_agent="AXIOM test@example.com", write_cache=True, request_delay_seconds=0, now=NOW, fetcher=fetcher)
    assert report["summary"]["documents_downloaded"] == 1
    assert calls == [("https://www.sec.gov/example.htm", "AXIOM test@example.com")]
    assert (tmp_path / "data/generated/provider_cache/sec/filing_documents/000126000001.html").is_file()


def test_writer_merges_resumable_batches_without_losing_prior_evidence(tmp_path):
    def report(company, evidence_id):
        return {"schema_version": "sec-business-evidence.v031.2b", "version": "V031.2B", "generated_at": NOW.isoformat(), "summary": {"business_evidence_available": 1, "business_evidence_unavailable": 0}, "business_evidence": [{"business_evidence_id": evidence_id, "company_id": company}], "diagnostics": []}

    output = tmp_path / "out"
    write_sec_business_evidence(report("company:1", "e1"), output)
    write_sec_business_evidence(report("company:2", "e2"), output, merge_existing=True)
    assert {row["company_id"] for row in load_business_evidence(output)} == {"company:1", "company:2"}
    assert json.loads((output / "manifest.json").read_text())["summary"]["cumulative_company_count"] == 2


def test_writer_retains_multiple_annual_accessions_for_same_company(tmp_path):
    def report(evidence_id):
        return {"schema_version": "sec-business-evidence.v031.2b", "version": "V031.2B", "generated_at": NOW.isoformat(), "summary": {}, "business_evidence": [{"business_evidence_id": evidence_id, "company_id": "company:1"}], "diagnostics": []}

    output = tmp_path / "out"
    write_sec_business_evidence(report("business-evidence:SEC:2025"), output)
    write_sec_business_evidence(report("business-evidence:SEC:2026"), output, merge_existing=True)
    assert {row["business_evidence_id"] for row in load_business_evidence(output)} == {
        "business-evidence:SEC:2025", "business-evidence:SEC:2026"
    }


def test_40f_uses_attributable_annual_report_exhibit_fallback(tmp_path):
    _manifest(tmp_path)
    manifest = tmp_path / "data/generated/canonical_company_evidence/filing_documents.json"
    row = json.loads(manifest.read_text())[0]
    row.update({"form": "40-F", "primary_document": "wrapper.htm"})
    manifest.write_text(json.dumps([row]), encoding="utf-8")
    submission = b"<DOCUMENT>\n<TYPE>EX-99.1\n<FILENAME>annual.htm\n<DESCRIPTION>Annual Report\n</DOCUMENT>"

    def fetcher(url, user_agent):
        if url.endswith("example.htm"):
            return b"<p>40-F wrapper only</p>"
        if url.endswith("0001-26-000001.txt"):
            return submission
        if url.endswith("annual.htm"):
            return _html("ITEM 4. INFORMATION ON THE COMPANY", "ITEM 5. OPERATING AND FINANCIAL REVIEW")
        raise AssertionError(url)

    report = build_sec_business_evidence(tmp_path, allow_live=True, user_agent="AXIOM test@example.com", request_delay_seconds=0, now=NOW, fetcher=fetcher)
    assert report["summary"]["business_evidence_available"] == 1
    assert report["business_evidence"][0]["document_url"].endswith("/annual.htm")
    assert report["business_evidence"][0]["section_type"] == "item_4_company_information"
