from decimal import Decimal

from axiom_engine.seven_model_valuation import calculate_seven_models


def metric(value):
    return {"value": str(value)}


def test_all_seven_formula_contracts_calculate_with_complete_evidence_inputs():
    financials = {
        "free_cash_flow": metric(100), "diluted_shares_outstanding": metric(10),
        "cash_and_cash_equivalents": metric(50), "total_debt": metric(20),
        "ebitda": metric(80), "book_value_per_share": metric(12),
    }
    estimates = {"forward_eps": metric(5), "forward_eps_growth": metric("0.20"), "forward_revenue": metric(1000), "forward_ebitda": metric(90)}
    assumptions = {
        "target_forward_pe": 20, "target_peg": 1, "target_forward_ps": 3,
        "target_ev_ebitda": 10, "target_forward_pb": 2,
        "milestone_success_probability": "0.6", "milestone_success_value_per_share": 200,
        "milestone_failure_value_per_share": 50,
    }
    models = calculate_seven_models(financials, estimates, assumptions, dcf_policy={"forecast_years": 5, "discount_rate": "0.10", "terminal_growth": "0.03", "default_growth": "0.08"})
    assert all(row["status"] == "calculated" for row in models.values())
    assert Decimal(models["forward_pe"]["fair_value"]) == 100
    assert Decimal(models["peg"]["fair_value"]) == 100
    assert Decimal(models["forward_ps"]["fair_value"]) == 300
    assert Decimal(models["ev_ebitda"]["fair_value"]) == 93
    assert Decimal(models["forward_pb"]["fair_value"]) == 24
    assert Decimal(models["milestone"]["fair_value"]) == 140


def test_missing_estimates_and_knowledge_assumptions_remain_unavailable_not_fabricated():
    models = calculate_seven_models({}, {}, {}, dcf_policy={"forecast_years": 5, "discount_rate": "0.10", "terminal_growth": "0.03", "default_growth": "0.08"})
    assert set(models) == {"dcf", "forward_pe", "peg", "forward_ps", "ev_ebitda", "forward_pb", "milestone"}
    assert all(row["status"] == "unavailable" and row["fair_value"] is None for row in models.values())
    assert "target_forward_pe" in models["forward_pe"]["missing_inputs"]
    assert "cash_and_cash_equivalents" in models["dcf"]["missing_inputs"]
    assert models["forward_pe"]["assumption_source"] == "knowledge.valuation_assumptions"
