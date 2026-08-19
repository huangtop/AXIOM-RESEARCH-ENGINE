from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

SCRIPT = (
    ROOT
    / "scripts"
    / "census_translation_universe_v2640.py"
)

spec = importlib.util.spec_from_file_location(
    "translation_universe_v2640",
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


def _overview(
    *,
    ticker: str,
    theme_id: str,
    sector_id: str,
    theme_confidence: float,
    sector_confidence: float,
    source: str,
    status: str = "classified",
):
    return {
        "ticker": ticker,
        "company_id": f"company:{ticker}",
        "display_name": ticker,
        "status": status,
        "path": {
            "theme": {
                "id": theme_id,
                "name": theme_id,
                "display_name_zh_tw": theme_id,
                "confidence": theme_confidence,
            },
            "sector": {
                "id": sector_id,
                "name": sector_id,
                "display_name_zh_tw": sector_id,
                "confidence": sector_confidence,
            },
        },
        "evidence": [
            {
                "business_evidence_id": "e1",
            },
        ],
        "classification_source": source,
        "classification_lock": {
            "status": "locked",
            "update_mode": "manual_override_only",
        },
    }


def test_v2640_curated_override_is_high_quality():
    row = _overview(
        ticker="NVDA",
        theme_id="theme:ai_infrastructure",
        sector_id="sector:ai_compute",
        theme_confidence=1.0,
        sector_confidence=1.0,
        source="curated_core_override",
    )

    quality, reasons = (
        module._classify_quality(
            row
        )
    )

    assert quality == "HIGH"
    assert reasons == [
        "curated_override",
    ]


def test_v2640_flags_sndk_style_locked_cloud_classification():
    row = _overview(
        ticker="SNDK",
        theme_id="theme:artificial_intelligence",
        sector_id="sector:cloud_infrastructure",
        theme_confidence=0.684,
        sector_confidence=0.5005,
        source="locked_published_classification",
    )

    quality, reasons = (
        module._classify_quality(
            row
        )
    )

    assert quality == "SUSPECT"
    assert (
        "possible_end_market_proxy"
        in reasons
    )
    assert (
        "low_sector_confidence"
        in reasons
    )
    assert (
        "weak_ai_sector_assignment"
        in reasons
    )


def test_v2640_priority_translation_requires_profile_ready():
    row = _overview(
        ticker="NVDA",
        theme_id="theme:ai_infrastructure",
        sector_id="sector:ai_compute",
        theme_confidence=1.0,
        sector_confidence=1.0,
        source="curated_core_override",
    )

    assert (
        module._translation_bucket(
            row,
            profile_ready=True,
            quality="HIGH",
        )
        == "translate_priority"
    )

    assert (
        module._translation_bucket(
            row,
            profile_ready=False,
            quality="HIGH",
        )
        == "not_profile_ready"
    )


def test_v2640_suspect_classification_never_auto_translates():
    row = _overview(
        ticker="SNDK",
        theme_id="theme:artificial_intelligence",
        sector_id="sector:cloud_infrastructure",
        theme_confidence=0.684,
        sector_confidence=0.5005,
        source="locked_published_classification",
    )

    assert (
        module._translation_bucket(
            row,
            profile_ready=True,
            quality="SUSPECT",
        )
        == "classification_review"
    )


def test_v2640_non_priority_theme_skips_translation():
    row = _overview(
        ticker="RCL",
        theme_id="theme:travel_leisure",
        sector_id="sector:cruise_lines",
        theme_confidence=1.0,
        sector_confidence=1.0,
        source="curated_core_override",
    )

    assert (
        module._translation_bucket(
            row,
            profile_ready=True,
            quality="HIGH",
        )
        == "skip_non_priority_theme"
    )


def test_v2640_reads_profile_ready_records(tmp_path: Path):
    path = (
        tmp_path
        / "census.json"
    )

    path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "symbol": "NVDA",
                        "production_ready": True,
                    },
                    {
                        "symbol": "SNDK",
                        "production_ready": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    ready = (
        module._profile_ready_symbols(
            tmp_path,
            Path("census.json"),
        )
    )

    assert ready == {
        "NVDA",
    }


def test_v2640_row_report_contains_evidence_and_bucket():
    row = _overview(
        ticker="MU",
        theme_id="theme:ai_infrastructure",
        sector_id="sector:ai_memory",
        theme_confidence=1.0,
        sector_confidence=1.0,
        source="curated_core_override",
    )

    result = (
        module._row_for_report(
            row,
            profile_ready=True,
        )
    )

    assert (
        result[
            "business_evidence_available"
        ]
        is True
    )
    assert (
        result[
            "translation_bucket"
        ]
        == "translate_priority"
    )