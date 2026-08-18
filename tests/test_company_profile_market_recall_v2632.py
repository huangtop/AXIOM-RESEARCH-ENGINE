from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/census_company_profile_market_recall_v2632.py"

spec = importlib.util.spec_from_file_location("market_recall_v2632", SCRIPT)
assert spec is not None
assert spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_v2632_classifies_explicit_market_language():
    sentence = "Our end markets include automotive, industrial and data center."
    assert "explicit_end_market" in module.classify_market_sentence(sentence)


def test_v2632_classifies_served_industries():
    sentence = "We serve customers in the healthcare and aerospace industries."
    families = module.classify_market_sentence(sentence)
    assert "serve_industry_market" in families


def test_v2632_classifies_application_context():
    sentence = "Our products are used in automotive safety applications."
    assert "application_context" in module.classify_market_sentence(sentence)


def test_v2632_does_not_flag_plain_demand_sentence_as_market_pattern():
    sentence = "Demand for artificial intelligence and cloud computing continues to grow."
    assert module.classify_market_sentence(sentence) == []


def test_v2632_marks_product_heavy_risk():
    sentence = "Our products are used in server DRAM applications."
    assert "product_heavy" in module.classify_risks(sentence)


def test_v2632_missing_market_records_uses_frontend_coverage():
    census = {
        "records": [
            {
                "symbol": "AAA",
                "company_id": "company:aaa",
                "coverage": {"frontend_markets": False},
                "readiness_reasons": ["missing_frontend_markets"],
            },
            {
                "symbol": "BBB",
                "company_id": "company:bbb",
                "coverage": {"frontend_markets": True},
                "readiness_reasons": [],
            },
        ]
    }
    rows = module.missing_market_records(census)
    assert [row["symbol"] for row in rows] == ["AAA"]


def test_v2632_latest_business_evidence_prefers_latest_supported_section():
    rows = [
        {"section_type": "item_1_business", "filing_date": "2025-01-01", "text": "Older business evidence."},
        {"section_type": "item_1_business", "filing_date": "2026-01-01", "text": "Newer business evidence."},
        {"section_type": "item_7_mda", "filing_date": "2026-02-01", "text": "Unsupported section."},
    ]
    latest = module.latest_business_evidence(rows)
    assert latest is not None
    assert latest["text"] == "Newer business evidence."


def test_v2632_analyze_company_finds_pattern_and_risk_flags():
    result = module.analyze_company(
        symbol="TEST",
        company_id="company:test",
        evidence_rows=[
            {
                "section_type": "item_1_business",
                "filing_date": "2026-01-01",
                "form": "10-K",
                "text": (
                    "Our products are used in server DRAM applications. "
                    "We continue to invest in manufacturing capacity."
                ),
            }
        ],
    )
    assert result["status"] == "market_like_evidence_found"
    assert result["candidate_sentence_count"] == 1
    candidate = result["candidate_sentences"][0]
    assert "application_context" in candidate["pattern_families"]
    assert "product_heavy" in candidate["risk_flags"]


def test_v2632_analyze_company_can_find_no_market_like_evidence():
    result = module.analyze_company(
        symbol="TEST",
        company_id="company:test",
        evidence_rows=[
            {
                "section_type": "item_1_business",
                "filing_date": "2026-01-01",
                "form": "10-K",
                "text": "The company develops software products. Revenue increased in 2025.",
            }
        ],
    )
    assert result["status"] == "no_market_like_evidence_found"
    assert result["candidate_sentences"] == []