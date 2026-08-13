from datetime import date

from axiom_engine.history_retention import prune_dated_snapshots


def test_news_style_dated_history_retains_only_configured_window(tmp_path):
    root = tmp_path / "snapshots"
    for day in ("2026-01-01", "2026-03-02", "not-a-date"):
        (root / day).mkdir(parents=True)
    removed = prune_dated_snapshots(root, retention_days=30, as_of=date(2026, 3, 2))
    assert removed == ["2026-01-01"]
    assert (root / "2026-03-02").is_dir()
    assert (root / "not-a-date").is_dir()
