from axiom_engine.repository import load_bundle
from axiom_engine.services.validator import validate_bundle


def test_bundle_validates():
    summary = validate_bundle(load_bundle())
    assert summary.entities == 6
    assert summary.securities == 4
    assert summary.estimates == 6
    assert summary.valuation_profiles == 2
