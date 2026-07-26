import json
from pathlib import Path
from subprocess import CompletedProcess

from axiom_engine.production_refresh import (
    build_readiness_assessment,
    build_refresh_report,
    coverage_delta,
    coverage_snapshot,
    overlap_summary,
    run_refresh,
)


def _summary(financial=99, market=2, estimate=1, ready=0):
    return {
        "coverage": {
            "financial": {"linked": financial, "linked_pct": 1.5316, "usable": financial, "usable_pct": 1.5316},
            "market": {"linked": market, "linked_pct": 0.0309, "usable": market, "usable_pct": 0.0309},
            "estimate": {"linked": estimate, "linked_pct": 0.0155, "usable": estimate, "usable_pct": 0.0155},
        },
        "readiness": {"production_ready_company_count": ready},
    }


def _policy():
    return {
        "version": "test-policy",
        "fail_on_coverage_regression": True,
        "minimum_production_ready_company_count": 1,
        "layer_minimums": {
            "financial": {"usable_company_count": 99, "usable_coverage_pct": 1.5316},
            "market": {"usable_company_count": 2, "usable_coverage_pct": 0.0309},
            "estimate": {"usable_company_count": 1, "usable_coverage_pct": 0.0155},
        },
    }


def test_coverage_snapshot_reads_coverage_v2():
    snapshot = coverage_snapshot(_summary())
    assert snapshot["financial"]["usable_company_count"] == 99
    assert snapshot["market"]["usable_coverage_pct"] == 0.0309
    assert snapshot["production"]["ready_company_count"] == 0


def test_coverage_delta_reports_company_and_percentage_changes():
    before = coverage_snapshot(_summary())
    after = coverage_snapshot(_summary(financial=100, market=3, estimate=2, ready=1))
    delta = coverage_delta(before, after)
    assert delta["financial"]["usable_company_count"] == 1
    assert delta["market"]["linked_company_count"] == 1
    assert delta["production"]["ready_company_count"] == 1


def test_overlap_summary_counts_layer_combinations():
    rows = [
        {"company_id": "c1", "data_usability": {"financial": True, "market": False, "estimate": True}},
        {"company_id": "c2", "data_usability": {"financial": False, "market": True, "estimate": False}},
        {"company_id": "c3", "data_usability": {"financial": True, "market": True, "estimate": True}},
    ]
    result = overlap_summary(rows)
    assert result["usable_layer_combinations"]["financial+estimate"] == 1
    assert result["usable_layer_combinations"]["market"] == 1
    assert result["production_ready_company_ids"] == ["c3"]


def test_readiness_assessment_identifies_cross_layer_overlap_blocker():
    after = coverage_snapshot(_summary())
    delta = coverage_delta(after, after)
    index = [{"company_id": "c1", "data_usability": {"financial": True, "market": False, "estimate": True}}]
    assessment = build_readiness_assessment(after, delta, index, _policy(), [{"name": "all", "returncode": 0}])
    assert assessment["status"] == "blocked"
    assert "production_ready_minimum" in assessment["blockers"]
    assert assessment["next_actions"][0] == "increase_cross_layer_company_overlap"


def test_readiness_assessment_qualifies_when_all_gates_pass():
    after = coverage_snapshot(_summary(ready=1))
    delta = coverage_delta(after, after)
    index = [{"company_id": "c1", "data_usability": {"financial": True, "market": True, "estimate": True}}]
    assessment = build_readiness_assessment(after, delta, index, _policy(), [{"name": "all", "returncode": 0}])
    assert assessment["status"] == "qualified"
    assert assessment["blockers"] == []


def test_readiness_assessment_detects_coverage_regression():
    before = coverage_snapshot(_summary(financial=100))
    after = coverage_snapshot(_summary(financial=99))
    delta = coverage_delta(before, after)
    assessment = build_readiness_assessment(after, delta, [], _policy(), [{"name": "all", "returncode": 0}])
    assert "no_coverage_regression" in assessment["blockers"]


def test_refresh_report_marks_failed_stage():
    report = build_refresh_report(_summary(), _summary(), [{"name": "build", "returncode": 2}])
    assert report["status"] == "failed"
    assert report["schema_version"] == "production-refresh-report.v030.7.0"
    assert report["readiness_assessment"]["status"] == "blocked"


def test_run_refresh_stops_after_failure_and_writes_report(tmp_path: Path):
    summary_dir = tmp_path / "data/generated/production_population"
    summary_dir.mkdir(parents=True)
    (summary_dir / "production_population_summary.json").write_text(json.dumps(_summary()), encoding="utf-8")
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        code = 0 if len(calls) == 1 else 2
        return CompletedProcess(argv, code, stdout="ok", stderr="boom" if code else "")

    output = tmp_path / "data/generated/production_refresh/refresh_report.json"
    report = run_refresh(tmp_path, [
        {"name": "expand", "argv": ["python", "expand.py"]},
        {"name": "discover", "argv": ["python", "discover.py"]},
        {"name": "build", "argv": ["python", "build.py"]},
    ], output, runner=runner, readiness_policy=_policy())
    assert report["status"] == "failed"
    assert len(calls) == 2
    assert output.exists()


def test_overlap_targets_prioritize_one_missing_layer():
    from axiom_engine.production_refresh import build_overlap_targets
    rows = [
        {"company_id": "c_fin_est", "ticker": "AAA", "data_usability": {"financial": True, "market": False, "estimate": True}},
        {"company_id": "c_fin", "ticker": "BBB", "data_usability": {"financial": True, "market": False, "estimate": False}},
        {"company_id": "c_fin_mkt", "ticker": "CCC", "data_usability": {"financial": True, "market": True, "estimate": False}},
    ]
    result = build_overlap_targets(rows)
    assert result["immediate_ready_opportunity_count"] == 2
    assert [x["company_id"] for x in result["targets"][:2]] == ["c_fin_mkt", "c_fin_est"]
    assert result["targets"][0]["missing_layers"] == ["estimate"]


def test_overlap_targets_exclude_empty_and_ready_companies():
    from axiom_engine.production_refresh import build_overlap_targets
    rows = [
        {"company_id": "empty", "data_usability": {}},
        {"company_id": "ready", "data_usability": {"financial": True, "market": True, "estimate": True}},
        {"company_id": "candidate", "data_usability": {"financial": True}},
    ]
    result = build_overlap_targets(rows)
    assert result["candidate_count"] == 1
    assert result["targets"][0]["company_id"] == "candidate"


def test_refresh_report_embeds_overlap_targets():
    rows = [{"company_id": "c1", "ticker": "AAA", "data_usability": {"financial": True, "market": True, "estimate": False}}]
    report = build_refresh_report(_summary(), _summary(), [{"name": "all", "returncode": 0}], index_rows=rows, readiness_policy=_policy())
    assert report["schema_version"] == "production-refresh-report.v030.7.0"
    assert report["overlap_targets"]["targets"][0]["recommended_action"] == "populate_estimate"


def test_run_refresh_writes_targets_artifact(tmp_path: Path):
    summary_dir = tmp_path / "data/generated/production_population"
    summary_dir.mkdir(parents=True)
    (summary_dir / "production_population_summary.json").write_text(json.dumps(_summary()), encoding="utf-8")
    (summary_dir / "population_index.json").write_text(json.dumps([
        {"company_id": "c1", "ticker": "AAA", "data_usability": {"financial": True, "market": False, "estimate": True}}
    ]), encoding="utf-8")
    def runner(argv, **kwargs):
        return CompletedProcess(argv, 0, stdout="ok", stderr="")
    output = tmp_path / "data/generated/production_refresh/refresh_report.json"
    targets = tmp_path / "data/generated/production_refresh/overlap_targets.json"
    run_refresh(tmp_path, [{"name": "all", "argv": ["python", "x.py"]}], output, runner=runner, readiness_policy=_policy(), targets_output_path=targets)
    payload = json.loads(targets.read_text(encoding="utf-8"))
    assert payload["target_count"] == 1
    assert payload["targets"][0]["company_id"] == "c1"


def test_provider_worklists_split_targets_by_missing_layer():
    from axiom_engine.production_refresh import build_provider_worklists
    targets = {
        "schema_version": "cross-layer-overlap-targets.v030.6.7",
        "targets": [
            {"company_id": "nvda", "ticker": "NVDA", "usable_layers": ["financial", "market"], "missing_layers": ["estimate"], "missing_layer_count": 1, "priority_tier": "one_layer_to_ready"},
            {"company_id": "aapl", "ticker": "AAPL", "usable_layers": ["financial", "estimate"], "missing_layers": ["market"], "missing_layer_count": 1, "priority_tier": "one_layer_to_ready"},
            {"company_id": "amd", "ticker": "AMD", "usable_layers": ["financial"], "missing_layers": ["market", "estimate"], "missing_layer_count": 2, "priority_tier": "two_layers_to_ready"},
        ],
    }
    result = build_provider_worklists(targets)
    assert [x["ticker"] for x in result["worklists"]["estimate"]] == ["NVDA", "AMD"]
    assert [x["ticker"] for x in result["worklists"]["market"]] == ["AAPL", "AMD"]
    assert result["immediate_ready_opportunities_by_layer"] == {"financial": 0, "market": 1, "estimate": 1}
    assert result["potential_production_ready_uplift"] == 2


def test_provider_worklists_have_required_provider_fields():
    from axiom_engine.production_refresh import build_provider_worklists
    result = build_provider_worklists({"targets": [
        {"company_id": "c1", "ticker": "AAA", "usable_layers": ["financial", "market"], "missing_layers": ["estimate"], "missing_layer_count": 1, "priority_tier": "one_layer_to_ready"}
    ]})
    row = result["worklists"]["estimate"][0]
    assert "forward_revenue_or_eps" in row["required_fields"]
    assert row["immediate_production_ready_uplift"] is True
    assert row["priority_rank"] == 1


def test_run_refresh_writes_provider_worklists_json_and_csv(tmp_path: Path):
    summary_dir = tmp_path / "data/generated/production_population"
    summary_dir.mkdir(parents=True)
    (summary_dir / "production_population_summary.json").write_text(json.dumps(_summary()), encoding="utf-8")
    (summary_dir / "population_index.json").write_text(json.dumps([
        {"company_id": "c1", "ticker": "AAA", "data_usability": {"financial": True, "market": True, "estimate": False}}
    ]), encoding="utf-8")
    def runner(argv, **kwargs):
        return CompletedProcess(argv, 0, stdout="ok", stderr="")
    output = tmp_path / "data/generated/production_refresh/refresh_report.json"
    workdir = tmp_path / "data/generated/production_refresh/provider_worklists"
    report = run_refresh(tmp_path, [{"name": "all", "argv": ["python", "x.py"]}], output, runner=runner, readiness_policy=_policy(), worklists_output_dir=workdir)
    assert report["schema_version"] == "production-refresh-report.v030.7.0"
    assert (workdir / "provider_worklists.json").exists()
    assert (workdir / "estimate_population_worklist.json").exists()
    csv_text = (workdir / "estimate_population_worklist.csv").read_text(encoding="utf-8")
    assert "AAA" in csv_text
    assert "forward_revenue_or_eps" in csv_text

def test_provider_batch_contracts_are_deterministic_and_layered():
    from axiom_engine.production_refresh import build_provider_batch_contracts
    worklists={"worklists":{"financial":[],"market":[{"company_id":"c1","ticker":"AAPL","priority_rank":1,"required_fields":["price"]}],"estimate":[]}}
    first=build_provider_batch_contracts(worklists); second=build_provider_batch_contracts(worklists)
    req=first["batches"]["market"]["requests"][0]
    assert req["request_id"]==second["batches"]["market"]["requests"][0]["request_id"]
    assert first["request_count_by_layer"]=={"financial":0,"market":1,"estimate":0}


def test_provider_batch_response_validation_accepts_matching_observation():
    from axiom_engine.production_refresh import build_provider_batch_contracts, validate_provider_batch_response
    contracts=build_provider_batch_contracts({"worklists":{"financial":[],"market":[{"company_id":"c1","ticker":"AAPL","required_fields":["price"]}],"estimate":[]}})
    batch=contracts["batches"]["market"]; req=batch["requests"][0]
    response={"schema_version":"provider-batch-response.v030.6.9","batch_id":batch["batch_id"],"target_layer":"market","provider":"licensed_market","observations":[{"request_id":req["request_id"],"company_id":"c1","provider_record_id":"p1","observed_at":"2026-07-26T00:00:00Z","data":{"price":200}}]}
    result=validate_provider_batch_response(response,batch)
    assert result["valid"] is True
    assert result["accepted_count"]==1


def test_provider_batch_response_validation_rejects_identity_mismatch_and_duplicates():
    from axiom_engine.production_refresh import build_provider_batch_contracts, validate_provider_batch_response
    contracts=build_provider_batch_contracts({"worklists":{"financial":[],"market":[],"estimate":[{"company_id":"c1","ticker":"NVDA","required_fields":["forward_eps"]}]}})
    batch=contracts["batches"]["estimate"]; req=batch["requests"][0]
    obs={"request_id":req["request_id"],"company_id":"wrong","provider_record_id":"p1","observed_at":"2026-07-26","data":{"forward_eps":1}}
    result=validate_provider_batch_response({"schema_version":"provider-batch-response.v030.6.9","batch_id":batch["batch_id"],"target_layer":"estimate","provider":"licensed","observations":[obs,obs]},batch)
    assert result["valid"] is False
    assert result["rejected_count"]==2
    assert result["rejected_observations"][0]["reason"]=="company_id_mismatch"


def test_provider_response_import_canonicalizes_market_fact():
    from axiom_engine.production_refresh import build_provider_batch_contracts, import_provider_batch_response
    contracts = build_provider_batch_contracts({"worklists":{"financial":[],"market":[{"company_id":"c1","ticker":"AAPL","required_fields":["price"]}],"estimate":[]}})
    batch = contracts["batches"]["market"]; request = batch["requests"][0]
    response = {"schema_version":"provider-batch-response.v030.6.9","batch_id":batch["batch_id"],"target_layer":"market","provider":"licensed_market","observations":[{"request_id":request["request_id"],"company_id":"c1","provider_record_id":"m1","observed_at":"2026-07-26T00:00:00Z","data":{"price":"215.42","currency":"USD","session_date":"2026-07-25"}}]}
    result = import_provider_batch_response(response, batch)
    assert result["valid"] is True
    assert result["canonical_rows"][0]["semantic_type"] == "market_fact"
    assert result["canonical_rows"][0]["price"] == 215.42
    assert result["inserted_count"] == 1


def test_provider_response_import_canonicalizes_estimate_fact():
    from axiom_engine.production_refresh import build_provider_batch_contracts, import_provider_batch_response
    contracts = build_provider_batch_contracts({"worklists":{"financial":[],"market":[],"estimate":[{"company_id":"c1","ticker":"NVDA","required_fields":["forward_eps"]}]}})
    batch = contracts["batches"]["estimate"]; request = batch["requests"][0]
    response = {"schema_version":"provider-batch-response.v030.6.9","batch_id":batch["batch_id"],"target_layer":"estimate","provider":"licensed_estimate","observations":[{"request_id":request["request_id"],"company_id":"c1","provider_record_id":"e1","observed_at":"2026-07-26T00:00:00Z","data":{"forward_eps":5.25,"fiscal_period":"FY2027","period_end":"2027-01-31","currency":"USD"}}]}
    result = import_provider_batch_response(response, batch)
    assert result["valid"] is True
    row = result["canonical_rows"][0]
    assert row["semantic_type"] == "estimate_fact"
    assert row["metric"] == "forward_eps"
    assert row["value"] == 5.25


def test_provider_response_import_rejects_semantically_invalid_market_data():
    from axiom_engine.production_refresh import build_provider_batch_contracts, import_provider_batch_response
    contracts = build_provider_batch_contracts({"worklists":{"financial":[],"market":[{"company_id":"c1","ticker":"AAPL","required_fields":["price"]}],"estimate":[]}})
    batch = contracts["batches"]["market"]; request = batch["requests"][0]
    response = {"schema_version":"provider-batch-response.v030.6.9","batch_id":batch["batch_id"],"target_layer":"market","provider":"licensed_market","observations":[{"request_id":request["request_id"],"company_id":"c1","provider_record_id":"m1","observed_at":"2026-07-26T00:00:00Z","data":{"price":"bad","currency":"USD","session_date":"2026-07-25"}}]}
    result = import_provider_batch_response(response, batch)
    assert result["valid"] is False
    assert result["canonical_rejections"][0]["reason"] == "invalid_market_price"


def test_provider_response_import_is_idempotent_by_provider_record():
    from axiom_engine.production_refresh import build_provider_batch_contracts, import_provider_batch_response
    contracts = build_provider_batch_contracts({"worklists":{"financial":[],"market":[{"company_id":"c1","ticker":"AAPL","required_fields":["price"]}],"estimate":[]}})
    batch = contracts["batches"]["market"]; request = batch["requests"][0]
    response = {"schema_version":"provider-batch-response.v030.6.9","batch_id":batch["batch_id"],"target_layer":"market","provider":"licensed_market","observations":[{"request_id":request["request_id"],"company_id":"c1","provider_record_id":"m1","observed_at":"2026-07-26T00:00:00Z","data":{"price":215,"currency":"USD","session_date":"2026-07-25"}}]}
    first = import_provider_batch_response(response, batch)
    second = import_provider_batch_response(response, batch, first["ledger_rows"])
    assert second["inserted_count"] == 0
    assert second["updated_count"] == 1
    assert second["ledger_record_count"] == 1


def test_provider_response_content_hash_is_deterministic_for_dicts():
    from axiom_engine.production_refresh import provider_response_content_hash
    assert provider_response_content_hash({"b": 2, "a": 1}) == provider_response_content_hash({"a": 1, "b": 2})


def test_provider_archive_filename_contains_status_and_hash():
    from axiom_engine.production_refresh import provider_archive_filename
    name = provider_archive_filename("market_batch_response.json", "abcdef1234567890", status="accepted")
    assert name == "market_batch_response.accepted.abcdef123456.json"


def test_provider_intake_receipt_captures_import_counts():
    from axiom_engine.production_refresh import build_provider_intake_receipt
    receipt = build_provider_intake_receipt(response_path="inbox/market.json", content_hash="abc", status="accepted", layer="market", import_report={"batch_id":"b1","provider":"licensed","canonicalized_count":1,"inserted_count":1,"updated_count":0})
    assert receipt["schema_version"] == "provider-intake-receipt.v030.7.1"
    assert receipt["status"] == "accepted"
    assert receipt["inserted_count"] == 1


def test_provider_intake_receipt_captures_failure_reason():
    from axiom_engine.production_refresh import build_provider_intake_receipt
    receipt = build_provider_intake_receipt(response_path="inbox/bad.json", content_hash="bad", status="failed", failure_reason="missing_batch_request")
    assert receipt["failure_reason"] == "missing_batch_request"


def test_provider_delivery_reconciliation_tracks_fulfilled_requests():
    from axiom_engine.production_refresh import build_provider_delivery_reconciliation
    batches={"market":{"batch_id":"b1","requests":[{"request_id":"r1","immediate_production_ready_uplift":True},{"request_id":"r2","immediate_production_ready_uplift":False}]}}
    result=build_provider_delivery_reconciliation(batches,{"market":[{"source_request_id":"r1"}]})
    assert result["layers"]["market"]["status"]=="partial"
    assert result["fulfilled_request_count"]==1
    assert result["realized_ready_uplift"]==1

def test_provider_delivery_reconciliation_reports_complete_layer():
    from axiom_engine.production_refresh import build_provider_delivery_reconciliation
    batches={"estimate":{"batch_id":"b2","requests":[{"request_id":"e1"}]}}
    result=build_provider_delivery_reconciliation(batches,{"estimate":[{"source_request_id":"e1"}]})
    assert result["layers"]["estimate"]["status"]=="complete"
    assert result["unfulfilled_request_count"]==0

def test_provider_delivery_reconciliation_counts_receipts_and_duplicates():
    from axiom_engine.production_refresh import build_provider_delivery_reconciliation
    result=build_provider_delivery_reconciliation({"market":{"requests":[]}}, {}, [{"target_layer":"market","status":"accepted"},{"target_layer":"market","status":"failed"}], {"market":2})
    row=result["layers"]["market"]
    assert row["accepted_receipt_count"]==1
    assert row["failed_receipt_count"]==1
    assert row["duplicate_delivery_count"]==2
