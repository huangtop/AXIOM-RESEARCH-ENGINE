import json
from pathlib import Path

from axiom_engine.multiple_policy import build_multiple_policy


def test_only_ready_historical_benchmarks_become_evidence_backed_assumptions(tmp_path: Path):
    payload = {"schema_version": "historical-multiple-benchmark.v030.13.3", "benchmarks": [
        {"company_id": "c1", "method": "forward_pe", "status": "ready", "confidence": "high", "selected_window": "252d", "latest_observation_date": "2026-07-28", "benchmark": {"target_multiple": 22}},
        {"company_id": "c1", "method": "price_to_book", "status": "ready", "confidence": "medium", "selected_window": "60d", "latest_observation_date": "2026-07-28", "benchmark": {"target_multiple": 3}},
        {"company_id": "c2", "method": "ev_to_ebitda", "status": "ready", "confidence": "low", "benchmark": {"target_multiple": 12}},
    ]}
    path = tmp_path / "data/generated/historical_multiple_benchmark/historical_multiple_benchmark.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload))
    report = build_multiple_policy(tmp_path)
    assert report["companies"][0]["assumptions"] == {"target_forward_pe": 22, "target_forward_pb": 3}
    assert len(report["companies"][0]["evidence_ids"]) == 2
    assert report["policy"]["current_spot_multiple_as_target"] == "allowed_for_explicit_market_roll_forward_models"


def test_milestone_and_peg_are_not_created_without_their_own_evidence(tmp_path: Path):
    payload = {"schema_version": "historical-multiple-benchmark.v030.13.3", "benchmarks": []}
    path = tmp_path / "data/generated/historical_multiple_benchmark/historical_multiple_benchmark.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload))
    report = build_multiple_policy(tmp_path)
    assert report["companies"] == []


def test_market_multiples_drive_roll_forward_without_using_analyst_target_for_peg(tmp_path: Path):
    snapshot = {"symbols": {"AAA": {
        "fetched_at": "2026-07-28T00:00:00+00:00", "analyst_count": 10,
        "analyst_target_mean": "120", "forward_eps": "6", "forward_eps_growth": "0.2",
        "forward_revenue": "1000", "shares_outstanding": "10", "ebitda_ttm": "80",
        "total_debt": "20", "total_cash": "10", "previous_close": "100", "price_to_book": "5",
        "trailing_pe": "25", "revenue_ttm": "800", "enterprise_to_ebitda": "14"
    }}}
    company_path = tmp_path / "data/generated/company/yahoo_company_snapshot.json"
    company_path.parent.mkdir(parents=True)
    company_path.write_text(json.dumps(snapshot))
    universe = tmp_path / "data/universe"
    universe.mkdir(parents=True)
    (universe / "securities.json").write_text(json.dumps([{"ticker": "AAA", "company_id": "c1"}]))
    report = build_multiple_policy(tmp_path)
    company = report["companies"][0]
    assert company["assumptions"] == {
        "target_forward_pe": 20.0,
        "target_forward_ps": 1.25,
        "target_ev_ebitda": 14.0,
        "target_forward_pb": 5.0,
    }
    assert "target_peg" not in company["assumptions"]
    assert company["policy_version"] == "yahoo-consensus-and-market-roll-forward.v031v.10"
    assert report["policy"]["analyst_target_as_multiple_source"] == "allowed_for_forward_pe_consensus_scenario_only"
    assert report["policy"]["peg_policy"] == "independent_classified_peer_profile_median"
