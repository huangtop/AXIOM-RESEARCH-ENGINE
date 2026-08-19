from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from axiom_engine.full_market_coverage import (
    FullMarketCoverageService,
    build_full_market_coverage,
    write_full_market_coverage,
)
from axiom_engine.valuation_http import ValuationWSGIApp


ROOT = Path(__file__).resolve().parents[1]
MODELS = {"dcf", "forward_pe", "peg", "forward_ps", "ev_ebitda", "forward_pb", "milestone"}


def report():
    return build_full_market_coverage(ROOT)


def test_builder_uses_entire_population_without_a_maintained_ticker_cohort():
    payload = report()
    assert payload["summary"]["registry_company_count"] == 6464
    assert payload["summary"]["company_count"] == 5851
    assert payload["summary"]["excluded_non_company_instrument_count"] == 613
    assert payload["summary"]["security_count"] == 7451
    assert len(payload["cards"]) == 5851
    assert len(payload["indexes"]["ticker_to_position"]) == 6027


def test_every_company_has_seven_model_slots_and_explicit_reasons():
    payload = report()
    for card in payload["cards"]:
        assert set(card["valuation"]["models"]) == MODELS
        assert card["status"] in {"ready", "partial", "unavailable"}
        for model in card["valuation"]["models"].values():
            assert model["status"] in {"calculated", "unavailable"}
            if model["status"] == "unavailable":
                assert model["reason_code"]
                if model["reason_code"] == "MISSING_REQUIRED_INPUT":
                    assert model["missing_inputs"]


def test_every_card_exposes_explicit_quarterly_history_contract():
    payload = report()
    for card in payload["cards"]:
        history = card["financial_history"]
        assert history["requested_quarter_count"] == 8
        assert history["quarter_count"] <= 8
        assert history["status"] in {"ready", "unavailable"}


def test_unknown_or_missing_data_never_creates_a_fair_value():
    payload = report()
    card = next(card for card in payload["cards"] if card["valuation"]["calculated_model_count"] == 0)
    assert card["valuation"]["fair_value"] is None
    assert card["valuation"]["reason_code"] == "NO_CALCULATED_MODELS"


def _get(app, path):
    observed = {}

    def start_response(status, headers):
        observed["status"] = status
        observed["headers"] = dict(headers)

    body = b"".join(app({"REQUEST_METHOD": "GET", "PATH_INFO": path}, start_response))
    return observed, json.loads(body)


def test_http_exposes_full_market_list_and_company_card():
    app = ValuationWSGIApp(full_market_service=FullMarketCoverageService(root=ROOT))
    list_response, listing = _get(app, "/v1/companies")
    card_response, card = _get(app, "/v1/companies/NVDA/valuation-card")
    contextual_response, contextual = _get(app, "/v1/companies/F/valuation-card")
    assert list_response["status"].startswith("200")
    assert listing["summary"]["company_count"] == 5851
    assert listing["summary"]["source"] == "compact_publication_catalog"
    assert card_response["status"].startswith("200")
    assert card["primary_security"]["ticker"] == "NVDA"
    assert set(card["valuation"]["models"]) == MODELS
    assert card["coverage_policy"]["research_scope"] == "core"
    assert contextual_response["status"].startswith("200")
    assert contextual["primary_security"]["ticker"] == "F"
    assert contextual["coverage_policy"]["product_scope"] == "basic_market"


def test_no_frontend_files_are_part_of_v031_implementation():
    paths = [
        "src/axiom_engine/full_market_coverage/core.py",
        "scripts/build_full_market_coverage.py",
        "tests/test_full_market_coverage_v031.py",
    ]
    assert all(not path.startswith("frontend/") for path in paths)


def test_writer_emits_lightweight_index_and_per_company_artifacts(tmp_path: Path):
    payload = report()
    output = tmp_path / "full_market_coverage.json"
    write_full_market_coverage(payload, output)
    index = json.loads(output.read_text())
    assert index["schema_version"] == "full-market-valuation-index.v031g.1"
    assert "cards" not in index
    nvda_file = index["indexes"]["ticker_to_file"]["NVDA"]
    nvda = json.loads((output.parent / nvda_file).read_text())
    assert nvda["primary_security"]["ticker"] == "NVDA"
    assert output.stat().st_size < 2_000_000


def test_alphabet_share_classes_resolve_to_one_primary_company_artifact(tmp_path: Path):
    payload = report()
    output = tmp_path / "full_market_coverage.json"
    write_full_market_coverage(payload, output)
    index = json.loads(output.read_text())["indexes"]["ticker_to_file"]
    assert index["GOOG"] == index["GOOGL"]
    card = json.loads((output.parent / index["GOOG"]).read_text())
    assert card["primary_security"]["ticker"] == "GOOGL"
    assert card["company"]["company_id"] == "company:US-CIK0001652044"
    assert "GOOGM" not in index
    assert "GOOGN" not in index


def test_valuation_uses_independent_model_families_and_reports_disagreement():
    payload = report()
    googl = next(card for card in payload["cards"] if card["primary_security"]["ticker"] == "GOOGL")
    valuation = googl["valuation"]
    assert valuation["aggregation_version"] == "independent-model-family.v031v.8"
    assert valuation["aggregation"] is None
    assert valuation["fair_value"] is None
    assert valuation["models"]["peg"]["status"] == "unavailable"
    for name in ("forward_pe", "forward_ps", "ev_ebitda", "forward_pb"):
        diagnostic = valuation["model_diagnostics"].get(name)
        if diagnostic:
            assert diagnostic["aggregation_role"] == "market_anchored"
            assert diagnostic["included_in_independent_aggregation"] is False


def test_dcf_is_globally_diagnostic_only_and_does_not_reduce_nvda_confidence():
    payload = report()
    nvda = next(card for card in payload["cards"] if card["primary_security"]["ticker"] == "NVDA")
    valuation = nvda["valuation"]
    dcf = valuation["aggregation"]["families"]["intrinsic_cash_flow"]
    assert dcf["included_in_aggregation"] is False
    assert Decimal(dcf["weight"]) == 0
    assert "intrinsic_cash_flow" not in valuation["aggregation"]["cross_check_families"]
    assert valuation["aggregation"]["confidence"] == "low"
    assert Decimal(valuation["fair_value"]) == Decimal(valuation["aggregation"]["families"]["forward_earnings"]["representative_fair_value"])


def test_ai_research_companies_have_a_calculated_valuation_model():
    payload = report()
    cards = {card["primary_security"]["ticker"]: card for card in payload["cards"]}
    eligibility = json.loads((ROOT / "data/generated/research_eligibility/research_eligibility.json").read_text())
    research_company_ids = {
        row["company_id"] for row in eligibility["records"]
        if row.get("research_universe_status") == "selected"
    }
    overview_dir = ROOT / "data/generated/company_overview/per-company"
    ai_tickers = []
    for path in overview_dir.glob("*.json"):
        overview = json.loads(path.read_text())
        theme_id = ((overview.get("path") or {}).get("theme") or {}).get("id")
        if (
            overview.get("status") == "classified"
            and overview.get("company_id") in research_company_ids
            and theme_id in {"theme:artificial_intelligence", "theme:ai_infrastructure"}
        ):
            ai_tickers.append(overview["ticker"])
    missing = [ticker for ticker in ai_tickers if cards[ticker]["valuation"]["calculated_model_count"] == 0]
    assert ai_tickers
    assert missing == []


def test_provider_fallbacks_are_labeled_without_analyst_target_derivation():
    payload = report()
    lite = next(card for card in payload["cards"] if card["primary_security"]["ticker"] == "LITE")
    arbb = next(card for card in payload["cards"] if card["primary_security"]["ticker"] == "ARBB")
    assert lite["status"] == "ready"
    assert lite["valuation"]["models"]["forward_ps"]["status"] == "calculated"
    assert "analyst_target" not in json.dumps(lite["valuation"]["models"])
    consensus = lite["valuation"]["reference_values"]["analyst_consensus_target"]
    assert consensus["aggregation_role"] == "external_reference"
    assert consensus["included_in_independent_aggregation"] is False
    assert arbb["financials"]["diluted_shares_outstanding"]["provenance"] == "yahoo_company_snapshot_fallback"
    assert arbb["estimates"]["forward_revenue"]["is_proxy"] is True
    assert arbb["valuation"]["models"]["forward_ps"]["status"] == "calculated"


def test_extreme_model_to_market_outlier_cannot_publish_a_headline():
    payload = report()
    outliers = [
        card for card in payload["cards"]
        if card["valuation"].get("reason_code") == "FAIR_VALUE_TO_MARKET_PRICE_EXTREME_OUTLIER"
    ]
    assert outliers
    assert all(card["valuation"]["calculated_model_count"] >= 1 for card in outliers)
    assert all(card["valuation"]["fair_value"] is None for card in outliers)


def test_locked_primary_business_routing_reaches_valuation_aggregation():
    payload = report()
    routed = [
        card for card in payload["cards"]
        if (card.get("valuation") or {}).get("routing", {}).get("status") == "routed"
    ]
    assert routed
    assert payload["summary"]["primary_business_routing_applied_count"] > 0
    assert payload["summary"]["primary_business_routing_pending_count"] < payload["summary"]["company_count"]

    archetypes = {
        card["valuation"]["routing"].get("archetype")
        for card in routed
    }
    assert "financial_institution" in archetypes
    assert "biopharma" in archetypes
    assert "technology_operating_company" in archetypes
    assert "investment_vehicle" in archetypes

    aggregated = [
        card for card in routed
        if card["valuation"].get("aggregation") is not None
        and card["valuation"]["routing"].get("aggregation_applied") is True
    ]
    assert aggregated
    for card in aggregated:
        aggregation = card["valuation"]["aggregation"]
        assert aggregation["routing_source"] == "locked_primary_business"
        assert aggregation["business_archetype"] == card["valuation"]["routing"]["archetype"]