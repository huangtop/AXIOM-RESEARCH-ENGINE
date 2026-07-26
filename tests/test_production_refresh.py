from pathlib import Path
from subprocess import CompletedProcess

from axiom_engine.production_refresh import build_refresh_report, coverage_delta, coverage_snapshot, run_refresh


def _summary(financial=99, market=2, estimate=1, ready=0):
    return {
        "coverage": {
            "financial": {"linked": financial, "linked_pct": 1.5316, "usable": financial, "usable_pct": 1.5316},
            "market": {"linked": market, "linked_pct": 0.0309, "usable": market, "usable_pct": 0.0309},
            "estimate": {"linked": estimate, "linked_pct": 0.0155, "usable": estimate, "usable_pct": 0.0155},
        },
        "readiness": {"production_ready_company_count": ready},
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


def test_refresh_report_marks_failed_stage():
    report = build_refresh_report(_summary(), _summary(), [{"name": "build", "returncode": 2}])
    assert report["status"] == "failed"
    assert report["schema_version"] == "production-refresh-report.v030.6.5"


def test_run_refresh_stops_after_failure_and_writes_report(tmp_path: Path):
    summary_dir = tmp_path / "data/generated/production_population"
    summary_dir.mkdir(parents=True)
    (summary_dir / "production_population_summary.json").write_text(__import__("json").dumps(_summary()), encoding="utf-8")
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
    ], output, runner=runner)
    assert report["status"] == "failed"
    assert len(calls) == 2
    assert output.exists()
