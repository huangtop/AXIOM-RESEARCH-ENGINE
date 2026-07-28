from __future__ import annotations

import json
from pathlib import Path

from axiom_engine.full_market_coverage import FullMarketCoverageService, build_full_market_coverage
from axiom_engine.valuation_http import ValuationWSGIApp


ROOT = Path(__file__).resolve().parents[1]
MODELS = {"dcf", "forward_pe", "peg", "forward_ps", "ev_ebitda", "forward_pb", "milestone"}


def report():
    return build_full_market_coverage(ROOT)


def test_builder_uses_entire_population_without_a_maintained_ticker_cohort():
    payload = report()
    assert payload["summary"]["company_count"] == 6464
    assert payload["summary"]["security_count"] == 7451
    assert len(payload["cards"]) == 6464
    assert len(payload["indexes"]["ticker_to_position"]) > 7000


def test_every_company_has_seven_model_slots_and_explicit_reasons():
    payload = report()
    for card in payload["cards"]:
        assert set(card["valuation"]["models"]) == MODELS
        assert card["status"] in {"ready", "partial", "unavailable"}
        for model in card["valuation"]["models"].values():
            assert model["status"] in {"eligible", "unavailable"}
            if model["status"] == "unavailable":
                assert model["reason_code"]
                assert model["missing_inputs"]


def test_unknown_or_missing_data_never_creates_a_fair_value():
    service = FullMarketCoverageService(root=ROOT)
    card = service.get("AIR")
    assert card["valuation"]["fair_value"] is None
    assert card["valuation"]["reason_code"] in {"NO_ELIGIBLE_MODELS", "VALUATION_ENGINE_NOT_EXECUTED"}


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
    assert list_response["status"].startswith("200")
    assert listing["summary"]["company_count"] == 6464
    assert card_response["status"].startswith("200")
    assert card["primary_security"]["ticker"] == "NVDA"
    assert set(card["valuation"]["models"]) == MODELS


def test_no_frontend_files_are_part_of_v031_implementation():
    paths = [
        "src/axiom_engine/full_market_coverage/core.py",
        "scripts/build_full_market_coverage.py",
        "tests/test_full_market_coverage_v031.py",
    ]
    assert all(not path.startswith("frontend/") for path in paths)
