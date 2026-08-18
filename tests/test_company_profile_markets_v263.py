from __future__ import annotations

from pathlib import Path

from axiom_engine.company_profile_v2.core import (
    _extract_generic_markets,
    _extract_markets,
    _market_candidate_allowed,
)

from axiom_engine.company_profile_v2 import (
    build_company_profile_v2,
)


ROOT = Path(__file__).resolve().parents[1]


def test_v263_extracts_explicit_end_markets():
    text = (
        "Our end markets include automotive, "
        "industrial, communications and data center."
    )

    values, evidence = _extract_generic_markets(
        text
    )

    assert "Automotive" in values
    assert "Industrial" in values
    assert "Communications" in values
    assert "Data Center" in values
    assert evidence


def test_v263_extracts_markets_we_serve():
    text = (
        "Markets we serve include healthcare, "
        "aerospace, defense and telecommunications."
    )

    values, _ = _extract_generic_markets(
        text
    )

    assert "Healthcare" in values
    assert "Aerospace" in values
    assert "Defense" in values
    assert "Telecom" in values


def test_v263_extracts_served_industries():
    text = (
        "Industries we serve include automotive, "
        "industrial automation, medical devices "
        "and energy."
    )

    values, _ = _extract_generic_markets(
        text
    )

    assert "Automotive" in values
    assert "Industrial Automation" in values
    assert "Medical Devices" in values
    assert "Energy" in values


def test_v263_rejects_geographies():
    for value in [
        "United States",
        "China",
        "Europe",
        "South Korea",
        "New Zealand",
    ]:
        assert (
            _market_candidate_allowed(value)
            is False
        )


def test_v263_does_not_promote_customer_types():
    text = (
        "Our customers include cloud providers, "
        "OEMs, distributors and system integrators."
    )

    values, _ = _extract_generic_markets(
        text
    )

    assert values == []


def test_v263_does_not_promote_demand_drivers():
    text = (
        "Demand for artificial intelligence, "
        "cloud computing and bandwidth "
        "continues to grow rapidly."
    )

    values, _ = _extract_generic_markets(
        text
    )

    assert values == []


def test_v263_preserves_nvda_markets():
    profile = build_company_profile_v2(
        ROOT,
        symbol="NVDA",
    )

    assert profile["markets"]
    assert profile[
        "value_provenance"
    ].get("markets")


def test_v263_preserves_aaoi_markets():
    profile = build_company_profile_v2(
        ROOT,
        symbol="AAOI",
    )

    assert profile["markets"]


def test_v263_generic_and_legacy_paths_dedupe():
    text = (
        "Our end markets include data center "
        "and automotive. "
        "Target markets include "
        "Data Center and Automotive."
    )

    values, evidence = _extract_markets(
        text
    )

    assert values.count(
        "Data Center"
    ) == 1

    assert values.count(
        "Automotive"
    ) == 1

    assert evidence


def test_v2631_rejects_generic_actor_fragments():
    values = [
        "Diverse",
        "Partners",
        "By Third-Party Developers",
    ]

    for value in values:
        assert (
            _market_candidate_allowed(
                value
            )
            is False
        )


def test_v2631_rejects_product_technology_terms():
    values = [
        "CPUs",
        "CUDA",
        "High-Capacity Dual In-Line Memory Modules",
        "Low-Power Server DRAM Solutions",
    ]

    for value in values:
        assert (
            _market_candidate_allowed(
                value
            )
            is False
        )


def test_v2631_rejects_demand_prose_fragments():
    values = [
        "Driven By Server Demand Across The Cloud",
        (
            "Networking Technologies As "
            "The Fundamental Building Blocks"
        ),
    ]

    for value in values:
        assert (
            _market_candidate_allowed(
                value
            )
            is False
        )


def test_v2631_preserves_real_end_markets():
    values = [
        "Data Center",
        "Gaming",
        "Professional Visualization",
        "Automotive",
        "Networking Connectivity",
        "Wireless Device Connectivity",
        "Servers",
        "Storage Systems",
        "Broadband",
        "Industrial",
        "Communications Infrastructure & Data Center",
    ]

    for value in values:
        assert (
            _market_candidate_allowed(
                value
            )
            is True
        )

# === V2.6.3.3 MARKET RECALL PROMOTION TIER 1 ===


def test_v2633_extracts_primary_markets():
    text = (
        "Our primary markets include aerospace, "
        "defense and healthcare."
    )

    values, evidence = _extract_generic_markets(
        text
    )

    assert "Aerospace" in values
    assert "Defense" in values
    assert "Healthcare" in values
    assert evidence


def test_v2633_extracts_principal_markets():
    text = (
        "Principal markets consist of automotive, "
        "industrial automation and energy."
    )

    values, _ = _extract_generic_markets(
        text
    )

    assert "Automotive" in values
    assert "Industrial Automation" in values
    assert "Energy" in values


def test_v2633_extracts_generic_market_list():
    text = (
        "Markets include data center, "
        "telecommunications and industrial."
    )

    values, _ = _extract_generic_markets(
        text
    )

    assert "Data Center" in values
    assert "Telecom" in values
    assert "Industrial" in values


def test_v2633_extracts_market_such_as_list():
    text = (
        "We participate in markets such as "
        "automotive, healthcare and aerospace."
    )

    values, _ = _extract_generic_markets(
        text
    )

    assert "Automotive" in values
    assert "Healthcare" in values
    assert "Aerospace" in values


def test_v2633_extracts_industry_list():
    text = (
        "Industries include medical devices, "
        "industrial automation and energy."
    )

    values, _ = _extract_generic_markets(
        text
    )

    assert "Medical Devices" in values
    assert "Industrial Automation" in values
    assert "Energy" in values


def test_v2633_extracts_serves_industries_without_we_prefix():
    text = (
        "The company serves the automotive, "
        "industrial and healthcare industries."
    )

    values, _ = _extract_generic_markets(
        text
    )

    assert "Automotive" in values
    assert "Industrial" in values
    assert "Healthcare" in values


def test_v2633_does_not_promote_internal_segment_lists():
    texts = [
        (
            "Our reportable segments include "
            "Cloud, Consumer and Other."
        ),
        (
            "Our operating segments include "
            "North America and International."
        ),
        (
            "Business segments include "
            "Products and Services."
        ),
    ]

    for text in texts:
        values, _ = _extract_generic_markets(
            text
        )

        assert values == []


def test_v2633_preserves_market_context_guard():
    text = (
        "Markets include CPUs, CUDA, "
        "DRAM modules and South Korea."
    )

    values, _ = _extract_generic_markets(
        text
    )

    assert values == []
