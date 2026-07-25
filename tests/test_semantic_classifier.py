from axiom_engine.semantic import SemanticType, classify_semantic_type


def test_valuation_result_is_not_market_fact():
    rows = [{
        "company_id": "company:1",
        "security_id": "security:1",
        "ticker": "AAA",
        "market_price": 100,
        "fair_value": 125,
        "valuation_method": "dcf",
        "implied_upside": 0.25,
    }]
    result = classify_semantic_type("data/generated/valuation_snapshots.json", rows)
    assert result.semantic_type is SemanticType.VALUATION_RESULT
    assert result.eligible_layers == ()


def test_market_fact_is_market_eligible():
    rows = [{"ticker": "AAA", "last_price": 100, "quote_time": "2026-07-25T00:00:00Z"}]
    result = classify_semantic_type("data/providers/market_quotes.json", rows)
    assert result.semantic_type is SemanticType.MARKET_FACT
    assert result.eligible_layers == ("market",)


def test_template_is_never_population_eligible():
    rows = [{"company_id": "company:1", "forward_eps": "", "target_price": ""}]
    result = classify_semantic_type("data/onboarding/estimate_template.csv", rows)
    assert result.semantic_type is SemanticType.TEMPLATE
    assert result.eligible_layers == ()


def test_financial_fact_classification():
    rows = [{"company_id": "company:1", "revenue": 10, "net_income": 2, "assets": 50}]
    result = classify_semantic_type("data/provider/company_facts.json", rows)
    assert result.semantic_type is SemanticType.FINANCIAL_FACT
    assert result.eligible_layers == ("financial",)
