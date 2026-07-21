from axiom_engine.repository import load_bundle
from axiom_engine.services.valuation import run_valuation_book


def test_nvda_multi_model_book():
    executions, snapshots, book = run_valuation_book(
        load_bundle(),
        company_id="company:US-NVDA",
        security_id="security:NASDAQ-NVDA",
        scenario_id="valuation_scenario:NVDA-2026Q3-BASE",
    )
    assert len(executions) == 4
    assert len(snapshots) == 4
    results = {x.model_type: x for x in snapshots}
    assert round(results["forward_pe"].fair_value_per_share, 4) == 384.939
    assert round(results["forward_ps"].fair_value_per_share, 4) == 202.7438
    assert round(results["forward_pb"].fair_value_per_share, 4) == 293.9901
    assert round(results["ev_ebitda"].fair_value_per_share, 3) == 202.632
    assert book.blended_fair_value is not None


def test_snapshot_id_is_deterministic():
    bundle = load_bundle()
    _, first, _ = run_valuation_book(
        bundle,
        company_id="company:US-NVDA",
        security_id="security:NASDAQ-NVDA",
        scenario_id="valuation_scenario:NVDA-2026Q3-BASE",
    )
    ids = {x.valuation_snapshot_id for x in first}
    _, second, _ = run_valuation_book(
        bundle,
        company_id="company:US-NVDA",
        security_id="security:NASDAQ-NVDA",
        scenario_id="valuation_scenario:NVDA-2026Q3-BASE",
        existing_snapshot_ids=ids,
    )
    assert second == []
