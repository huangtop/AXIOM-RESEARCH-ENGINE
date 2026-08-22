from __future__ import annotations

import json
from pathlib import Path

from axiom_engine.company_profile_v2.batch import (
    build_company_profile_batch,
    resolve_batch_symbols,
)


ROOT = Path(__file__).resolve().parents[1]


def test_v25_published_scope_follows_company_profile_v2_production_index():
    production = json.loads(
        (
            ROOT
            / "data/generated/company_profile_v2/index.json"
        ).read_text()
    )

    expected = sorted(
        production[
            "symbol_to_file"
        ]
    )

    actual = resolve_batch_symbols(
        ROOT,
        scope="published",
    )

    assert actual == expected

    # The batch layer must not maintain a second
    # company-membership list.
    source = (
        ROOT
        / "src/axiom_engine/company_profile_v2/batch.py"
    ).read_text()

    for symbol in expected:
        assert (
            f'"{symbol}"'
            not in source
        )


def test_v25_explicit_symbols_override_scope():
    symbols = resolve_batch_symbols(
        ROOT,
        scope="published",
        symbols=[
            "nvda",
            "AAOI",
            "NVDA",
        ],
    )

    assert symbols == [
        "AAOI",
        "NVDA",
    ]


def test_v25_generic_smoke_cohort_builds_canonical_and_zh_tw():
    report = build_company_profile_batch(
        ROOT,
        symbols=[
            "AAOI",
            "NVDA",
        ],
    )

    assert report[
        "summary"
    ][
        "target_company_count"
    ] == 2

    assert report[
        "summary"
    ][
        "generated_company_count"
    ] == 2

    assert report[
        "summary"
    ][
        "failed_company_count"
    ] == 0

    assert report[
        "summary"
    ][
        "complete"
    ] is True

    records = {
        row["symbol"]: row
        for row
        in report[
            "records"
        ]
    }

    assert set(records) == {
        "AAOI",
        "NVDA",
    }

    for row in records.values():
        assert (
            row[
                "canonical_schema_version"
            ]
            == "axiom-company-profile.v2.3"
        )

        assert (
            row[
                "display_schema_version"
            ]
            == "axiom-company-profile-display.zh-tw.v2.4"
        )

        assert (
            row[
                "production_ready"
            ]
            is True
        )

        assert (
            row[
                "coverage"
            ][
                "company_summary"
            ]
            is True
        )

        assert (
            row[
                "coverage"
            ][
                "value_provenance"
            ]
            is True
        )

        assert (
            row[
                "coverage"
            ][
                "evidence"
            ]
            is True
        )


def test_v25_coverage_report_is_field_level_not_company_specific():
    report = build_company_profile_batch(
        ROOT,
        symbols=[
            "AAOI",
            "NVDA",
        ],
    )

    coverage = report[
        "coverage"
    ]

    assert (
        coverage[
            "company_summary"
        ][
            "covered_company_count"
        ]
        == 2
    )

    assert (
        coverage[
            "evidence"
        ][
            "coverage"
        ]
        == 1.0
    )

    assert (
        "markets"
        in coverage
    )

    assert (
        "financial_snapshot"
        in coverage
    )

def test_v25_supports_20f_company_information_gfs():
    report = build_company_profile_batch(
        ROOT,
        symbols=["GFS"],
    )

    assert (
        report["summary"]
        ["generated_company_count"]
        == 1
    )

    assert report["failures"] == []

    profile = report[
        "_canonical_profiles"
    ][0]

    assert (
        profile["evidence"][0]["form"]
        == "20-F"
    )

    assert (
        profile["evidence"][0]
        ["section_type"]
        == "item_4_company_information"
    )


def test_v25_supports_20f_company_information_silc():
    report = build_company_profile_batch(
        ROOT,
        symbols=["SILC"],
    )

    assert (
        report["summary"]
        ["generated_company_count"]
        == 1
    )

    assert report["failures"] == []

    profile = report[
        "_canonical_profiles"
    ][0]

    assert (
        profile["evidence"][0]["form"]
        == "20-F"
    )

    assert (
        profile["evidence"][0]
        ["section_type"]
        == "item_4_company_information"
    )