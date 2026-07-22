from pathlib import Path


def test_frontend_has_no_valuation_formula():
    source = Path("frontend/axiom-valuation-client.js").read_text()
    forbidden = ["forward_eps *", "growth_percent *", "ebitda *", "fair =", "impliedPE"]

    assert not any(token in source for token in forbidden)
    assert "/v1/valuations" in source
    assert "fair_value" in source
    assert "research_payload" not in source
    assert "/v1/valuations/legacy" not in source
