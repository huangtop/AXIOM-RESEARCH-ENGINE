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
    assert any("dynamic random-access memory" in value for value in technologies)


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
