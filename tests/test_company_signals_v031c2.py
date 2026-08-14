from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from axiom_engine.company_signals import CompanySignalsError, build_company_signals


ROOT = Path(__file__).resolve().parents[1]


def _write(root: Path, relative: str, payload) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(tmp_path: Path) -> Path:
    rules = json.loads((ROOT / "config/company_signal_rules.v031c.2.json").read_text())
    _write(tmp_path, "config/company_signal_rules.v031c.2.json", rules)
    _write(tmp_path, "data/universe/companies.json", [{"company_id": "company:1"}, {"company_id": "company:2"}])
    _write(tmp_path, "data/generated/canonical_business_evidence/business_evidence.json", [{
        "business_evidence_id": "business-evidence:1",
        "company_id": "company:1",
        "provenance_id": "provenance:1",
        "accession_number": "accession:1",
        "filing_date": "2026-01-01",
        "text": "We design optical transceivers for data center interconnect and silicon photonics applications.",
    }])
    return tmp_path


def test_extracts_traceable_multidimensional_signals_without_ticker_membership(tmp_path: Path):
    report = build_company_signals(_fixture(tmp_path), now=datetime(2026, 1, 2, tzinfo=timezone.utc))
    record = report["records"][0]
    assert {row["signal_id"] for row in record["signals"]} >= {
        "technology:silicon_photonics", "product:optical_transceiver", "end_market:data_center", "capability:high_speed_data_center_networking"
    }
    location = next(row for row in record["signals"] if row["signal_id"] == "technology:silicon_photonics")["locations"][0]
    assert location["business_evidence_id"] == "business-evidence:1"
    assert location["matched_text"] == "silicon photonics"
    assert report["policy"]["contains_ticker_membership"] is False


def test_preserves_company_with_unavailable_business_evidence(tmp_path: Path):
    report = build_company_signals(_fixture(tmp_path))
    assert report["records"][1] == {
        "company_id": "company:2", "status": "business_evidence_unavailable", "source_business_evidence_ids": [], "signals": []
    }


def test_excludes_incidental_ai_adoption_and_media_asset_contexts(tmp_path: Path):
    root = _fixture(tmp_path)
    evidence_path = root / "data/generated/canonical_business_evidence/business_evidence.json"
    evidence = json.loads(evidence_path.read_text())
    evidence[0]["text"] = (
        "We are exploring the benefits of AI for our business with generative AI partners. "
        "We support and invest in emerging technologies, including artificial intelligence. "
        "We provide digital assets for our music to streaming services and downloads."
    )
    evidence_path.write_text(json.dumps(evidence))

    report = build_company_signals(root)
    signal_ids = {row["signal_id"] for row in report["records"][0]["signals"]}

    assert "technology:artificial_intelligence" not in signal_ids
    assert "technology:digital_assets" not in signal_ids


def test_legal_company_name_followed_by_offering_verb_marks_primary_business(tmp_path: Path):
    root = _fixture(tmp_path)
    companies_path = root / "data/universe/companies.json"
    companies = json.loads(companies_path.read_text())
    companies[0]["legal_name"] = "Example Consulting Limited"
    companies_path.write_text(json.dumps(companies))
    evidence_path = root / "data/generated/canonical_business_evidence/business_evidence.json"
    evidence = json.loads(evidence_path.read_text())
    evidence[0]["text"] = (
        "Example Consulting Limited provides AI-first business consulting and "
        "technology services to global enterprises."
    )
    evidence_path.write_text(json.dumps(evidence))

    report = build_company_signals(root)
    signal = next(
        row
        for row in report["records"][0]["signals"]
        if row["signal_id"] == "product:it_consulting_services"
    )

    assert signal["offering_occurrence_count"] >= 1
    assert signal["primary_business_score"] == 3


def test_rejects_duplicate_signal_rules(tmp_path: Path):
    root = _fixture(tmp_path)
    policy_path = root / "config/company_signal_rules.v031c.2.json"
    policy = json.loads(policy_path.read_text())
    policy["signals"].append(policy["signals"][0])
    policy_path.write_text(json.dumps(policy))
    with pytest.raises(CompanySignalsError, match="duplicate"):
        build_company_signals(root)


def test_rejects_ticker_membership_in_rules(tmp_path: Path):
    root = _fixture(tmp_path)
    policy_path = root / "config/company_signal_rules.v031c.2.json"
    policy = json.loads(policy_path.read_text())
    policy["signals"][0]["symbols"] = ["NVDA"]
    policy_path.write_text(json.dumps(policy))
    with pytest.raises(CompanySignalsError, match="membership is forbidden"):
        build_company_signals(root)


def test_real_population_is_complete_and_only_uses_canonical_business_evidence():
    report = build_company_signals(ROOT)
    assert report["summary"]["company_count"] == 6464
    assert report["summary"]["business_evidence_company_count"] >= 1000
    assert len(report["records"]) == 6464
