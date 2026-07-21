from axiom_engine.repository import load_bundle
from axiom_engine.services.etf import derive_theme_exposures, derive_valuation_snapshot, etf_summary


def test_etf_holdings_and_theme_exposure():
    bundle = load_bundle()
    payload = etf_summary(bundle, "etf:AXSM")
    assert len(payload["holdings"]) == 3
    exposure_ids = {x["entity_id"] for x in payload["theme_exposures"]}
    assert "technology:HBM4" in exposure_ids
    assert "technology:TSMC-COWOS" in exposure_ids
    assert "demand_driver:CLOUD-AI-CAPEX" in exposure_ids


def test_etf_valuation_coverage():
    snapshot = derive_valuation_snapshot(load_bundle(), "etf:AXSM")
    assert snapshot.valuation_coverage == 0.5
    assert snapshot.weighted_upside is not None
    assert "company:TW-2330" in snapshot.missing_company_ids


def test_derived_exposure_formula():
    exposures = {x.entity_id: x for x in derive_theme_exposures(load_bundle(), "etf:AXSM")}
    assert exposures["technology:HBM4"].derived_weight == 0.425
    assert exposures["technology:TSMC-COWOS"].derived_weight == 0.4
