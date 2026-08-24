from __future__ import annotations

import importlib.util
from pathlib import Path

from axiom_engine.company_profile_v2.core import build_company_profile_v2


ROOT = Path(__file__).resolve().parents[1]


def _production_builder_module():
    path = ROOT / "scripts/build_company_profiles_v2.py"
    spec = importlib.util.spec_from_file_location(
        "company_profile_production_builder",
        path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _profile(symbol: str) -> dict:
    profile = build_company_profile_v2(ROOT, symbol=symbol)
    return _production_builder_module()._enrich_profile_product_recall(profile)


def test_acls_market_and_technology_relations_are_semantic() -> None:
    profile = _profile("ACLS")

    bad_markets = {
        "Cost Of Ownership",
        "Equipment Performance",
        "Customer Support",
        "Capabilities",
        "Breadth Of Product Line",
        "Manufacturing Supply Chain For The Micro",
        "Nano-Electronics",
    }
    assert bad_markets.isdisjoint(profile["markets"])

    technologies = profile["core_technologies"]
    assert not any(
        marker in value
        for value in technologies
        for marker in ("SMIC", "SCC", "SEMI")
    )
    assert not any("dynamic random-access memory" in value for value in technologies)


def test_lite_location_and_product_roles_are_semantic() -> None:
    profile = _profile("LITE")

    assert "AI/ML infrastructure providers" not in profile["product_stack"]
    assert any(
        term in value.casefold()
        for value in profile["product_stack"]
        for term in ("optical", "photonic", "laser")
    )

    locations = profile["manufacturing"]["locations"]
    assert "Asia" in locations
    assert {
        "semiconductor",
        "microelectronics fabrication",
        "electric vehicle",
        "battery production",
        "metal cutting",
        "welding",
        "advanced manufacturing",
    }.isdisjoint(locations)


def test_mpwr_corporate_title_is_not_a_product() -> None:
    profile = _profile("MPWR")

    assert "Corporate Controller" not in profile["product_stack"]
    assert any(
        term in value.casefold()
        for value in profile["product_stack"]
        for term in ("current", "metal-oxide-semiconductor", "electronic systems")
    )


def test_actor_words_inside_product_names_are_retained() -> None:
    aiio = _profile("AIIO")
    audc = _profile("AUDC")

    assert "open cloud platform for various service providers" in aiio["product_stack"]
    assert {
        "Microsoft Operator Connect Accelerator",
        "Zoom Provider Exchange Accelerator",
        "Zoom Phone Provider Exchange Accelerator",
    }.issubset(audc["product_stack"])


def test_international_alone_does_not_make_technology_an_entity() -> None:
    profile = _profile("RDW")

    assert "International Berthing and Docking Mechanism (IBDM)" in profile[
        "core_technologies"
    ]


def test_existing_legitimate_manufacturing_geographies_survive() -> None:
    expected = {
        "AMAT": {
            "United States",
            "Singapore",
            "Japan",
            "China",
            "Korea",
            "Taiwan",
            "Israel",
            "Europe",
        },
        "AIRG": {"Vietnam", "China", "Taiwan", "Mexico", "United States"},
        "FSLR": {"United States", "Malaysia", "Vietnam", "India"},
        "LFUS": {
            "China",
            "France",
            "Germany",
            "India",
            "Ireland",
            "Italy",
            "Japan",
            "Mexico",
            "Philippines",
            "United States",
            "Vietnam",
        },
    }

    for symbol, locations in expected.items():
        profile = _profile(symbol)
        assert locations.issubset(profile["manufacturing"]["locations"])


def test_manufacturing_relation_noise_is_not_promoted_as_geography() -> None:
    assert _profile("ACMR")["manufacturing"]["locations"] == []
    assert _profile("HEI")["manufacturing"]["locations"] == []
    assert _profile("DCO")["manufacturing"]["locations"] == []
    assert _profile("ASYS")["manufacturing"]["locations"] == []
    assert _profile("AIR")["manufacturing"]["locations"] == []
    assert _profile("GILT")["manufacturing"]["locations"] == [
        "Sofia",
        "Bulgaria",
    ]


def test_manufacturing_precision_controls_remain_stable() -> None:
    assert _profile("LITE")["manufacturing"]["locations"] == ["Asia"]
    assert _profile("CTS")["manufacturing"]["locations"] == [
        "North America",
        "Asia",
        "Europe",
    ]

    for symbol in ("MPWR", "ERIC", "ARW"):
        assert _profile(symbol)["manufacturing"]["locations"] == []


def test_core_technology_entities_roles_and_fragments_are_rejected() -> None:
    rejected = {
        "ALAB": {"Restriction of Chemicals (REACH)"},
        "AEIS": {
            "Our strategy is to outgrow the wafer fabrication equipment (WFE)",
        },
        "HEI": {
            "Federal Aviation Administration (FAA)",
            "Our Electronic Technologies Group (ETG)",
            "FAA-qualified designated engineering representative (DER)",
            "Repair and Overhaul (MRO)",
            "FAA and European Aviation Safety Agency (EASA)",
        },
        "GLW": {
            "This glass has been optimized for oxide thin-film transistor (TFT)",
            "TFT backplanes through low temperature poly-silicon (LTPS)",
            "General Counsel at Worthington Steel Processing and Worthington Armstrong Venture (WAVE)",
        },
        "AIR": {
            "LLC (ADI)",
            "Aircraft Reconfig Technologies (ART)",
            "Federal Aviation Administration (FAA)",
            "Parts Manufacturer Approval (PMA)",
        },
    }

    for symbol, values in rejected.items():
        assert values.isdisjoint(_profile(symbol)["core_technologies"])


def test_owned_product_list_stops_before_descriptive_benefit_clause() -> None:
    products = set(_profile("ALAB")["product_stack"])

    assert {
        "Aries PCIe®/CXL® Smart DSP Retimers",
        "Leo CXL Memory Connectivity Controllers",
        "COSMOS software suite",
    }.issubset(products)
    assert {
        "are essential to enable higher PCIe/CXL data bandwidth",
        "lower latency interconnectivity between various heterogeneous compute processors",
        "network controllers",
    }.isdisjoint(products)


def test_owned_architecture_and_used_protocols_are_core_technologies() -> None:
    technologies = set(_profile("ALAB")["core_technologies"])

    assert "software-defined IC architecture" in technologies
    assert "Peripheral Component Interconnect Express" in technologies
    assert "Compute Express Link" in technologies
    assert "Restriction of Chemicals (REACH)" not in technologies


def test_core_technology_precision_controls_remain_stable() -> None:
    assert {
        "Point of Load (POL)",
        "Technical Surveillance Countermeasures (TSCM)",
    }.issubset(_profile("HEI")["core_technologies"])
    assert "optical physics" in _profile("GLW")["core_technologies"]
    assert "International Berthing and Docking Mechanism (IBDM)" in _profile(
        "RDW"
    )["core_technologies"]


def test_market_competition_actor_and_product_lists_are_rejected() -> None:
    rejected = {
        "AEIS": {
            "A Wide Variety Of Applications",
            "Highly Competitive",
            "Characterized By Rapid Technological Development",
            "Changing Customer Requirements",
        },
        "ARM": {
            "Various End",
            "Chips Used By A Wide Range Of Goods",
            "Main Server Chips",
            "Chips Used In Autonomous",
            "Other Mobile Chips",
        },
        "HEI": {
            "A Number Of Public",
            "Private Manufacturing",
            "Service Clients In A Broad Range Of",
        },
        "DCO": {
            "Products Used In Military",
            "General Economic Conditions",
            "Highly Competitive",
            "Services Are Affected By Varying Degrees Of Competition",
            "Heavy Industrial Manufacturing Systems",
            "Certain Medical",
        },
        "ENPH": {
            "Tesla",
            "Solaredge",
            "Huawei",
            "Byd Company Limited",
            "Wallbox N",
        },
        "GILT": {"SES", "Viasat", "Hispasat", "Amazon Leo"},
        "ASYS": {
            "Characterized By Rapidly Evolving Industry Standards",
            "Technological Change",
        },
    }

    for symbol, values in rejected.items():
        assert values.isdisjoint(_profile(symbol)["markets"])


def test_market_precision_controls_remain_stable() -> None:
    assert {"Medical Devices", "Aerospace"}.issubset(_profile("AEIS")["markets"])
    assert {"Smartphones", "Automotive", "Cloud Compute"}.issubset(
        _profile("ARM")["markets"]
    )
    assert _profile("ASYS")["markets"] == ["Ceramics", "Optics"]
    assert _profile("LITE")["markets"] == [
        "Printed Circuit Board Manufacturing",
        "Electric Vehicle Battery Production",
        "Solar Cell Production",
        "Flat Panel Display Fabrication",
        "Semiconductor Processing",
    ]
    assert _profile("MPWR")["markets"] == [
        "Storage And Computing",
        "Enterprise Data",
        "Automotive",
        "Communications",
        "Consumer",
        "Industrial",
    ]


def test_product_wrong_type_fragments_and_non_owned_lists_are_rejected() -> None:
    rejected = {
        "ACMR": {"modular platforms"},
        "ARM": {"Every Processor"},
        "CSCO": {
            "software or other intellectual property licensed from third parties",
            "available embedded on these new switches",
        },
        "GLW": {
            "monitors with larger-sized screens",
            "life sciences products under the Corning®",
            "Axygen® brands",
            "ClearCurve® ultra-bendable multimode fiber for private",
        },
        "ENPH": {
            "solar module products and racking systems",
            "communications on one intelligent platform",
        },
        "ASYS": {"these products to semiconductor device packaging"},
    }

    for symbol, values in rejected.items():
        assert values.isdisjoint(_profile(symbol)["product_stack"])


def test_product_precision_controls_remain_stable() -> None:
    assert {"scrubber", "Ultra ECP ap"}.issubset(_profile("ACMR")["product_stack"])
    assert {"Arm CPUs", "Arm compute platform"}.issubset(
        _profile("ARM")["product_stack"]
    )
    assert {"Cisco Smart Switches", "Catalyst 9000"}.issubset(
        _profile("CSCO")["product_stack"]
    )
    assert "Corning® EAGLE XG® Slim Glass" in _profile("GLW")["product_stack"]
    assert {"IQ® Load Controllers", "Proposal™ platform"}.issubset(
        _profile("ENPH")["product_stack"]
    )
    assert "Tensor Series Products" in _profile("ASYS")["product_stack"]
    assert _profile("LITE")["product_stack"]
    assert _profile("MPWR")["product_stack"]


def test_standalone_temporal_fragments_are_not_inline_model_products() -> None:
    expected = {
        "AIIO": {"Since 2023"},
        "CIEN": {"February 2017"},
        "FRSX": {
            "July 2024",
            "January 2025",
            "July 2023",
            "April 2024",
            "October 2024",
            "September 2025",
            "December 2025",
        },
        "MDB": {"In 2025"},
        "NA": {"August 2020"},
        "NIU": {"February 2025"},
        "OSS": {"July 2017"},
        "SEDG": {"In 2025"},
        "SES": {"September 2025"},
        "SHAZ": {"January 2026", "December 2025"},
        "SMTK": {"During 2025"},
        "XCH": {"May 2023", "April 2022"},
    }

    assert sum(len(values) for values in expected.values()) == 20

    for symbol, temporal_fragments in expected.items():
        products = set(_profile(symbol)["product_stack"])
        assert temporal_fragments.isdisjoint(products)


def test_numbered_model_names_remain_inline_model_products() -> None:
    module = _production_builder_module()
    products, _ = module._extract_inline_model_products(
        "Our product models include Alpha 2024, Server 2022, X1, and Cuckoo 3.0 systems."
    )

    assert "Alpha 2024" in products
    assert "Server 2022" in products
    assert "X1" in products
    assert any(value.startswith("Cuckoo 3") for value in products)


def test_competitor_and_regulatory_relations_are_not_products() -> None:
    profile = _profile("CRDO")
    products = set(profile["product_stack"])

    assert {
        "Broadcom Ltd",
        "14 Marvell Technology",
        "Inc. and Astera Labs",
        "United States export controls and sanctions laws",
        "United States export controls",
        "all leveraging the Company’s PILOT diagnostic",
    }.isdisjoint(products)

    assert {
        "Active Electrical Cables (AECs)",
        "SerDes Chiplets",
        "Optical PAM4 DSPs",
        "PCIe Retimers",
        "PILOT Software Platform",
        "ZeroFlap Optical Transceivers",
    }.issubset(products)


def test_acls_owned_models_survive_without_component_or_chip_type_noise() -> None:
    profile = _profile("ACLS")
    products = set(profile["product_stack"])

    assert profile["company_summary"]["one_line_business"].startswith(
        "Axcelis Technologies, Inc."
    )
    assert {
        "Purion H",
        "Purion Dragon",
        "Purion H200",
        "Purion XE",
        "Purion EXE",
        "Purion M Si",
        "Purion M SiC",
        "GSD/E2 Ovation",
    }.issubset(products)
    assert not any("stage Linac with energies" in value for value in products)
    assert "Purion Purion" not in products
    assert not any("dynamic random-access memory" in value for value in profile[
        "core_technologies"
    ])


def test_lite_product_relations_are_products_not_uses_or_actors() -> None:
    profile = _profile("LITE")
    products = set(profile["product_stack"])

    assert {
        "AI/ML infrastructure providers",
        "storage area networks",
        "optical channel monitors to efficiently switch",
        "integrated modules",
        "pump lasers for optical amplifiers and passive components such as switches",
    }.isdisjoint(products)
    assert {
        "pump lasers",
        "VCSELs and VCSEL arrays",
        "ROADMs",
        "optical amplifiers",
        "optical channel monitors",
    }.issubset(products)
    assert profile["markets"] == [
        "Printed Circuit Board Manufacturing",
        "Electric Vehicle Battery Production",
        "Solar Cell Production",
        "Flat Panel Display Fabrication",
        "Semiconductor Processing",
    ]
    assert profile["customer_types"] == ["network equipment manufacturers"]


def test_mpwr_product_heads_markets_and_channels_are_semantic() -> None:
    profile = _profile("MPWR")

    assert profile["markets"] == [
        "Storage And Computing",
        "Enterprise Data",
        "Automotive",
        "Communications",
        "Consumer",
        "Industrial",
    ]
    assert profile["product_stack"] == [
        "DC-to-DC products",
        "AC-to-DC products",
        "MOSFET drivers",
        "power management ICs",
        "current limit switches",
        "lighting control products",
    ]
    assert "distributors" not in profile["customer_types"]


def test_rebuilt_values_have_value_specific_clean_provenance() -> None:
    for symbol in ("ACLS", "LITE", "MPWR"):
        profile = _profile(symbol)
        provenance = profile["value_provenance"]["product_stack"]

        assert [row["value"] for row in provenance] == profile["product_stack"]
        assert all(row["evidence"] is not None for row in provenance)
        assert not any(
            "unconscious bias training" in sentence.casefold()
            for sentence in profile["field_evidence"]["product_stack"]
        )

    acls = _profile("ACLS")
    ai_row = next(
        row
        for row in acls["value_provenance"]["demand_drivers"]
        if row["value"] == "AI"
    )
    assert "artificial intelligence" in ai_row["evidence"]["quote"].casefold()
    assert "available on the market" not in ai_row["evidence"]["quote"].casefold()


def test_hele_business_brands_entities_and_locations_are_typed() -> None:
    profile = _profile("HELE")

    assert profile["company_summary"]["one_line_business"].startswith(
        "We are a leading global consumer products company"
    )
    assert {
        "OXO",
        "Hydro Flask",
        "Osprey",
        "Hot Tools",
        "Revlon",
        "Olive & June",
    }.issubset(profile["product_stack"])
    assert {
        "Revlon and Olive & June",
        "food preparation and storage",
    }.isdisjoint(profile["product_stack"])
    assert not any("TCFD" in value for value in profile["core_technologies"])
    assert profile["manufacturing"]["locations"] == [
        "China",
        "Vietnam",
        "Mexico",
    ]


def test_lyts_lists_stop_before_standards_and_preserve_compound_markets() -> None:
    profile = _profile("LYTS")

    assert {
        "Refueling",
        "Convenience Store",
        "Parking Lot",
        "Garage",
        "Grocery",
        "Pharmacy",
        "Sports Court",
    }.issubset(profile["markets"])
    assert {
        "sensors",
        "photocontrols",
        "dimming",
        "motion detection",
        "circuit controllers",
    }.issubset(profile["product_stack"])
    assert not any(
        marker in value
        for value in profile["product_stack"]
        for marker in ("UL Solutions", "Consortium", "Association", "NOM", "IPC")
    )
    assert profile["manufacturing"]["locations"] == ["United States"]


def test_ral_explicit_end_markets_products_and_regulations_are_typed() -> None:
    profile = _profile("RAL")

    assert {
        "Semiconductor",
        "Diversified Electronics",
        "Communications",
        "Utilities",
        "Defense And Space",
        "Industrial Manufacturing",
    }.issubset(profile["markets"])
    assert {
        "oscilloscopes",
        "probes",
        "source measuring units",
        "semiconductor test systems",
        "liquid level sensors",
        "flow sensors",
        "pressure sensors",
        "motion sensors",
        "hygienic sensors",
    }.issubset(profile["product_stack"])
    assert not any(
        marker in value
        for value in profile["core_technologies"]
        for marker in ("GDPR", "LGPD")
    )
    assert profile["manufacturing"]["locations"] == []
    assert all(
        row["evidence"] is not None
        for row in profile["value_provenance"]["product_stack"]
    )
