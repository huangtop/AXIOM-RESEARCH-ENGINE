from __future__ import annotations

from pathlib import Path

from axiom_engine.company_profile_v2.core import (
    _extract_generic_offerings,
    _extract_product_stack,
)

from axiom_engine.company_profile_v2 import (
    build_company_profile_v2,
)


ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)


def test_v2621_extracts_products_include():
    text = (
        "Our products include GPUs, "
        "network adapters, and processors."
    )

    values, evidence = (
        _extract_generic_offerings(
            text
        )
    )

    assert "GPUs" in values
    assert "network adapters" in values
    assert "processors" in values
    assert evidence


def test_v2621_extracts_services_and_solutions():
    text = (
        "We offer cloud services, "
        "security solutions, and "
        "data analytics software."
    )

    values, evidence = (
        _extract_generic_offerings(
            text
        )
    )

    assert "cloud services" in values
    assert "security solutions" in values
    assert "data analytics software" in values
    assert evidence


def test_v2621_extracts_commercial_manufacturing_statement():
    text = (
        "We design, develop, manufacture "
        "and sell semiconductor devices, "
        "power modules, and controllers."
    )

    values, _ = (
        _extract_generic_offerings(
            text
        )
    )

    assert "semiconductor devices" in values
    assert "power modules" in values
    assert "controllers" in values


def test_v2621_rejects_employee_benefits():
    text = (
        "We offer employees competitive salaries, "
        "bonuses, mental health support, "
        "and development programs."
    )

    values, _ = (
        _extract_generic_offerings(
            text
        )
    )

    assert values == []


def test_v2621_rejects_investor_relations_noise():
    text = (
        "We provide notifications of news, "
        "SEC filings, investor events, "
        "press releases, and earnings releases."
    )

    values, _ = (
        _extract_generic_offerings(
            text
        )
    )

    assert values == []


def test_v2621_rejects_distribution_channels():
    text = (
        "We sell our products through "
        "independent distributors, "
        "sales representatives, retailers, "
        "and channel partners."
    )

    values, _ = (
        _extract_generic_offerings(
            text
        )
    )

    assert values == []


def test_v2621_rejects_esg_volunteering():
    text = (
        "We provide company-matched donations "
        "and opportunities for volunteering."
    )

    values, _ = (
        _extract_generic_offerings(
            text
        )
    )

    assert values == []


def test_v2621_does_not_promote_customer_or_demand_language():
    text = (
        "Our customers include cloud providers "
        "and OEMs. Demand for artificial "
        "intelligence continues to grow."
    )

    values, _ = (
        _extract_generic_offerings(
            text
        )
    )

    assert values == []


def test_v2621_preserves_existing_aaoi_product_stack():
    profile = (
        build_company_profile_v2(
            ROOT,
            symbol="AAOI",
        )
    )

    assert profile[
        "product_stack"
    ]

    assert (
        profile[
            "value_provenance"
        ].get(
            "product_stack"
        )
    )


def test_v2621_full_product_stack_dedupes():
    text = (
        "Our products include processors, "
        "accelerators, and processors. "
        "We offer accelerators, "
        "network adapters, and processors."
    )

    values, evidence = (
        _extract_product_stack(
            text
        )
    )

    assert values.count(
        "processors"
    ) == 1

    assert values.count(
        "accelerators"
    ) == 1

    assert (
        "network adapters"
        in values
    )

    assert evidence

def test_v2622_preserves_descriptor_chain():
    text = (
        "We offer high-speed, "
        "high-bandwidth, "
        "low-latency networking solutions."
    )

    values, _ = (
        _extract_generic_offerings(
            text
        )
    )

    assert values == [
        (
            "high-speed, high-bandwidth, "
            "low-latency networking solutions"
        )
    ]


def test_v2622_rejects_fragment_candidates():
    text = (
        "We offer fast, designed, complete, "
        "and software."
    )

    values, _ = (
        _extract_generic_offerings(
            text
        )
    )

    assert values == [
        "software"
    ]


def test_v2622_rejects_acquisition_tail():
    text = (
        "We provide RISC-V expertise, "
        "with the acquisition of MIPS Holding, Inc."
    )

    values, _ = (
        _extract_generic_offerings(
            text
        )
    )

    assert (
        "with the acquisition of MIPS Holding"
        not in values
    )

    assert "Inc" not in values


def test_v2622_rejects_customer_channel_tail():
    text = (
        "We sell chipset products to AIB "
        "manufacturers who in turn build "
        "graphics cards."
    )

    values, _ = (
        _extract_generic_offerings(
            text
        )
    )

    assert values == [
        "chipset products"
    ]


def test_v2622_rejects_major_end_market_list():
    text = (
        "We offer semiconductor-based solutions "
        "in five major end markets: "
        "Networking Connectivity, "
        "Wireless Device Connectivity, "
        "Servers, Storage Systems, "
        "Broadband and Industrial."
    )

    values, _ = (
        _extract_generic_offerings(
            text
        )
    )

    assert values == []


def test_v2622_keeps_real_single_product_nouns():
    text = (
        "Our products include software, "
        "filters, sensors, and wafers."
    )

    values, _ = (
        _extract_generic_offerings(
            text
        )
    )

    assert "software" in values
    assert "filters" in values
    assert "sensors" in values
    assert "wafers" in values

def test_v2623_rejects_geography_fragments():
    values = [
        "South America",
        "South Korea",
        "New Zealand",
    ]

    from axiom_engine.company_profile_v2.core import (
        _offering_candidate_allowed,
    )

    for value in values:
        assert (
            _offering_candidate_allowed(
                value
            )
            is False
        )


def test_v2623_rejects_customer_groups():
    from axiom_engine.company_profile_v2.core import (
        _offering_candidate_allowed,
    )

    values = [
        "service provider",
        "mobility service providers",
        "directly to Telcos or other service providers",
    ]

    for value in values:
        assert (
            _offering_candidate_allowed(
                value
            )
            is False
        )


def test_v2623_rejects_action_fragments():
    from axiom_engine.company_profile_v2.core import (
        _offering_candidate_allowed,
    )

    values = [
        "is action-oriented",
        "addressing both training",
        "execute their hardware code",
        "mostly used by customers in laboratories",
    ]

    for value in values:
        assert (
            _offering_candidate_allowed(
                value
            )
            is False
        )


def test_v2623_rejects_capability_as_offering():
    from axiom_engine.company_profile_v2.core import (
        _offering_candidate_allowed,
    )

    values = [
        (
            "pharmaceutical customers specialized "
            "manufacturing capabilities for "
            "targeted therapeutics"
        ),
        "RISC-V expertise",
    ]

    for value in values:
        assert (
            _offering_candidate_allowed(
                value
            )
            is False
        )


def test_v2623_rejects_generic_incomplete_platform_phrases():
    from axiom_engine.company_profile_v2.core import (
        _offering_candidate_allowed,
    )

    values = [
        "two types of platforms",
        "family of high performance",
        "product families with secure",
    ]

    for value in values:
        assert (
            _offering_candidate_allowed(
                value
            )
            is False
        )


def test_v2623_preserves_real_products():
    from axiom_engine.company_profile_v2.core import (
        _offering_candidate_allowed,
    )

    values = [
        "AI accelerators",
        "adaptive SoCs",
        "power management ICs",
        "air handling units",
        "managed NAND",
        "RF front-end modules",
        "hardware-based accelerator solutions for PQC",
        "end-to-end accelerated computing platform for AI",
    ]

    for value in values:
        assert (
            _offering_candidate_allowed(
                value
            )
            is True
        )