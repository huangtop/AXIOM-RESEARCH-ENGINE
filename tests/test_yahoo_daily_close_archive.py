from datetime import date, datetime, timezone
from decimal import Decimal
import json

from axiom_engine.previous_close import DailyClose, PreviousCloseError
from axiom_engine.providers.yahoo_daily_close import (
    YahooDailyCloseArchive, refresh_yahoo_daily_closes,
)


def close(symbol: str, day: date, value: str) -> DailyClose:
    return DailyClose(symbol=symbol, session_date=day, close=Decimal(value), currency="USD", exchange_timezone="America/New_York")


def test_archive_keeps_history_and_latest(tmp_path):
    archive = YahooDailyCloseArchive(tmp_path / "history", latest_cache_path=tmp_path / "latest.json", retention_days=365)
    archive.write([close("AAPL", date(2026, 7, 23), "210")], generated_at=datetime(2026, 7, 24, tzinfo=timezone.utc))
    report = archive.write([close("AAPL", date(2026, 7, 24), "212"), close("MSFT", date(2026, 7, 24), "500")], generated_at=datetime(2026, 7, 25, tzinfo=timezone.utc))
    assert [row.close for row in archive.history("AAPL")] == [Decimal("210"), Decimal("212")]
    assert report.latest_symbols == 2
    assert report.history_rows == 3
    latest = json.loads((tmp_path / "latest.json").read_text())
    assert latest == {"AAPL": [212, "2026-07-24"], "MSFT": [500, "2026-07-24"]}
    assert report.refresh_state_path.endswith("history_state.json")
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
    archive.write([close("OLD", date(2025, 7, 25), "1"), close("KEEP", date(2025, 7, 26), "2")], generated_at=datetime(2026, 7, 25, tzinfo=timezone.utc))
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


def test_same_run_date_cache_skips_before_provider_request(tmp_path):
    archive = YahooDailyCloseArchive(tmp_path / "history", retention_days=365)
    archive.write([close("AAPL", date(2026, 7, 24), "212")], generated_at=datetime(2026, 7, 25, tzinfo=timezone.utc))

    class MustNotFetch:
        def previous_close(self, symbol, *, as_of=None):
            raise AssertionError(symbol)

    report = refresh_yahoo_daily_closes(["AAPL"], fetcher=MustNotFetch(), archive=archive, as_of=datetime(2026, 7, 25, tzinfo=timezone.utc))
    assert report.skipped_existing == 1
    assert report.succeeded == 0


def test_refresh_checkpoints_successes_before_batch_completion(tmp_path):
    archive = YahooDailyCloseArchive(tmp_path / "history", retention_days=365)
    report = refresh_yahoo_daily_closes(["A", "B", "C"], fetcher=FakeFetcher(), archive=archive, as_of=datetime(2026, 7, 25, tzinfo=timezone.utc), checkpoint_size=2)
    assert report.succeeded == 3
    assert archive.latest("A") is not None
    assert archive.latest("C") is not None


def test_stale_fetched_today_is_never_skipped(tmp_path):
    archive = YahooDailyCloseArchive(tmp_path / "history")
    now = datetime(2026, 10, 14, 1, 30, tzinfo=timezone.utc)
    archive.write([close("AAPL", date(2026, 10, 12), "100")], generated_at=now)
    calls = []

    class Fetcher:
        def previous_close(self, symbol, *, as_of=None):
            calls.append(symbol)
            return close(symbol, date(2026, 10, 13), "101")

    report = refresh_yahoo_daily_closes(["AAPL"], fetcher=Fetcher(), archive=archive, as_of=now)
    assert calls == ["AAPL"]
    assert report.fresh == 1
    assert report.stale == 0
    assert archive.latest("AAPL").session_date == date(2026, 10, 13)


def test_stale_retries_only_stale_and_no_repeat_session_rewrites(tmp_path):
    archive = YahooDailyCloseArchive(tmp_path / "history")
    now = datetime(2026, 10, 14, 1, 30, tzinfo=timezone.utc)
    calls = []

    class Staggered:
        def previous_close(self, symbol, *, as_of=None):
            calls.append(symbol)
            day = date(2026, 10, 12) if symbol == "AAPL" and calls.count(symbol) == 1 else date(2026, 10, 13)
            return close(symbol, day, "100")

    report = refresh_yahoo_daily_closes(["AAPL", "SNDK"], fetcher=Staggered(), archive=archive, as_of=now, retry_stale=True)
    assert calls == ["AAPL", "SNDK", "AAPL"]
    assert report.retry_attempted == 1
    assert report.retry_recovered == 1
    assert report.target_coverage_rate == 1
    archive_path = tmp_path / "history" / "2026-10-13.json"
    before = archive_path.read_bytes()
    another = archive.write([close("SNDK", date(2026, 10, 13), "100")], generated_at=datetime(2026, 10, 14, 2, tzinfo=timezone.utc))
    assert another.session_files_written == 0
    assert archive_path.read_bytes() == before


def test_stale_is_not_counted_as_fresh_success(tmp_path):
    archive = YahooDailyCloseArchive(tmp_path / "history")
    now = datetime(2026, 10, 14, 1, 30, tzinfo=timezone.utc)

    class Stale:
        def previous_close(self, symbol, *, as_of=None):
            return close(symbol, date(2026, 10, 12), "100")

    report = refresh_yahoo_daily_closes(["AAPL"], fetcher=Stale(), archive=archive, as_of=now, retry_stale=True)
    assert report.fresh == 0
    assert report.stale == 1
    assert report.retry_attempted == 1
    assert report.target_coverage_rate == 0
