from pathlib import Path


def test_frontend_calls_production_endpoint_without_financial_payload():
    text = Path("frontend/axiom-valuation-client.js").read_text()
    assert "/v1/valuations" in text
    assert "research_payload" not in text
    assert "forward_eps" not in text
    assert "target_pe" not in text
    assert "fair_value" in text
