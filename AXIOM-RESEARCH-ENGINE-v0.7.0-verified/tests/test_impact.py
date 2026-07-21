from axiom_engine.repository import load_bundle
from axiom_engine.services.impact import company_impacts, etf_impacts, impact_summary, propagate_shock


def test_cloud_capex_propagates_to_nvda():
    bundle = load_bundle()
    nodes = propagate_shock(bundle, "shock:CLOUD-AI-CAPEX-DOWN-15")
    by_id = {x.entity_id: x for x in nodes}
    assert by_id["company:US-NVDA"].impact < 0
    assert by_id["company:US-NVDA"].path == [
        "demand_driver:CLOUD-AI-CAPEX",
        "product_architecture:NVDA-VERA-RUBIN",
        "company:US-NVDA",
    ]


def test_company_impact_has_financial_mapping():
    bundle = load_bundle()
    impacts = company_impacts(bundle, "shock:HBM4-SUPPLY-DOWN-20")
    nvda = next(x for x in impacts if x.company_id == "company:US-NVDA")
    assert nvda.estimated_revenue_impact < 0
    assert nvda.estimated_eps_impact <= nvda.estimated_revenue_impact
    assert nvda.estimated_fair_value_impact <= nvda.estimated_eps_impact


def test_etf_impact_aggregates_holding_weight():
    bundle = load_bundle()
    impacts = etf_impacts(bundle, "shock:CLOUD-AI-CAPEX-DOWN-15")
    axsm = next(x for x in impacts if x.etf_id == "etf:AXSM")
    assert axsm.estimated_fair_value_impact < 0
    assert axsm.impact_coverage == 0.5
    assert axsm.contributors[0]["company_id"] == "company:US-NVDA"


def test_impact_summary_discloses_methodology():
    bundle = load_bundle()
    result = impact_summary(bundle, "shock:CLOUD-AI-CAPEX-DOWN-15")
    assert result["methodology"]["graph_direction"] == "cause_to_effect"
    assert result["company_impacts"]
    assert result["etf_impacts"]
