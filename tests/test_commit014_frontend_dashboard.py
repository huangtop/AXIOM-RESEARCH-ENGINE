from pathlib import Path


CLIENT = Path("frontend/axiom-valuation-client.js")
DASHBOARD = Path("frontend/axiom-valuation-dashboard.js")
WORDPRESS = Path("frontend/wordpress/axiom-valuation-api.php")


def test_wordpress_adapter_uses_production_api_base_and_shortcode():
    source = WORDPRESS.read_text()
    assert "http://127.0.0.1:8765" in source
    assert "/v1/valuations/legacy" not in source
    assert "add_shortcode('axiom_valuation'" in source
    assert 'type="module"' in source


def test_dashboard_supports_ticker_and_scenario_switching():
    source = DASHBOARD.read_text()
    assert "data-axiom-ticker" in source
    assert "data-axiom-scenario" in source
    assert "scenarioId" in source
    assert "available_scenarios" in source


def test_dashboard_renders_all_six_models_and_states():
    source = DASHBOARD.read_text()
    for model in ("forward_pe", "peg", "forward_ps", "ev_ebitda", "forward_pb", "milestone"):
        assert model in source
    for state in ("completed", "skipped", "unavailable"):
        assert state in source
    assert "reason_zh_tw" in source
    assert "warnings" in source


def test_dashboard_renders_summary_reference_price_and_provenance():
    source = DASHBOARD.read_text()
    for field in (
        "blended_fair_value",
        "blended_upside",
        "reference_price",
        "reference_price_date",
        "data_provenance",
    ):
        assert field in source


def test_frontend_is_read_only_and_has_no_valuation_formula_or_financial_payload():
    source = CLIENT.read_text() + DASHBOARD.read_text()
    forbidden = (
        "research_payload",
        "forward_eps",
        "target_pe",
        "target_peg",
        "ebitda *",
        "fair_value =",
        "implied_pe",
        "success_probability *",
    )
    assert not any(token in source for token in forbidden)
    assert "/v1/valuations" in source


def test_dashboard_has_api_and_missing_data_error_state():
    source = CLIENT.read_text() + DASHBOARD.read_text()
    assert "Unable to reach the AXIOM valuation API" in source
    assert "Valuation unavailable" in source
    assert "invalid JSON" in source
    assert "Unknown valuation error" in source


def test_http_api_exposes_cors_for_browser_frontend():
    source = Path("src/axiom_engine/valuation_http.py").read_text()
    assert 'method == "OPTIONS"' in source
    assert "Access-Control-Allow-Origin" in source
    assert "AXIOM_CORS_ORIGIN" in source
