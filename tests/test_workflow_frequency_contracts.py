from pathlib import Path


ROOT = Path(__file__).parents[1]


def _workflow(name: str) -> str:
    return (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")


def test_ci_runs_validation_and_maintained_suites():
    workflow = _workflow("ci.yml")

    assert "axiom validate" in workflow
    assert "pytest -q" in workflow
    assert workflow.count("pytest -q") == 1
    assert '"--ignore-glob=tests/test_company_*.py"' in workflow

def test_generated_data_pushes_do_not_start_the_full_ci_suite():
    workflow = _workflow("ci.yml")
    assert 'paths-ignore:' in workflow
    assert '"data/generated/**"' in workflow


def test_market_refresh_publishes_the_daily_close_refresh_report():
    workflow = _workflow("production-market-refresh.yml")
    assert "--report data/generated/market/daily_close_refresh_report.json" in workflow
    assert "data/generated/market" in workflow
    assert "Synchronize main before the expensive provider refresh" in workflow
    assert "publish_daily_market_refresh.sh" in workflow
    publisher = (ROOT / "scripts/publish_daily_market_refresh.sh").read_text(encoding="utf-8")
    assert "git pull --rebase" not in publisher
    assert "git reset --hard origin/main" in publisher
    assert "for attempt in 1 2 3" in publisher
    assert "restore_market_inputs" in publisher


def test_estimates_refresh_daily_in_batches_of_200():
    workflow = _workflow("yahoo-estimates-refresh.yml")
    assert 'cron: "30 11 * * *"' in workflow
    assert "build_daily_estimate_worklist.py" in workflow
    assert "--max-fetch 200" in workflow
    assert "inputs.force && '--force'" in workflow


def test_sec_filing_planner_caps_daily_worklist_at_200():
    workflow = _workflow("sec-filing-events.yml")
    assert "--max-companies 200" in workflow


def test_sec_financial_refresh_never_runs_classification_or_business_evidence():
    workflow = _workflow("sec-financial-refresh.yml")
    assert 'workflows: ["Daily SEC Filing Event Planner"]' in workflow
    assert "build_sec_business_evidence.py" not in workflow
    assert "build_company_signals.py" not in workflow
    assert "canonical_business_evidence" not in workflow
    assert "classification_quality" not in workflow


def test_daily_market_and_etf_schedules_remain_weekday_only():
    market = _workflow("production-market-refresh.yml")
    etf = _workflow("etf-holdings-refresh.yml")
    assert 'cron: "20 22 * * 1-5"' in market
    assert 'cron: "45 23 * * 1-5"' in etf
