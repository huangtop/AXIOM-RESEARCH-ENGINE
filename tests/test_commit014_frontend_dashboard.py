from pathlib import Path


CLIENT = Path("frontend/axiom-valuation-client.js")
DASHBOARD = Path("frontend/axiom-valuation-dashboard.js")
WORDPRESS = Path("frontend/wordpress/axiom-valuation-api.php")


def test_wordpress_adapter_uses_production_api_base_and_shortcode():
    source = WORDPRESS.read_text()
    assert "http://127.0.0.1:8765" in source
    assert "add_shortcode('axiom_valuation'" in source
    assert 'type="module"' in source


def test_dashboard_uses_v03014_snapshot_contract():
    source = CLIENT.read_text() + DASHBOARD.read_text()
    assert "/v1/fair-values/" in source
    assert "client.list()" in source
    assert "data-axiom-company" in source
    assert "/v1/valuations" not in source
    for model in ("dcf", "peer", "historical"):
        assert model in source
    for field in (
        "valuation_card",
        "current_price",
        "fair_value",
        "range_low",
        "range_high",
        "upside",
        "rating",
        "confidence",
        "snapshot_version",
    ):
        assert field in source


def test_dashboard_renders_ready_blocked_and_unavailable_states():
    source = CLIENT.read_text() + DASHBOARD.read_text()
    assert "ready" in source
    assert "blocked" in source
    assert "Valuation unavailable" in source
    assert "Unknown valuation error" in source


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
    assert 'method: "GET"' in source


def test_dashboard_has_transport_and_invalid_json_errors():
    source = CLIENT.read_text() + DASHBOARD.read_text()
    assert "Unable to reach the AXIOM valuation API" in source
    assert "invalid JSON" in source


def test_http_api_exposes_cors_for_browser_frontend():
    source = Path("src/axiom_engine/valuation_http.py").read_text()
    assert 'method == "OPTIONS"' in source
    assert "Access-Control-Allow-Origin" in source
    assert "AXIOM_CORS_ORIGIN" in source
