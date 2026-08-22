from __future__ import annotations

from pathlib import Path

from axiom_engine.company_profile_v2 import (
    build_company_profile_v2,
)

from axiom_engine.company_profile_v2.batch import (
    build_company_profile_batch,
)

from axiom_engine.company_profile_v2.display_zh_tw import (
    build_company_profile_display_zh_tw,
)

from axiom_engine.company_profile_v2.enrichment import (
    enrich_company_profile_display,
)


ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)


def _enriched(
    symbol: str,
):
    profile = (
        build_company_profile_v2(
            ROOT,
            symbol=symbol,
        )
    )

    display = (
        build_company_profile_display_zh_tw(
            ROOT,
            profile=profile,
        )
    )

    return (
        profile,
        enrich_company_profile_display(
            ROOT,
            profile=profile,
            display_payload=display,
        ),
    )


def test_v261_direct_aaoi_values_remain_first_priority():
    profile, display = (
        _enriched(
            "AAOI"
        )
    )

    assert profile[
        "market_products"
    ]

    payload = display[
        "display"
    ]

    assert (
        payload[
            "offerings_source"
        ]
        == "v2_market_products"
    )

    assert (
        payload[
            "markets_source"
        ]
        == "v2_direct"
    )

    assert (
        "光收發模組"
        in payload[
            "offerings"
        ]
    )


def test_v261_product_stack_is_generic_offering_fallback():
    profile = {
        "symbol":
            "TEST",

        "company_id":
            "company:test",

        "product_stack": [
            "Accelerators",
            "Networking",
        ],
    }

    display_payload = {
        "display": {
            "locale":
                "zh-TW",

            "product_stack": [
                "加速運算產品",
                "網路產品",
            ],

            "market_products":
                {},

            "markets":
                [],

            "customer_types": [
                "cloud providers",
            ],

            "core_technologies":
                [],

            "manufacturing":
                {},
        },
    }

    enriched = (
        enrich_company_profile_display(
            ROOT,
            profile=profile,
            display_payload=display_payload,
        )
    )

    payload = enriched[
        "display"
    ]

    assert (
        payload[
            "offerings"
        ]
        == [
            "加速運算產品",
            "網路產品",
        ]
    )

    assert (
        payload[
            "offerings_source"
        ]
        == "v2_product_stack"
    )


def test_v261_market_product_keys_are_market_fallback():
    profile = {
        "symbol":
            "TEST",

        "company_id":
            "company:test",
    }

    display_payload = {
        "display": {
            "locale":
                "zh-TW",

            "product_stack":
                [],

            "markets":
                [],

            "market_products": {
                "雲端與資料中心": [
                    "GPU",
                ],
                "汽車與車用電子": [
                    "Processor",
                ],
            },

            "customer_types":
                [],

            "core_technologies":
                [],

            "manufacturing":
                {},
        },
    }

    enriched = (
        enrich_company_profile_display(
            ROOT,
            profile=profile,
            display_payload=display_payload,
        )
    )

    payload = enriched[
        "display"
    ]

    assert (
        payload[
            "markets"
        ]
        == [
            "雲端與資料中心",
            "汽車與車用電子",
        ]
    )

    assert (
        payload[
            "markets_source"
        ]
        == "v2_market_products"
    )


def test_v261_customer_types_are_explicit_market_proxy():
    profile = {
        "symbol":
            "TEST",

        "company_id":
            "company:test",
    }

    display_payload = {
        "display": {
            "locale":
                "zh-TW",

            "product_stack": [
                "產品 A",
            ],

            "market_products":
                {},

            "markets":
                [],

            "customer_types": [
                "cloud providers",
                "OEMs",
                "cloud providers",
            ],

            "core_technologies":
                [],

            "manufacturing":
                {},
        },
    }

    enriched = (
        enrich_company_profile_display(
            ROOT,
            profile=profile,
            display_payload=display_payload,
        )
    )

    payload = enriched[
        "display"
    ]

    assert (
        payload[
            "markets"
        ]
        == [
            "cloud providers",
            "OEMs",
        ]
    )

    assert (
        payload[
            "markets_source"
        ]
        == "v2_customer_types_proxy"
    )

    production_enrichment = (
        enriched[
            "production_enrichment"
        ]
    )

    assert (
        "markets"
        in production_enrichment[
            "fallback_dimensions"
        ]
    )



def test_v261_canonical_v2_profile_is_not_mutated():
    profile = (
        build_company_profile_v2(
            ROOT,
            symbol="MU",
        )
    )

    original = dict(
        profile
    )

    display = (
        build_company_profile_display_zh_tw(
            ROOT,
            profile=profile,
        )
    )

    enrich_company_profile_display(
        ROOT,
        profile=profile,
        display_payload=display,
    )

    assert (
        profile
        == original
    )

    assert (
        "offerings"
        not in profile
    )

    assert (
        "classification"
        not in profile
    )


def test_v261_enrichment_records_frontend_source_provenance():
    profile = {
        "symbol":
            "TEST",

        "company_id":
            "company:test",
    }

    display_payload = {
        "display": {
            "locale":
                "zh-TW",

            "product_stack": [
                "產品 A",
            ],

            "market_products":
                {},

            "markets":
                [],

            "customer_types": [
                "OEM",
            ],

            "core_technologies": [
                "Technology A",
            ],

            "manufacturing":
                {},
        },
    }

    enriched = (
        enrich_company_profile_display(
            ROOT,
            profile=profile,
            display_payload=display_payload,
        )
    )

    production_enrichment = (
        enriched[
            "production_enrichment"
        ]
    )

    assert (
        production_enrichment[
            "schema_version"
        ]
        == (
            "axiom-company-profile-enrichment."
            "v2.6.2"
        )
    )

    assert (
        production_enrichment[
            "frontend_sources"
        ][
            "offerings"
        ]
        == "v2_product_stack"
    )

    assert (
        production_enrichment[
            "frontend_sources"
        ][
            "markets"
        ]
        == "v2_customer_types_proxy"
    )

    assert (
        production_enrichment[
            "frontend_sources"
        ][
            "operating_capabilities"
        ]
        == "v2_direct"
    )
