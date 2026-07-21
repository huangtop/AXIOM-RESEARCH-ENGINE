from axiom_engine.repository import load_bundle
from axiom_engine.services.industry import find_paths, industry_summary
from axiom_engine.services.validator import validate_bundle


def test_industry_graph_validates():
    bundle = load_bundle()
    summary = validate_bundle(bundle)
    assert summary.counts["industry_edges"] == 7
    assert summary.counts["industry_exposures"] == 3


def test_nvda_industry_summary():
    payload = industry_summary(load_bundle(), "company:US-NVDA")
    assert len(payload["exposures"]) == 3
    assert any(x["entity_id"] == "technology:HBM4" for x in payload["entities"])


def test_supply_path_to_nvda():
    paths = find_paths(load_bundle(), "company:KR-000660", "company:US-NVDA")
    assert [
        "company:KR-000660",
        "technology:HBM4",
        "product_architecture:NVDA-VERA-RUBIN",
        "company:US-NVDA",
    ] in paths


def test_causal_edges_use_cause_to_effect_direction():
    bundle = load_bundle()
    edge = next(x for x in bundle.industry_edges if x.edge_id == "industry_edge:CLOUD-CAPEX-DRIVES-RUBIN")
    assert edge.source_entity_id == "demand_driver:CLOUD-AI-CAPEX"
    assert edge.target_entity_id == "product_architecture:NVDA-VERA-RUBIN"
    assert edge.edge_type.value == "drives_demand_for"
