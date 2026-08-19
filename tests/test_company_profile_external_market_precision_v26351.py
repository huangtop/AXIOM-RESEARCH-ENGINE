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
    / "census_company_profile_external_market_precision_v26351.py"
)

spec = importlib.util.spec_from_file_location(
    "external_market_precision_v26351",
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


def test_v26351_extracts_focus_market_list():
    values = (
        module.extract_market_phrase_candidates(
            "We focus on automotive, industrial "
            "and healthcare markets."
        )
    )

    assert values == [
        "automotive",
        "industrial",
        "healthcare",
    ]


def test_v26351_extracts_target_market_list():
    values = (
        module.extract_market_phrase_candidates(
            "We target aerospace and defense markets."
        )
    )

    assert values == [
        "aerospace",
        "defense",
    ]


def test_v26351_clean_market_candidate():
    result = module.classify_candidate(
        "automotive"
    )

    assert (
        result[
            "classification"
        ]
        == "clean_market"
    )
    assert (
        result[
            "canonical_candidate"
        ]
        == "Automotive"
    )


def test_v26351_canonicalizes_data_centers():
    result = module.classify_candidate(
        "data centers"
    )

    assert (
        result[
            "classification"
        ]
        == "clean_market"
    )
    assert (
        result[
            "canonical_candidate"
        ]
        == "Data Center"
    )


def test_v26351_rejects_product_capability():
    result = module.classify_candidate(
        "high performance processing capabilities"
    )

    assert (
        result[
            "classification"
        ]
        == "product_capability_contamination"
    )


def test_v26351_rejects_customer_type():
    result = module.classify_candidate(
        "enterprise customers"
    )

    assert (
        result[
            "classification"
        ]
        == "customer_contamination"
    )


def test_v26351_rejects_geography():
    result = module.classify_candidate(
        "Europe"
    )

    assert (
        result[
            "classification"
        ]
        == "geography_contamination"
    )


def test_v26351_rejects_demand_strategy():
    result = module.classify_candidate(
        "growth opportunities"
    )

    assert (
        result[
            "classification"
        ]
        == "strategy_demand_contamination"
    )


def test_v26351_marks_unknown_candidate_ambiguous():
    result = module.classify_candidate(
        "specialized workflows"
    )

    assert (
        result[
            "classification"
        ]
        == "ambiguous"
    )


def test_v26351_audit_clean_sentence():
    row = {
        "symbol": "TEST",
        "company_id": "company:test",
        "sentence": (
            "We focus on automotive and industrial markets."
        ),
        "source_secondary_flags": [],
    }

    result = module.audit_sentence(
        row
    )

    assert (
        result[
            "sentence_status"
        ]
        == "clean"
    )
    assert (
        result[
            "clean_market_candidates"
        ]
        == [
            "Automotive",
            "Industrial",
        ]
    )


def test_v26351_audit_mixed_sentence():
    row = {
        "symbol": "TEST",
        "company_id": "company:test",
        "sentence": (
            "We focus on automotive and "
            "high performance processing markets."
        ),
        "source_secondary_flags": [],
    }

    result = module.audit_sentence(
        row
    )

    assert (
        result[
            "sentence_status"
        ]
        == "mixed"
    )
    assert (
        "Automotive"
        in result[
            "clean_market_candidates"
        ]
    )


def test_v26351_filters_only_external_market_source_rows():
    payload = {
        "companies": [
            {
                "symbol": "AAA",
                "company_id": "company:aaa",
                "address_focus_sentences": [
                    {
                        "sentence": (
                            "We focus on automotive markets."
                        ),
                        "primary_classification": (
                            "external_market"
                        ),
                        "secondary_flags": [],
                    },
                    {
                        "sentence": (
                            "We address growing demand in markets."
                        ),
                        "primary_classification": (
                            "demand_driver"
                        ),
                        "secondary_flags": [],
                    },
                ],
            }
        ]
    }

    rows = (
        module.external_market_sentences(
            payload
        )
    )

    assert len(
        rows
    ) == 1
    assert (
        rows[
            0
        ][
            "sentence"
        ]
        == "We focus on automotive markets."
    )


def test_v26351_build_report_counts_promotable_company():
    payload = {
        "summary": {
            "address_focus_company_count": 1,
        },
        "companies": [
            {
                "symbol": "AAA",
                "company_id": "company:aaa",
                "address_focus_sentences": [
                    {
                        "sentence": (
                            "We focus on automotive "
                            "and industrial markets."
                        ),
                        "primary_classification": (
                            "external_market"
                        ),
                        "secondary_flags": [],
                    }
                ],
            }
        ],
    }

    report = module.build_report(
        payload
    )

    assert (
        report[
            "summary"
        ][
            "promotable_company_count"
        ]
        == 1
    )
    assert (
        report[
            "summary"
        ][
            "strict_clean_company_count"
        ]
        == 1
    )