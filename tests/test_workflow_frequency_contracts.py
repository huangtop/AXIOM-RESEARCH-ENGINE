from pathlib import Path


ROOT = Path(__file__).parents[1]


def _workflow(name: str) -> str:
    return (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")


def test_classification_is_manual_only():
    workflow = _workflow("research-classification-refresh.yml")
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "cron:" not in workflow


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
