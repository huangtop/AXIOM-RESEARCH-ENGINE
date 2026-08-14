from pathlib import Path


ROOT = Path(__file__).parents[1]


def _workflow(name: str) -> str:
    return (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")


def test_classification_refreshes_daily_in_batches_of_300():
    workflow = _workflow("research-classification-refresh.yml")
    assert "workflow_dispatch:" in workflow
    assert 'cron: "30 8 * * *"' in workflow
    assert "--limit 300" in workflow
    assert workflow.index("Smoke-test workflow and publication contracts") < workflow.index(
        "Extend SEC business evidence checkpoint"
    )


def test_ci_smoke_gate_runs_before_full_suite():
    workflow = _workflow("ci.yml")
    assert (
        "tests/test_full_market_coverage_v031.py::"
        "test_ai_research_companies_have_a_calculated_valuation_model"
    ) in workflow
    assert workflow.index("Smoke-test workflow and publication contracts") < workflow.index(
        "- run: pytest -q\n"
    )


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
