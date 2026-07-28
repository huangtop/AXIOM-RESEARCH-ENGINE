from datetime import date, datetime, timezone
from decimal import Decimal

from axiom_engine.previous_close import DailyClose, PreviousCloseError
from axiom_engine.providers.yahoo_daily_close import YahooDailyCloseArchive, refresh_yahoo_daily_closes


def close(symbol: str, day: date, value: str) -> DailyClose:
    return DailyClose(symbol=symbol, session_date=day, close=Decimal(value), currency="USD", exchange_timezone="America/New_York")


def test_archive_keeps_history_and_latest(tmp_path):
    archive = YahooDailyCloseArchive(tmp_path / "history", latest_cache_path=tmp_path / "latest.json", retention_days=365)
    archive.write([close("AAPL", date(2026, 7, 23), "210")], generated_at=datetime(2026, 7, 24, tzinfo=timezone.utc))
    report = archive.write([close("AAPL", date(2026, 7, 24), "212"), close("MSFT", date(2026, 7, 24), "500")], generated_at=datetime(2026, 7, 25, tzinfo=timezone.utc))
    assert [row.close for row in archive.history("AAPL")] == [Decimal("210"), Decimal("212")]
    assert report.latest_symbols == 2
    assert report.history_rows == 3
    assert (tmp_path / "history" / "2026-07-23.json").exists()
    assert (tmp_path / "history" / "2026-07-24.json").exists()


def test_archive_is_idempotent_per_symbol_and_session(tmp_path):
    archive = YahooDailyCloseArchive(tmp_path / "history", retention_days=365)
    now = datetime(2026, 7, 25, tzinfo=timezone.utc)
    archive.write([close("AAPL", date(2026, 7, 24), "212")], generated_at=now)
    report = archive.write([close("AAPL", date(2026, 7, 24), "213")], generated_at=now)
    assert report.history_rows == 1
    assert archive.history("AAPL")[0].close == Decimal("213")


def test_prune_keeps_exact_retention_window(tmp_path):
    archive = YahooDailyCloseArchive(tmp_path / "history", retention_days=365)
    archive.write(
        [close("OLD", date(2025, 7, 25), "1"), close("KEEP", date(2025, 7, 26), "2")],
        generated_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )
    assert not (tmp_path / "history" / "2025-07-25.json").exists()
    assert (tmp_path / "history" / "2025-07-26.json").exists()


class FakeFetcher:
    def previous_close(self, symbol, *, as_of=None):
        if symbol == "BAD":
            raise PreviousCloseError("missing")
        return close(symbol, date(2026, 7, 24), "100")


def test_refresh_continues_after_symbol_failure_and_resumes(tmp_path):
    archive = YahooDailyCloseArchive(tmp_path / "history", retention_days=365)
    first = refresh_yahoo_daily_closes(["AAPL", "BAD", "MSFT"], fetcher=FakeFetcher(), archive=archive, as_of=datetime(2026, 7, 25, tzinfo=timezone.utc))
    assert first.succeeded == 2
    assert first.failed == 1
    second = refresh_yahoo_daily_closes(["AAPL", "MSFT"], fetcher=FakeFetcher(), archive=archive, as_of=datetime(2026, 7, 25, tzinfo=timezone.utc))
    assert second.succeeded == 0
    assert second.skipped_existing == 2
    assert second.archive.history_rows == 2


def test_recent_latest_cache_skips_before_provider_request(tmp_path):
    archive = YahooDailyCloseArchive(tmp_path / "history", retention_days=365)
    archive.write(
        [close("AAPL", date(2026, 7, 24), "212")],
        generated_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )

    class MustNotFetch:
        def previous_close(self, symbol, *, as_of=None):
            raise AssertionError(symbol)

    report = refresh_yahoo_daily_closes(
        ["AAPL"],
        fetcher=MustNotFetch(),
        archive=archive,
        as_of=datetime(2026, 7, 28, tzinfo=timezone.utc),
    )
    assert report.skipped_existing == 1
    assert report.succeeded == 0


def test_refresh_checkpoints_successes_before_batch_completion(tmp_path):
    archive = YahooDailyCloseArchive(tmp_path / "history", retention_days=365)
    report = refresh_yahoo_daily_closes(
        ["A", "B", "C"],
        fetcher=FakeFetcher(),
        archive=archive,
        as_of=datetime(2026, 7, 25, tzinfo=timezone.utc),
        checkpoint_size=2,
    )
    assert report.succeeded == 3
    assert archive.latest("A") is not None
    assert archive.latest("C") is not None
