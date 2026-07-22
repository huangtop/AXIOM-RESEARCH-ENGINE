from axiom_engine.repository import load_bundle
from axiom_engine.services.validator import validate_bundle


def test_bundle_validates():
    summary = validate_bundle(load_bundle())
    assert summary.counts["entities"] == 14
    assert summary.counts["securities"] == 4
    assert summary.counts["estimates"] == 12
    assert summary.counts["valuation_profiles"] == 2
