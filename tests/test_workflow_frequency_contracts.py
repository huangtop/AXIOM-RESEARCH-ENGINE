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


def test_generated_data_pushes_do_not_start_the_full_ci_suite():
    workflow = _workflow("ci.yml")
    assert 'paths-ignore:' in workflow
    assert '"data/generated/**"' in workflow


def test_business_evidence_is_checkpointed_before_classification_rebuild():
    workflow = _workflow("research-classification-refresh.yml")
    evidence = workflow.index("Extend SEC business evidence checkpoint")
    checkpoint = workflow.index("Validate and publish SEC business evidence checkpoint")
    rebuild = workflow.index("Rebuild evidence-derived classifications and action gates")
    validation = workflow.index("Validate classification and publication contracts")
    assert evidence < checkpoint < rebuild < validation
    checkpoint_block = workflow[checkpoint:rebuild]
    assert "tests/test_sec_business_evidence_v031_2b.py" in checkpoint_block
    assert "git add data/generated/canonical_business_evidence" in checkpoint_block
    derived_block = workflow[workflow.index("Commit derived research artifacts"):]
    assert "git add data/generated/canonical_business_evidence" not in derived_block
    assert "--delay 0.20" in workflow


def test_market_refresh_publishes_the_daily_close_refresh_report():
    workflow = _workflow("production-market-refresh.yml")
    assert "--report data/generated/market/daily_close_refresh_report.json" in workflow
    assert "data/generated/market" in workflow


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
