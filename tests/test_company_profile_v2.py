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
    assert row["generation_mode"] == "evidence_first_deterministic"

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