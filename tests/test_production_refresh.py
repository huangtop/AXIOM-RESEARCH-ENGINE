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
    assert report["schema_version"] == "production-refresh-report.v030.6.6"
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
