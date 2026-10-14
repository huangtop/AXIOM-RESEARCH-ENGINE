from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable, Mapping, Protocol
from zoneinfo import ZoneInfo

from axiom_engine.market_price_cache import compact_market_row, market_rows, unpack_market_row
from axiom_engine.previous_close import DailyClose, PreviousCloseError


class PreviousCloseFetcher(Protocol):
    def previous_close(self, symbol: str, *, as_of: datetime | None = None) -> DailyClose: ...


@dataclass(frozen=True, slots=True)
class ArchiveWriteReport:
    archive_root: str
    latest_cache_path: str
    refresh_state_path: str
    rows_received: int
    session_files_written: int
    latest_symbols: int
    history_rows: int
    pruned_session_files: int
    retention_days: int


@dataclass(frozen=True, slots=True)
class YahooDailyCloseRefreshReport:
    requested: int
    succeeded: int
    failed: int
    skipped_existing: int
    failures: dict[str, str]
    archive: ArchiveWriteReport
    fresh: int = 0
    stale: int = 0
    stale_symbols: tuple[str, ...] = ()
    retry_attempted: int = 0
    retry_recovered: int = 0
    target_session_date: str | None = None
    provider_attempted: int = 0
    provider_succeeded: int = 0

    @property
    def success_rate(self) -> float:
        return 1.0 if self.requested == 0 else (self.succeeded + self.skipped_existing) / self.requested

    @property
    def target_coverage_rate(self) -> float:
        return 1.0 if self.requested == 0 else self.fresh / self.requested

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["success_rate"] = round(self.success_rate, 6)
        payload["target_coverage_rate"] = round(self.target_coverage_rate, 6)
        payload["stale_symbol_count"] = len(self.stale_symbols)
        # Do not publish a 4,000-ticker stale list in Git every day.
        payload["stale_symbols"] = list(self.stale_symbols[:40])
        return payload


def expected_us_session(as_of: datetime) -> date:
    """Most recent completed regular US equity trading session.

    Handles standard NYSE holidays; ad-hoc closures are not predictable.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    eastern = as_of.astimezone(ZoneInfo("America/New_York"))
    day = eastern.date()
    if eastern.hour < 17:
        day -= timedelta(days=1)
    while day.weekday() >= 5 or _us_equity_holiday(day):
        day -= timedelta(days=1)
    return day


def _us_equity_holiday(day: date) -> bool:
    """Regular NYSE full-day closures; not unscheduled market emergencies."""
    def observed(month: int, number: int, year: int) -> date:
        raw = date(year, month, number)
        return raw - timedelta(days=1) if raw.weekday() == 5 else (raw + timedelta(days=1) if raw.weekday() == 6 else raw)

    def nth_monday(month: int, nth: int) -> date:
        first = date(day.year, month, 1)
        return first + timedelta(days=(7 - first.weekday()) % 7 + 7 * (nth - 1))

    def last_monday(month: int) -> date:
        nxt = date(day.year + (month == 12), month % 12 + 1, 1)
        end = nxt - timedelta(days=1)
        return end - timedelta(days=end.weekday())

    # Meeus/Jones/Butcher Gregorian computus, then Friday before Easter.
    y = day.year
    a = y % 19
    b = y // 100
    c = y % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    easter_day = (h + l - 7 * m + 114) % 31 + 1
    good_friday = date(y, month, easter_day) - timedelta(days=2)
    thanksgiving = nth_monday(11, 4) + timedelta(days=3)
    holidays = {
        observed(1, 1, y), observed(1, 1, y + 1),
        nth_monday(1, 3), nth_monday(2, 3),
        good_friday, last_monday(5), observed(6, 19, y),
        observed(7, 4, y), nth_monday(9, 1),
        thanksgiving, observed(12, 25, y),
    }
    return day in holidays


class YahooDailyCloseArchive:
    """One-year, per-session archive with semantic no-op writes."""

    def __init__(
        self, archive_root: Path, *, latest_cache_path: Path | None = None,
        refresh_state_path: Path | None = None, retention_days: int = 365,
    ) -> None:
        if retention_days < 1:
            raise ValueError("retention_days must be positive")
        self.archive_root = Path(archive_root)
        self.latest_cache_path = Path(latest_cache_path) if latest_cache_path else self.archive_root / "latest.json"
        self.refresh_state_path = Path(refresh_state_path) if refresh_state_path else self.archive_root.parent / f"{self.archive_root.name}_state.json"
        self.retention_days = retention_days

    def write(self, closes: Iterable[DailyClose], *, generated_at: datetime | None = None) -> ArchiveWriteReport:
        now = generated_at or datetime.now(tz=timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        rows = list(closes)
        grouped: dict[date, dict[str, DailyClose]] = {}
        for close in rows:
            grouped.setdefault(close.session_date, {})[close.symbol] = close

        self.archive_root.mkdir(parents=True, exist_ok=True)
        written = 0
        for session_date, session_rows in grouped.items():
            path = self._session_path(session_date)
            existing = self._read_session(path)
            merged = dict(existing)
            merged.update({symbol: close.to_dict() for symbol, close in session_rows.items()})
            if merged != existing or not path.exists():
                self._atomic_json_write(path, {
                    "schema_version": "1.0", "provider": "yahoo_finance",
                    "session_date": session_date.isoformat(),
                    "generated_at": now.isoformat(),
                    "symbols": dict(sorted(merged.items())),
                })
                written += 1

        latest = self._read_latest_rows()
        updated = dict(latest)
        refresh_state = self._read_refresh_state()
        for close in rows:
            previous = unpack_market_row(updated.get(close.symbol))
            previous_date = str(previous.get("session_date") or "")
            if not previous_date or close.session_date.isoformat() >= previous_date:
                updated[close.symbol] = compact_market_row(close.close, close.session_date)
            # Never mark an old close as a successful session refresh.
            if close.session_date >= expected_us_session(now):
                refresh_state[close.symbol] = now.isoformat()
        if updated != latest or not self.latest_cache_path.exists():
            self._atomic_compact_json_write(self.latest_cache_path, dict(sorted(updated.items())))
        if rows or not self.refresh_state_path.exists():
            self._write_refresh_state_if_changed(refresh_state)

        pruned = self.prune(reference_date=now.date())
        return ArchiveWriteReport(
            archive_root=str(self.archive_root), latest_cache_path=str(self.latest_cache_path),
            refresh_state_path=str(self.refresh_state_path), rows_received=len(rows),
            session_files_written=written, latest_symbols=len(updated),
            history_rows=self.count_history_rows(), pruned_session_files=pruned,
            retention_days=self.retention_days,
        )

    def _write_refresh_state_if_changed(self, state: Mapping[str, str]) -> None:
        # Save only session-level success markers. Re-running within the same
        # UTC date must not create new commit churn for the same fresh close.
        existing = self._read_refresh_state()
        normalized = dict(sorted({symbol: timestamp[:10] for symbol, timestamp in state.items()}.items()))
        previous = {symbol: timestamp[:10] for symbol, timestamp in existing.items()}
        if normalized != previous or not self.refresh_state_path.exists():
            self._atomic_compact_json_write(self.refresh_state_path, {
                "schema_version": "yahoo-daily-close-refresh-state.v1", "symbols": normalized,
            })

    def history(self, symbol: str, *, limit_days: int | None = None) -> list[DailyClose]:
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("symbol cannot be empty")
        cutoff = None
        if limit_days is not None:
            if limit_days < 1:
                raise ValueError("limit_days must be positive")
            cutoff = date.today() - timedelta(days=limit_days - 1)
        result: list[DailyClose] = []
        for path in sorted(self.archive_root.glob("*.json")):
            if path.resolve() == self.latest_cache_path.resolve():
                continue
            session_date = _date_from_filename(path)
            if session_date is None or (cutoff is not None and session_date < cutoff):
                continue
            item = self._read_session(path).get(normalized)
            if isinstance(item, Mapping):
                result.append(_daily_close_from_dict(normalized, item))
        return sorted(result, key=lambda row: row.session_date)

    def has(self, symbol: str, session_date: date) -> bool:
        return symbol.strip().upper() in self._read_session(self._session_path(session_date))

    def latest(self, symbol: str) -> DailyClose | None:
        normalized = symbol.strip().upper()
        row = unpack_market_row(self._read_latest_rows().get(normalized))
        if row.get("close") in (None, "") or not row.get("session_date"):
            return None
        return DailyClose(
            symbol=normalized, session_date=date.fromisoformat(str(row["session_date"])),
            close=Decimal(str(row["close"])), currency=str(row["currency"]) if row.get("currency") else None,
            exchange_timezone=None, provider=str(row.get("provider") or "yahoo_finance"),
        )

    def was_fetched_on(self, symbol: str, fetch_date: date) -> bool:
        fetched_at = self._read_refresh_state().get(symbol.strip().upper())
        if not fetched_at:
            return False
        try:
            return date.fromisoformat(str(fetched_at)[:10]) == fetch_date
        except ValueError:
            return False

    def prune(self, *, reference_date: date | None = None) -> int:
        reference = reference_date or date.today()
        cutoff = reference - timedelta(days=self.retention_days - 1)
        removed = 0
        for path in self.archive_root.glob("*.json"):
            if path.resolve() == self.latest_cache_path.resolve():
                continue
            session_date = _date_from_filename(path)
            if session_date is not None and session_date < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        return removed

    def count_history_rows(self) -> int:
        total = 0
        for path in self.archive_root.glob("*.json"):
            if path.resolve() == self.latest_cache_path.resolve():
                continue
            total += len(self._read_session(path))
        return total

    def _session_path(self, session_date: date) -> Path:
        return self.archive_root / f"{session_date.isoformat()}.json"

    def _read_latest_rows(self) -> dict[str, object]:
        try:
            payload = json.loads(self.latest_cache_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return dict(market_rows(payload))

    def _read_refresh_state(self) -> dict[str, str]:
        try:
            payload = json.loads(self.refresh_state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            payload = {}
        symbols = payload.get("symbols") if isinstance(payload, Mapping) else None
        if isinstance(symbols, Mapping):
            return {str(k).upper(): str(v) for k, v in symbols.items() if v}
        try:
            legacy = json.loads(self.latest_cache_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        legacy_rows = legacy.get("symbols") if isinstance(legacy, Mapping) else None
        if not isinstance(legacy_rows, Mapping):
            return {}
        out = {}
        for symbol, row in legacy_rows.items():
            fetched = unpack_market_row(row).get("fetched_at")
            if fetched:
                out[str(symbol).upper()] = str(fetched)
        return out

    @staticmethod
    def _read_session(path: Path) -> dict[str, dict[str, object]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        symbols = payload.get("symbols") if isinstance(payload, Mapping) else None
        return dict(symbols) if isinstance(symbols, Mapping) else {}

    @staticmethod
    def _atomic_json_write(path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _atomic_compact_json_write(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)


def refresh_yahoo_daily_closes(
    symbols: Iterable[str], *, fetcher: PreviousCloseFetcher, archive: YahooDailyCloseArchive,
    as_of: datetime | None = None, request_delay_seconds: float = 0.0,
    skip_existing: bool = True, checkpoint_size: int = 25,
    sleep: Callable[[float], None] = time.sleep,
    retry_stale: bool = False,
) -> YahooDailyCloseRefreshReport:
    if request_delay_seconds < 0:
        raise ValueError("request_delay_seconds cannot be negative")
    if checkpoint_size < 1:
        raise ValueError("checkpoint_size must be positive")
    normalized = _normalize_symbols(symbols)
    now = as_of or datetime.now(tz=timezone.utc)
    target = expected_us_session(now)
    successes: list[DailyClose] = []
    failures: dict[str, str] = {}
    requested, succeeded, skipped = 0, 0, 0
    retry_attempted, retry_recovered = 0, 0
    provider_attempted, provider_succeeded = 0, 0
    write_report: ArchiveWriteReport | None = None
    observed: dict[str, date] = {}

    def checkpoint() -> None:
        nonlocal succeeded, write_report
        if successes:
            write_report = archive.write(successes, generated_at=now)
            succeeded += len(successes)
            successes.clear()

    for index, symbol in enumerate(normalized):
        requested += 1
        prior = archive.latest(symbol)
        if skip_existing and prior and prior.session_date >= target:
            skipped += 1
            observed[symbol] = prior.session_date
            continue
        try:
            provider_attempted += 1
            close = fetcher.previous_close(symbol, as_of=now)
            provider_succeeded += 1
            observed[symbol] = close.session_date
            if prior is None or close.session_date > prior.session_date or (close.session_date == prior.session_date and close.close != prior.close):
                successes.append(close)
            elif prior is not None and close.session_date < prior.session_date:
                observed[symbol] = prior.session_date
        except (PreviousCloseError, ValueError, OSError) as exc:
            failures[symbol] = f"{type(exc).__name__}: {exc}"
            if prior:
                observed[symbol] = prior.session_date
        if (index + 1) % checkpoint_size == 0:
            checkpoint()
        if request_delay_seconds and index < len(normalized) - 1:
            sleep(request_delay_seconds)
    checkpoint()

    if retry_stale:
        # At most ONE additional targeted retry; never refetch fresh symbols.
        stale = [s for s in normalized if observed.get(s, date.min) < target]
        for i, symbol in enumerate(stale):
            retry_attempted += 1
            provider_attempted += 1
            try:
                close = fetcher.previous_close(symbol, as_of=now)
                provider_succeeded += 1
                prior = archive.latest(symbol)
                if prior is None or close.session_date > prior.session_date or (close.session_date == prior.session_date and close.close != prior.close):
                    successes.append(close)
                observed[symbol] = max(close.session_date, observed.get(symbol, date.min))
                if observed[symbol] >= target:
                    retry_recovered += 1
                    failures.pop(symbol, None)
            except (PreviousCloseError, ValueError, OSError) as exc:
                failures[symbol] = f"{type(exc).__name__}: {exc}"
            if (i + 1) % checkpoint_size == 0:
                checkpoint()
            if request_delay_seconds and i < len(stale) - 1:
                sleep(request_delay_seconds)
        checkpoint()

    if write_report is None:
        write_report = archive.write([], generated_at=now)
    stale_symbols = tuple(s for s in normalized if observed.get(s, date.min) < target)
    fresh = requested - len(stale_symbols)
    return YahooDailyCloseRefreshReport(
        requested=requested, succeeded=succeeded, failed=len(failures),
        skipped_existing=skipped, failures=failures, archive=write_report,
        fresh=fresh, stale=len(stale_symbols), stale_symbols=stale_symbols,
        retry_attempted=retry_attempted, retry_recovered=retry_recovered,
        target_session_date=target.isoformat(),
        provider_attempted=provider_attempted, provider_succeeded=provider_succeeded,
    )


def _normalize_symbols(symbols: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        symbol = str(raw).strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            result.append(symbol)
    return result


def _date_from_filename(path: Path) -> date | None:
    try:
        return date.fromisoformat(path.stem)
    except ValueError:
        return None


def _daily_close_from_dict(symbol: str, item: Mapping[str, object]) -> DailyClose:
    return DailyClose(
        symbol=symbol, session_date=date.fromisoformat(str(item["session_date"])),
        close=Decimal(str(item["close"])),
        currency=str(item["currency"]) if item.get("currency") else None,
        exchange_timezone=str(item["exchange_timezone"]) if item.get("exchange_timezone") else None,
        provider=str(item.get("provider") or "yahoo_finance"),
    )
