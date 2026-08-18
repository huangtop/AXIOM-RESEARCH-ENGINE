from __future__ import annotations

from pathlib import Path

from axiom_engine.company_profile_v2 import build_company_profile_v2
from axiom_engine.company_profile_v2.batch import build_company_profile_batch
from axiom_engine.company_profile_v2.display_zh_tw import (
    build_company_profile_display_zh_tw,
)
from axiom_engine.company_profile_v2.enrichment import (
    enrich_company_profile_display,
)


ROOT = Path(__file__).resolve().parents[1]


def _enriched(symbol: str):
    profile = build_company_profile_v2(ROOT, symbol=symbol)
    display = build_company_profile_display_zh_tw(ROOT, profile=profile)
    return profile, enrich_company_profile_display(
        ROOT, profile=profile, display_payload=display
    )


def test_v251_direct_aaoi_values_remain_first_priority():
    profile, display = _enriched("AAOI")
    assert profile["market_products"]
    payload = display["display"]
    assert payload["offerings_source"] == "v2_direct"
    assert payload["markets_source"] == "v2_direct"
    assert "光收發模組" in payload["offerings"]


def test_v251_mu_fills_missing_products_and_markets_from_legacy_evidence():
    profile, display = _enriched("MU")
    assert not profile["market_products"]
    payload = display["display"]
    assert payload["offerings_source"] == "company_analysis_v1_fallback"
    assert payload["markets_source"] == "company_analysis_v1_fallback"
    assert "HBM 高頻寬記憶體" in payload["offerings"]
    assert "DRAM 記憶體" in payload["offerings"]
    assert "雲端與資料中心" in payload["markets"]
    enrichment = display["production_enrichment"]
    assert enrichment["legacy_source_used"] is True
    assert enrichment["evidence_ids"]


def test_v251_canonical_v2_profile_is_not_mutated_by_bridge():
    profile = build_company_profile_v2(ROOT, symbol="MU")
    original = dict(profile)
    display = build_company_profile_display_zh_tw(ROOT, profile=profile)
    enrich_company_profile_display(ROOT, profile=profile, display_payload=display)
    assert profile == original
    assert "offerings" not in profile
    assert "classification" not in profile


def test_v251_published_cohort_has_frontend_products_and_markets():
    report = build_company_profile_batch(ROOT, scope="published")
    assert report["summary"]["target_company_count"] == 19
    assert report["summary"]["generated_company_count"] == 19
    assert report["summary"]["failed_company_count"] == 0
    assert report["coverage"]["frontend_offerings"]["covered_company_count"] == 19
    assert report["coverage"]["frontend_markets"]["covered_company_count"] == 19
    assert report["summary"]["production_ready_count"] == 19
    assert report["summary"]["complete"] is True