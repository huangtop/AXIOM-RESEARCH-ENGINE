from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from axiom_engine.full_market_coverage import (
    FullMarketCoverageService,
    build_full_market_coverage,
    write_full_market_coverage,
)
import pytest

from axiom_engine.full_market_coverage.core import (
    _dual_fy_seven_models,
    _forward_fundamental_peg_growth,
)
from axiom_engine.valuation_http import ValuationWSGIApp


ROOT = Path(__file__).resolve().parents[1]
MODELS = {"dcf", "forward_pe", "peg", "forward_ps", "ev_ebitda", "forward_pb", "milestone"}


def test_dual_fy_models_never_use_current_to_next_growth_for_next_fy_peg():
    horizons = _dual_fy_seven_models(
        {
            "annual_estimates": {
                "CURRENT_FY": {"eps": "214.09818", "revenue": "48960258320", "peg_growth": "0.2364", "growth_basis": "CURRENT_FY_TO_NEXT_FY"},
                "NEXT_FY": {"eps": "264.72162", "revenue": "57786626660", "peg_growth": None, "growth_basis": None},
            },
            "previous_close": "1484.98",
            "trailing_eps": "73.8",
            "revenue_ttm": "20248000512",
            "shares_outstanding": "146000000",
        },
        {"diluted_shares_outstanding": {"value": "146000000"}},
        {
            "target_peg": "0.9",
        },
        {"current_price": "1484.98"},
        {},
    )

    assert Decimal(horizons["CURRENT_FY"]["models"]["peg"]["fair_value"]).quantize(Decimal("0.01")) == Decimal("3473.71")
    assert horizons["NEXT_FY"]["models"]["peg"]["status"] == "unavailable"
    assert horizons["NEXT_FY"]["models"]["peg"]["fair_value"] is None
    assert horizons["NEXT_FY"]["models"]["peg"]["reason_code"] == "HORIZON_EPS_OR_MATCHED_GROWTH_UNAVAILABLE"


def test_negative_eps_growth_without_revenue_growth_makes_peg_unavailable():
    current_eps = Decimal("25.88306")
    next_eps = Decimal("24.66365")
    derived_growth = next_eps / current_eps - Decimal("1")

    assert derived_growth < 0

    horizons = _dual_fy_seven_models(
        {
            "annual_estimates": {
                "CURRENT_FY": {
                    "eps": format(current_eps, "f"),
                    "revenue": "113538000000",
                    "reported_growth": "0.375",
                    "peg_growth": format(derived_growth, "f"),
                    "growth_basis": "CURRENT_FY_TO_NEXT_FY",
                },
                "NEXT_FY": {
                    "eps": format(next_eps, "f"),
                    "revenue": None,
                    "reported_growth": "0.0083",
                    "peg_growth": None,
                    "growth_basis": None,
                },
            },
            "current_fiscal_year": 2027,
            "trailing_eps": "17.24",
            "shares_outstanding": "684000000",
            "revenue_ttm": "113538000000",
        },
        {
            "diluted_shares_outstanding": {"value": "684000000"},
        },
        {},
        {
            "current_price": "563.2899780273438",
        },
        {},
    )

    current = horizons["CURRENT_FY"]
    peg = current["models"]["peg"]

    assert current["estimate_basis"] == "CURRENT_FY"

    assert peg["status"] == "unavailable"
    assert peg["fair_value"] is None
    assert (
        peg["reason_code"]
        == "HORIZON_EPS_OR_MATCHED_GROWTH_UNAVAILABLE"
    )
    assert peg["included_in_weighting"] is False
    assert (
        peg["weighting_exclusion_reason"]
        == "HORIZON_EPS_OR_MATCHED_GROWTH_UNAVAILABLE"
    )
def test_dell_current_fy_peg_uses_revenue_anchor_and_published_target_peg():
    current_eps = Decimal("25.88376")
    next_eps = Decimal("24.66365")
    transition_growth = next_eps / current_eps - Decimal("1")

    assert transition_growth < 0

    horizons = _dual_fy_seven_models(
        {
            "normalized_peg_growth": "0.1077",
            "normalized_peg_growth_basis": "YAHOO_GROWTH_ESTIMATES_PLUS_1Y",
            "annual_estimates": {
                "CURRENT_FY": {
                    "eps": format(current_eps, "f"),
                    "revenue": "113538000000",
                    "reported_growth": "1.5130",
                    "peg_growth": format(transition_growth, "f"),
                    "growth_basis": None,
                },
                "NEXT_FY": {
                    "eps": format(next_eps, "f"),
                    "revenue": "130307450000",
                    "reported_growth": "0.0083",
                    "peg_growth": None,
                    "growth_basis": None,
                },
            },
            "current_fiscal_year": 2027,
            "trailing_eps": "17.24",
            "shares_outstanding": "684000000",
            "revenue_ttm": "113538000000",
        },
        {
            "diluted_shares_outstanding": {"value": "684000000"},
        },
        {
            "target_peg": "1.0125115160599578",
        },
        {
            "current_price": "506.62",
        },
        {},
    )

    current_fy = horizons["CURRENT_FY"]

    # The negative adjacent-FY transition remains available as a diagnostic,
    # but it is not the normalized growth input used by PEG valuation.
    assert transition_growth == (
        next_eps / current_eps - Decimal("1")
    )

    assert Decimal(current_fy["eps_growth"]) == (Decimal("130307450000") / Decimal("113538000000") - 1)
    assert (
        current_fy["growth_basis"]
        == "PEG_GROWTH_FORWARD_FUNDAMENTAL_ANCHOR"
    )

    assert current_fy["growth_is_horizon_matched"] is True

    published_target_peg = Decimal("1.0125115160599578")

    expected_peg = (
        current_eps
        * (Decimal("130307450000") / Decimal("113538000000") - 1)
        * Decimal("100")
        * published_target_peg
    )

    assert Decimal(
        current_fy["models"]["peg"]["fair_value"]
    ) == expected_peg

    # One normalized CURRENT_FY PEG growth must not leak into NEXT_FY.
    assert horizons["NEXT_FY"]["models"]["peg"]["status"] == "unavailable"
    assert horizons["NEXT_FY"]["models"]["peg"]["fair_value"] is None

def test_missing_horizon_inputs_are_unavailable_instead_of_current_price_fallbacks():
    horizons = _dual_fy_seven_models(
        {}, {}, {}, {"current_price": "100"}, {}
    )
    for horizon in horizons.values():
        for model_name in ("dcf", "forward_pe", "peg", "forward_ps", "ev_ebitda", "forward_pb"):
            assert horizon["models"][model_name]["status"] == "unavailable"
            assert horizon["models"][model_name]["fair_value"] is None


def report():
    return build_full_market_coverage(ROOT)


def test_builder_uses_entire_population_without_a_maintained_ticker_cohort():
    payload = report()
    companies = json.loads((ROOT / "data/universe/companies.json").read_text())
    securities = json.loads((ROOT / "data/universe/securities.json").read_text())
    assert payload["summary"]["registry_company_count"] == len(companies)
    assert payload["summary"]["company_count"] == len(payload["cards"])
    assert payload["summary"]["excluded_non_company_instrument_count"] == (
        payload["summary"]["registry_company_count"]
        - payload["summary"]["company_count"]
    )
    assert payload["summary"]["security_count"] == len(securities)
    assert len(payload["indexes"]["ticker_to_position"]) >= payload["summary"][
        "company_count"
    ]


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
    assert listing["summary"]["company_count"] == len(listing["companies"])
    assert listing["summary"]["source"] == "compact_publication_catalog"
    assert card_response["status"].startswith("200")
    assert card["primary_security"]["ticker"] == "NVDA"

    # The valuation-card API is backed by the rich Full Market artifact.
    # Compact Publication projections are a separate frontend delivery
    # contract and must not shadow backend valuation-card responses.
    assert set(card["valuation"]["models"]) == MODELS
    assert "financial_history" in card
    assert set(card["valuation_horizons"]["CURRENT_FY"]["models"]) == MODELS
    assert set(card["valuation_horizons"]["NEXT_FY"]["models"]) == MODELS

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


def test_valuation_uses_unified_contract_and_preserves_market_anchor_exclusions():
    payload = report()
    googl = next(card for card in payload["cards"] if card["primary_security"]["ticker"] == "GOOGL")
    valuation = googl["valuation"]
    assert valuation["aggregation_version"] == "unified-dynamic-weight.v1"
    unified = valuation["unified_contract"]
    assert unified["contract_version"] == "unified-valuation.v1"
    assert tuple(unified["models"]) == (
        "dcf",
        "forward_pe",
        "peg",
        "forward_ps",
        "ev_ebitda",
        "forward_pb",
        "milestone",
    )
    for name in ("forward_pe", "forward_ps", "ev_ebitda", "forward_pb"):
        diagnostic = valuation["model_diagnostics"].get(name)
        if diagnostic and diagnostic["aggregation_role"] == "market_anchored":
            assert diagnostic["included_in_independent_aggregation"] is False
            assert Decimal(diagnostic["effective_weight"]) == 0


def test_nvda_uses_unified_backend_model_selection():
    payload = report()
    nvda = next(card for card in payload["cards"] if card["primary_security"]["ticker"] == "NVDA")
    valuation = nvda["valuation"]
    unified = valuation["unified_contract"]
    assert unified["headline"]["dominant_model"] in unified["models"]
    included = unified["aggregation"]["included_models"]
    weights = {
        name: Decimal(value)
        for name, value in unified["aggregation"]["normalized_weights"].items()
    }
    assert included
    assert sum((weights[name] for name in included), Decimal("0")) == Decimal("1")
    assert Decimal(valuation["fair_value"]) == Decimal(unified["headline"]["base_fair_value"])


def test_ai_research_companies_without_inputs_report_unavailable_models():
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
            and theme_id == "theme:ai_infrastructure"
        ):
            ai_tickers.append(overview["ticker"])
    missing = [ticker for ticker in ai_tickers if cards[ticker]["valuation"]["calculated_model_count"] == 0]
    assert ai_tickers
    for ticker in missing:
        valuation = cards[ticker]["valuation"]
        assert valuation["reason_code"] == "NO_CALCULATED_MODELS"
        assert all(model["status"] == "unavailable" for model in valuation["models"].values())


def test_trailing_revenue_is_not_relabelled_as_forward_revenue():
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
    assert arbb["estimates"]["forward_revenue"]["status"] == "unavailable"
    assert arbb["estimates"]["forward_revenue"]["reason_code"] == "MISSING_POSITIVE_FORWARD_REVENUE"
    assert arbb["estimates"]["forward_revenue"]["is_proxy"] is False
    assert arbb["valuation"]["models"]["forward_ps"]["status"] == "unavailable"


def test_unified_headline_comes_from_backend_contract_not_legacy_market_sanity_gate():
    payload = report()
    cards = [
        card for card in payload["cards"]
        if card["valuation"].get("unified_contract")
    ]
    assert cards
    for card in cards:
        valuation = card["valuation"]
        unified = valuation["unified_contract"]
        assert valuation["reason_code"] != "FAIR_VALUE_TO_MARKET_PRICE_EXTREME_OUTLIER"
        assert valuation["fair_value"] == unified["headline"]["base_fair_value"]


def test_primary_business_routing_no_longer_controls_valuation_aggregation():
    payload = report()
    routed = [
        card for card in payload["cards"]
        if (card.get("valuation") or {}).get("routing", {}).get("status") == "routed"
    ]
    assert routed
    assert payload["summary"]["primary_business_routing_applied_count"] == 0

    for card in routed:
        valuation = card["valuation"]
        unified = valuation["unified_contract"]
        assert valuation["aggregation"]["routing_source"] == "unified_valuation"
        assert unified["aggregation"]["methodology_version"] == "unified-dynamic-weight.v1"


def test_incremental_builder_filters_to_requested_company_and_share_class_alias():
    payload = build_full_market_coverage(ROOT, symbols=["GOOG"])
    assert payload["summary"]["incremental"] is True
    assert payload["summary"]["selected_symbol_count"] == 1
    assert len(payload["cards"]) == 1
    card = payload["cards"][0]
    assert card["primary_security"]["ticker"] == "GOOGL"
    assert {row["ticker"] for row in card["securities"]} >= {"GOOG", "GOOGL"}


def test_incremental_writer_preserves_unmentioned_company_bytes_and_complete_index(
    tmp_path: Path,
):
    output = tmp_path / "full_market_coverage.json"

    initial = build_full_market_coverage(ROOT, symbols=["AMD", "NVDA"])
    write_full_market_coverage(initial, output)
    before_index = json.loads(output.read_text())
    amd_file = before_index["indexes"]["ticker_to_file"]["AMD"]
    nvda_file = before_index["indexes"]["ticker_to_file"]["NVDA"]
    amd_path = output.parent / amd_file
    nvda_path = output.parent / nvda_file
    amd_before = amd_path.read_bytes()
    nvda_before = nvda_path.read_bytes()

    partial = build_full_market_coverage(ROOT, symbols=["NVDA"])
    assert len(partial["cards"]) == 1
    partial["cards"][0]["company"]["display_name"] = "NVIDIA incremental test"
    write_full_market_coverage(partial, output, incremental=True)

    after_index = json.loads(output.read_text())
    assert after_index["indexes"]["ticker_to_file"]["AMD"] == amd_file
    assert after_index["indexes"]["ticker_to_file"]["NVDA"] == nvda_file
    assert amd_path.read_bytes() == amd_before
    assert nvda_path.read_bytes() != nvda_before
    assert after_index["summary"]["incremental"] is True
    assert after_index["summary"]["incremental_updated_company_count"] == 1


@pytest.mark.parametrize("eps_next,revenue_next,expected", [
    ("130", "120", "0.2"),
    ("110", "120", "0.1"),
    ("95", "120", "0.2"),
    ("100", "120", "0.2"),
    (None, "120", "0.2"),
    ("130", None, "0.3"),
    ("130", "100", "0.3"),
    ("130", "90", "0.3"),
    ("250", None, "1.5"),
    ("95", "90", None),
    (None, None, None),
    ("NaN", "Infinity", None),
])
def test_forward_fundamental_peg_growth_selection(eps_next, revenue_next, expected):
    growth, basis = _forward_fundamental_peg_growth({
        "CURRENT_FY": {"eps": "100", "revenue": "100", "peg_growth": "9"},
        "NEXT_FY": {"eps": eps_next, "revenue": revenue_next},
    })
    assert growth == (Decimal(expected) if expected is not None else None)
    assert basis == ("PEG_GROWTH_FORWARD_FUNDAMENTAL_ANCHOR" if expected else None)


def test_current_fy_peg_anchor_matches_unified_contract():
    payload = build_full_market_coverage(ROOT, symbols=["DELL", "NVDA", "SNDK", "MU"])
    assert len(payload["cards"]) == 4
    for card in payload["cards"]:
        horizon = card["valuation_horizons"]["CURRENT_FY"]
        unified = card["valuation"]["unified_contract"]["models"]["peg"]
        assert horizon["growth_basis"] == "PEG_GROWTH_FORWARD_FUNDAMENTAL_ANCHOR"
        assert horizon["models"]["peg"]["status"] == unified["status"] == "calculated"
        assert Decimal(horizon["models"]["peg"]["fair_value"]) == Decimal(unified["fair_value"])
        assert horizon["eps_growth"] == card["estimates"]["normalized_peg_growth"]["value"]


def test_unavailable_anchor_does_not_fall_back_to_legacy_growth(monkeypatch):
    monkeypatch.setattr(
        "axiom_engine.full_market_coverage.core._forward_fundamental_peg_growth",
        lambda annual: (None, None),
    )
    payload = build_full_market_coverage(ROOT, symbols=["NVDA"])
    card = payload["cards"][0]
    assert Decimal(card["estimates"]["forward_eps_growth"]["value"]) > 0
    horizon = card["valuation_horizons"]["CURRENT_FY"]
    unified = card["valuation"]["unified_contract"]["models"]["peg"]
    assert horizon["growth_basis"] is None
    assert horizon["growth_is_horizon_matched"] is False
    assert horizon["models"]["peg"]["status"] == unified["status"] == "unavailable"
    assert horizon["models"]["peg"]["fair_value"] is unified["fair_value"] is None


@pytest.mark.parametrize("base", [None, "0", "-100", "NaN", "Infinity"])
def test_peg_growth_requires_valid_positive_denominators(base):
    assert _forward_fundamental_peg_growth({
        "CURRENT_FY": {"eps": base, "revenue": base},
        "NEXT_FY": {"eps": "100", "revenue": "100"},
    }) == (None, None)


def test_ev_ebitda_uses_canonical_shares_and_target_not_snapshot_or_peg_growth():
    snapshot = {
        "shares_outstanding": "315433188",
        "ebitda_ttm": "17725999104",
        "enterprise_to_ebitda": "99",
        "annual_estimates": {
            "CURRENT_FY": {"eps": "10", "revenue": "100"},
            "NEXT_FY": {"eps": "30", "revenue": "300"},
        },
    }
    financials = {
        "diluted_shares_outstanding": {"value": "684000000"},
        "cash_and_cash_equivalents": {"value": "11528000000"},
        "total_debt": {"value": "31503000000"},
    }
    horizons = _dual_fy_seven_models(
        snapshot, financials, {"target_ev_ebitda": "22.443"}, {}, {}
    )
    for horizon in horizons.values():
        assert Decimal(horizon["models"]["ev_ebitda"]["fair_value"]).quantize(
            Decimal("0.01")
        ) == Decimal("552.41")
    without_target = _dual_fy_seven_models(snapshot, financials, {}, {}, {})
    for horizon in without_target.values():
        assert horizon["models"]["ev_ebitda"]["status"] == "unavailable"


def test_ev_ebitda_horizons_share_unified_result_for_five_companies():
    payload = build_full_market_coverage(ROOT, symbols=["DELL", "NVDA", "AMD", "MU", "SNDK"])
    assert len(payload["cards"]) == 5
    for card in payload["cards"]:
        unified = card["valuation"]["unified_contract"]["models"]["ev_ebitda"]
        for horizon in card["valuation_horizons"].values():
            model = horizon["models"]["ev_ebitda"]
            assert model["status"] == unified["status"]
            assert model["fair_value"] == unified["fair_value"]


def test_peg_does_not_use_other_period_eps_when_current_fy_eps_is_missing():
    payload = build_full_market_coverage(ROOT, symbols=["ALAR"])
    card = payload["cards"][0]
    horizon = card["valuation_horizons"]["CURRENT_FY"]
    assert horizon["eps"] is None
    assert Decimal(card["estimates"]["forward_eps"]["value"]) > 0
    assert Decimal(horizon["eps_growth"]) > 0
    assert horizon["models"]["peg"]["fair_value"] is None
    assert card["valuation"]["unified_contract"]["models"]["peg"]["fair_value"] is None
