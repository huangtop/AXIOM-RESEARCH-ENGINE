from __future__ import annotations

import json
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
