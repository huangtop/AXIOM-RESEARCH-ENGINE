from axiom_engine.repository import load_bundle
from axiom_engine.services.research import research_summary
from axiom_engine.services.validator import validate_bundle


def test_research_graph_is_valid():
    b = load_bundle()
    validate_bundle(b)
    s = research_summary(b, "company:US-NVDA")
    assert len(s["drivers"]) == 2
    assert s["catalysts"][0]["catalyst_id"] == "catalyst:NVDA-VERA-RUBIN-QUALIFICATION"


def test_estimate_has_research_support():
    b = load_bundle()
    e = next(x for x in b.estimates if x.estimate_id == "estimate:NVDA-DILUTED-EPS-FORWARD-BASE")
    assert "driver:NVDA-NEXT-GEN-PRODUCT-CYCLE" in e.supported_by_driver_ids
