import json
from pathlib import Path
import pytest

from axiom_engine.company_profile_v2 import (
    build_company_profile_v2,
)


ROOT = Path(__file__).resolve().parents[1]


def _aaoi():
    return build_company_profile_v2(
        ROOT,
        symbol="AAOI",
    )


def test_aaoi_v2_is_evidence_first():
    row = _aaoi()

    assert row["symbol"] == "AAOI"
    assert row["generation_mode"] == "evidence_first_generic_extractor"

    assert "classification" not in row
    assert "theme" not in row
    assert "sector" not in row


def test_aaoi_preserves_business_detail():
    row = _aaoi()

    assert "Internet Data Center" in row["markets"]
    assert "CATV" in row["markets"]
    assert "Telecom" in row["markets"]
    assert "FTTH" in row["markets"]

    assert "optical transceivers" in (
        row["market_products"]["internet_data_center"]
    )
    assert "light engines" in (
        row["market_products"]["internet_data_center"]
    )

    assert "lasers" in row["market_products"]["catv"]
    assert "amplifiers" in row["market_products"]["catv"]

    assert "laser subassemblies" in (
        row["market_products"]["telecom"]
    )


def test_aaoi_preserves_manufacturing_and_technology():
    row = _aaoi()

    assert "Molecular Beam Epitaxy (MBE)" in row["core_technologies"]
    assert (
        "Metal Organic Chemical Vapor Deposition (MOCVD)"
        in row["core_technologies"]
    )

    assert "vertically integrated" in row["manufacturing"]["model"]
    assert "highly automated" in row["manufacturing"]["model"]

    assert {
        "United States",
        "Taiwan",
        "China",
    }.issubset(set(row["manufacturing"]["locations"]))

    asset = row["manufacturing"]["critical_assets"][0]

    assert asset["asset"] == "laser chip manufacturing"
    assert asset["location"] == "Sugar Land, Texas"


def test_aaoi_preserves_ai_and_strategy():
    row = _aaoi()

    assert row["ai_exposure"]["type"] == "direct_company_disclosure"
    assert "800Gbps" in row["ai_exposure"]["summary"]

    assert "AI" in row["demand_drivers"]
    assert "DOCSIS 4.0" in row["demand_drivers"]
    assert "5G" in row["demand_drivers"]
    assert "PON" in row["demand_drivers"]

    assert row["strategy_changes"][0]["brand"] == "Quantum Bandwidth"


def test_aaoi_preserves_2025_financial_facts():
    row = _aaoi()
    facts = row["financial_snapshot"]

    assert facts["revenue"] == 455_700_000
    assert facts["gross_margin"] == pytest.approx(0.30)
    assert facts["net_loss"] == 38_200_000

    assert facts["revenue_mix"]["CATV"] == pytest.approx(0.538)
    assert facts["revenue_mix"]["Internet Data Center"] == pytest.approx(0.429)

    assert facts["customer_concentration"]["Digicomm"] == pytest.approx(0.531)
    assert facts["customer_concentration"]["Microsoft"] == pytest.approx(0.288)

def test_v21_core_has_no_company_specific_rules():
    source = (
        ROOT
        / "src/axiom_engine/company_profile_v2/core.py"
    ).read_text()

    forbidden = [
        "Applied Optoelectronics",
        "JinkoSolar",
        'symbol == "AAOI"',
        "symbol == 'AAOI'",
        'symbol == "NVDA"',
        "company:US-CIK0001158114",
    ]

    for value in forbidden:
        assert value not in source


def test_nvda_uses_same_generic_extractor():
    row = build_company_profile_v2(
        ROOT,
        symbol="NVDA",
    )

    assert row["symbol"] == "NVDA"

    assert row["generation_mode"] == (
        "evidence_first_generic_extractor"
    )

    summary = (
        row["company_summary"]
        ["one_line_business"]
        or ""
    )

    assert "accelerated computing" in summary.lower()

    markets = set(row["markets"])

    assert {
        "Data Center",
        "Gaming",
        "Professional Visualization",
        "Automotive",
    }.issubset(markets)

    assert row["evidence"]
    assert (
        row["evidence"][0]["form"]
        == "10-K"
    )

def test_v22_has_per_value_provenance():
    row = _aaoi()

    assert (
        row["schema_version"]
        == "axiom-company-profile.v2.2"
    )

    provenance = row[
        "value_provenance"
    ]

    assert provenance["markets"]

    by_value = {
        item["value"]: item
        for item
        in provenance["markets"]
    }

    assert "CATV" in by_value
    assert "Internet Data Center" in by_value

    catv = by_value["CATV"]

    assert catv["evidence"] is not None
    assert (
        catv["evidence"]
        ["business_evidence_id"]
        == row["evidence"][0]
        ["business_evidence_id"]
    )
    assert catv["evidence"]["quote"]


def test_v22_provenance_span_is_exact_source_text():
    row = _aaoi()

    company_id = row["company_id"]

    index = json.loads(
        (
            ROOT
            / "data/generated/canonical_business_evidence/index.json"
        ).read_text()
    )

    rel = (
        index["company_id_to_file"]
        [company_id]
    )

    evidence_rows = json.loads(
        (
            ROOT
            / "data/generated/canonical_business_evidence"
            / rel
        ).read_text()
    )

    raw_text = evidence_rows[0]["text"]

    catv = next(
        item
        for item
        in row[
            "value_provenance"
        ]["markets"]
        if item["value"] == "CATV"
    )

    evidence = catv["evidence"]

    start = evidence[
        "evidence_start_character"
    ]
    end = evidence[
        "evidence_end_character"
    ]

    assert raw_text[start:end] == (
        evidence["quote"]
    )


def test_v22_normalized_location_keeps_original_quote():
    row = _aaoi()

    locations = {
        item["value"]: item
        for item
        in row[
            "value_provenance"
        ][
            "manufacturing"
        ][
            "locations"
        ]
    }

    us = locations[
        "United States"
    ]

    assert us["evidence"] is not None

    quote = us[
        "evidence"
    ][
        "quote"
    ]

    assert (
        "U.S." in quote
        or "United States" in quote
    )

    assert "Taiwan" in quote
    assert "China" in quote


def test_v22_financial_values_have_source_provenance():
    row = _aaoi()

    financial = row[
        "value_provenance"
    ][
        "financial_snapshot"
    ]

    revenue = financial[
        "revenue"
    ]

    assert revenue["value"] == (
        455_700_000
    )

    assert revenue[
        "evidence"
    ] is not None

    assert "$455.7 million" in (
        revenue[
            "evidence"
        ][
            "quote"
        ]
    )

    mix = financial[
        "revenue_mix"
    ]

    assert (
        mix["CATV"]["value"]
        == pytest.approx(0.538)
    )

    assert (
        mix["Internet Data Center"]
        ["value"]
        == pytest.approx(0.429)
    )