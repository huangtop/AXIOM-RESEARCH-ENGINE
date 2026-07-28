from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable, Mapping, Protocol

from axiom_engine.previous_close import DailyClose, PreviousCloseError


class PreviousCloseFetcher(Protocol):
    def previous_close(self, symbol: str, *, as_of: datetime | None = None) -> DailyClose: ...


@dataclass(frozen=True, slots=True)
class ArchiveWriteReport:
    archive_root: str
    latest_cache_path: str
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

    @property
    def success_rate(self) -> float:
        return 1.0 if self.requested == 0 else (self.succeeded + self.skipped_existing) / self.requested

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["success_rate"] = round(self.success_rate, 6)
        return payload


class YahooDailyCloseArchive:
    """Durable one-year archive for completed daily closes.

    Storage is partitioned by market session date so a 6,000+ symbol refresh
    creates one bounded file per trading day, not one file per symbol. Writes
    are idempotent: rerunning a session merges/replaces rows by symbol.
    """

    def __init__(
        self,
        archive_root: Path,
        *,
        latest_cache_path: Path | None = None,
        retention_days: int = 365,
    ) -> None:
        if retention_days < 1:
            raise ValueError("retention_days must be positive")
        self.archive_root = Path(archive_root)
        self.latest_cache_path = Path(latest_cache_path) if latest_cache_path else self.archive_root / "latest.json"
        self.retention_days = retention_days

    def write(
        self,
        closes: Iterable[DailyClose],
        *,
        generated_at: datetime | None = None,
    ) -> ArchiveWriteReport:
        now = generated_at or datetime.now(tz=timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        rows = list(closes)
        grouped: dict[date, dict[str, DailyClose]] = {}
        for close in rows:
            grouped.setdefault(close.session_date, {})[close.symbol] = close

        self.archive_root.mkdir(parents=True, exist_ok=True)
        for session_date, session_rows in grouped.items():
            path = self._session_path(session_date)
            existing = self._read_session(path)
            existing.update({symbol: close.to_dict() for symbol, close in session_rows.items()})
            self._atomic_json_write(
                path,
                {
                    "schema_version": "1.0",
                    "provider": "yahoo_finance",
                    "session_date": session_date.isoformat(),
                    "generated_at": now.isoformat(),
                    "symbols": dict(sorted(existing.items())),
                },
            )

        latest = self._read_latest_rows()
        for close in rows:
            previous = latest.get(close.symbol)
            previous_date = str(previous.get("session_date")) if isinstance(previous, Mapping) else ""
            if not previous_date or close.session_date.isoformat() >= previous_date:
                latest[close.symbol] = close.to_dict()
        self._atomic_json_write(
            self.latest_cache_path,
            {
                "schema_version": "1.0",
                "generated_at": now.isoformat(),
                "retention_days": self.retention_days,
                "symbols": dict(sorted(latest.items())),
            },
        )

        pruned = self.prune(reference_date=now.date())
        return ArchiveWriteReport(
            archive_root=str(self.archive_root),
            latest_cache_path=str(self.latest_cache_path),
            rows_received=len(rows),
            session_files_written=len(grouped),
            latest_symbols=len(latest),
            history_rows=self.count_history_rows(),
            pruned_session_files=pruned,
            retention_days=self.retention_days,
        )

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
        item = self._read_latest_rows().get(normalized)
        return _daily_close_from_dict(normalized, item) if isinstance(item, Mapping) else None

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

    def _read_latest_rows(self) -> dict[str, dict[str, object]]:
        try:
            payload = json.loads(self.latest_cache_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        symbols = payload.get("symbols") if isinstance(payload, Mapping) else None
        return dict(symbols) if isinstance(symbols, Mapping) else {}

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


def refresh_yahoo_daily_closes(
    symbols: Iterable[str],
    *,
    fetcher: PreviousCloseFetcher,
    archive: YahooDailyCloseArchive,
    as_of: datetime | None = None,
    request_delay_seconds: float = 0.0,
    skip_existing: bool = True,
    checkpoint_size: int = 25,
    sleep: Callable[[float], None] = time.sleep,
) -> YahooDailyCloseRefreshReport:
    if request_delay_seconds < 0:
        raise ValueError("request_delay_seconds cannot be negative")
    if checkpoint_size < 1:
        raise ValueError("checkpoint_size must be positive")
    normalized = _normalize_symbols(symbols)
    successes: list[DailyClose] = []
    failures: dict[str, str] = {}
    skipped = 0
    requested = 0
    succeeded = 0
    write_report: ArchiveWriteReport | None = None

    for index, symbol in enumerate(normalized):
        requested += 1
        cached = archive.latest(symbol) if skip_existing else None
        cutoff_date = (as_of or datetime.now(tz=timezone.utc)).date()
        if cached and 0 <= (cutoff_date - cached.session_date).days <= 7:
            skipped += 1
            continue
        try:
            close = fetcher.previous_close(symbol, as_of=as_of)
            if skip_existing and archive.has(symbol, close.session_date):
                skipped += 1
            else:
                successes.append(close)
        except (PreviousCloseError, ValueError, OSError) as exc:
            failures[symbol] = f"{type(exc).__name__}: {exc}"
        if (index + 1) % checkpoint_size == 0:
            write_report = archive.write(
                successes, generated_at=as_of or datetime.now(tz=timezone.utc)
            )
            succeeded += len(successes)
            successes.clear()
        if request_delay_seconds and index < len(normalized) - 1:
            sleep(request_delay_seconds)

    write_report = archive.write(successes, generated_at=as_of or datetime.now(tz=timezone.utc))
    succeeded += len(successes)
    return YahooDailyCloseRefreshReport(
        requested=requested,
        succeeded=succeeded,
        failed=len(failures),
        skipped_existing=skipped,
        failures=failures,
        archive=write_report,
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
        symbol=symbol,
        session_date=date.fromisoformat(str(item["session_date"])),
        close=Decimal(str(item["close"])),
        currency=str(item["currency"]) if item.get("currency") else None,
        exchange_timezone=str(item["exchange_timezone"]) if item.get("exchange_timezone") else None,
        provider=str(item.get("provider") or "yahoo_finance"),
    )
