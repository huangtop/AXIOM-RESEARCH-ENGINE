from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_daily_etf_workflow_preserves_history_and_scopes_commit():
    workflow = (ROOT / ".github/workflows/etf-holdings-refresh.yml").read_text()
    assert 'cron: "45 23 * * 1-5"' in workflow
    assert "sync_etf_engine_cache.py --allow-live --force" in workflow
    assert "build_etf_holdings_history.py" in workflow
    assert "canonical_etf_holdings_history" in workflow
    assert "canonical_etf_change_events" in workflow
    assert "event_triggers/etf_changes.json" in workflow
    assert "news_pipeline" not in workflow
    history = (ROOT / "src/axiom_engine/etf_holdings_history/core.py").read_text()
    assert 'get("research_scope") != "core"' in history
