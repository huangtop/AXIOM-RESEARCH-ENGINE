import json
from io import BytesIO
from pathlib import Path

from axiom_engine.valuation_card import build_valuation_cards, get_valuation_card, validate_valuation_cards
from axiom_engine.valuation_card.http import ValuationCardWSGIApp

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "valuation_card_fixture" / "research_data"


def test_get_card_maps_research_bundle():
    card = get_valuation_card(ticker="AAPL", research_dir=FIXTURE)
    assert card["market"]["current_price"]["value"] == "210.15"
    assert card["valuation"]["base"]["status"] == "partial"
    assert card["valuation"]["base"]["fair_value"] == "973.8680776418734554283583554"
    assert card["research_confidence"]["score"] == 78


def test_quality_diagnostics_are_visible():
    card = get_valuation_card(ticker="AAPL", research_dir=FIXTURE)
    assert {row["code"] for row in card["quality_diagnostics"]} == {
        "valuation_scenarios_incomplete", "shares_outstanding_mismatch"
    }


def test_all_required_tabs_are_preserved():
    card = get_valuation_card(ticker="AAPL", research_dir=FIXTURE)
    assert list(card["sections"]) == [
        "overview", "company_analysis", "industry_map", "research_notes",
        "valuation", "analyst_growth_ranking", "related_news"
    ]


def test_build_and_validate(tmp_path):
    report = build_valuation_cards(research_dir=FIXTURE, output_dir=tmp_path, write=True)
    assert report["cards_built"] == 1
    validation = validate_valuation_cards(output_dir=tmp_path)
    assert validation["valid"] is True


def test_http_endpoint_returns_card():
    body = json.dumps({"ticker": "AAPL"}).encode()
    environ = {
        "REQUEST_METHOD": "POST", "PATH_INFO": "/v1/research/valuation-card",
        "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": BytesIO(body),
    }
    captured = {}
    def start_response(status, headers):
        captured["status"] = status
    response = b"".join(ValuationCardWSGIApp(str(FIXTURE))(environ, start_response))
    payload = json.loads(response)
    assert captured["status"].startswith("200")
    assert payload["ticker"] == "AAPL"


def test_missing_company_is_explicit():
    try:
        get_valuation_card(ticker="MISSING", research_dir=FIXTURE)
    except Exception as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("missing ticker should fail")
