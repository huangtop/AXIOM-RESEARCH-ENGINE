from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_daily_market_refresh_is_recoverable_before_full_market_fetch():
    workflow = (ROOT / ".github/workflows/production-market-refresh.yml").read_text()
    assert "preflight:" in workflow
    assert "Prove tracked ignored archives can be staged" in workflow
    assert "git check-ignore --no-index" in workflow
    assert "--symbols NVDA GOOGL" in workflow
    assert workflow.index("Smoke test NVDA and GOOGL") < workflow.index("Refresh all eligible operating-company closes")
    assert "git diff --cached --binary --full-index" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "retention-days: 7" in workflow
    assert "actions/download-artifact@v4" in workflow
    assert "git apply --3way --index" in workflow
    assert "Verify committed NVDA and GOOGL session dates" in workflow


def test_publish_retry_reuses_artifact_without_refetching_yahoo():
    workflow = (ROOT / ".github/workflows/production-market-publish-retry.yml").read_text()
    assert "source_run_id:" in workflow
    assert "actions/download-artifact@v4" in workflow
    assert "run-id: ${{ inputs.source_run_id }}" in workflow
    assert "git apply --3way --index" in workflow
    assert "refresh_yahoo_daily_close.py" not in workflow
