from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

SCRIPT = (
    ROOT
    / "scripts"
    / "census_company_profile_address_focus_v2635.py"
)

spec = importlib.util.spec_from_file_location(
    "address_focus_v2635",
    SCRIPT,
)

assert spec is not None
assert spec.loader is not None

module = importlib.util.module_from_spec(
    spec
)

spec.loader.exec_module(
    module
)


def test_v2635_detects_address_focus_sentence():
    sentence = (
        "We focus on automotive and "
        "industrial markets."
    )

    assert (
        module.is_address_focus_sentence(
            sentence
        )
        is True
    )


def test_v2635_classifies_external_market():
    result = (
        module.classify_address_focus_sentence(
            "We focus on automotive and industrial markets."
        )
    )

    assert (
        result[
            "primary_classification"
        ]
        == "external_market"
    )


def test_v2635_classifies_demand_driver():
    result = (
        module.classify_address_focus_sentence(
            "We address growing demand in data center markets."
        )
    )

    assert (
        result[
            "primary_classification"
        ]
        == "demand_driver"
    )


def test_v2635_classifies_strategy_statement():
    result = (
        module.classify_address_focus_sentence(
            "Our strategy focuses on expansion into new markets."
        )
    )

    assert (
        result[
            "primary_classification"
        ]
        == "strategy_statement"
    )


def test_v2635_classifies_product_capability():
    result = (
        module.classify_address_focus_sentence(
            "Our products address communications markets "
            "with advanced software capabilities."
        )
    )

    assert (
        result[
            "primary_classification"
        ]
        == "product_capability"
    )


def test_v2635_classifies_geography():
    result = (
        module.classify_address_focus_sentence(
            "We focus on markets in Europe and China."
        )
    )

    assert (
        result[
            "primary_classification"
        ]
        == "geography"
    )


def test_v2635_classifies_customer_type():
    result = (
        module.classify_address_focus_sentence(
            "We target enterprise customers in cloud markets."
        )
    )

    assert (
        result[
            "primary_classification"
        ]
        == "customer_type"
    )


def test_v2635_market_hint_is_not_enough_when_product_noise_exists():
    result = (
        module.classify_address_focus_sentence(
            "Our GPU products target automotive markets."
        )
    )

    assert (
        result[
            "primary_classification"
        ]
        == "product_capability"
    )


def test_v2635_latest_business_evidence_prefers_latest_supported():
    rows = [
        {
            "section_type": "item_1_business",
            "filing_date": "2025-01-01",
            "text": "Older evidence.",
        },
        {
            "section_type": "item_1_business",
            "filing_date": "2026-01-01",
            "text": "Newer evidence.",
        },
        {
            "section_type": "item_7_mda",
            "filing_date": "2026-02-01",
            "text": "Unsupported.",
        },
    ]

    latest = (
        module.latest_business_evidence(
            rows
        )
    )

    assert latest is not None
    assert (
        latest[
            "text"
        ]
        == "Newer evidence."
    )


def test_v2635_analyze_company_only_keeps_address_focus_sentences():
    result = module.analyze_company(
        symbol="TEST",
        company_id="company:test",
        evidence_rows=[
            {
                "section_type": "item_1_business",
                "filing_date": "2026-01-01",
                "form": "10-K",
                "text": (
                    "We focus on automotive and industrial markets. "
                    "Revenue increased during the year."
                ),
            }
        ],
    )

    assert (
        result[
            "status"
        ]
        == "address_focus_found"
    )

    assert (
        result[
            "address_focus_sentence_count"
        ]
        == 1
    )

    assert (
        result[
            "address_focus_sentences"
        ][0][
            "primary_classification"
        ]
        == "external_market"
    )


def test_v2635_missing_market_records_uses_frontend_coverage():
    census = {
        "records": [
            {
                "symbol": "AAA",
                "company_id": "company:aaa",
                "coverage": {
                    "frontend_markets": False,
                },
            },
            {
                "symbol": "BBB",
                "company_id": "company:bbb",
                "coverage": {
                    "frontend_markets": True,
                },
            },
        ],
    }

    rows = (
        module.missing_market_records(
            census
        )
    )

    assert [
        row[
            "symbol"
        ]
        for row in rows
    ] == [
        "AAA",
    ]

def test_v2635_focus_verb_alone_does_not_force_strategy():
    result = (
        module.classify_address_focus_sentence(
            "We focus on healthcare and aerospace markets."
        )
    )

    assert (
        result[
            "primary_classification"
        ]
        == "external_market"
    )
