#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from axiom_engine.previous_close import YahooPreviousCloseAdapter
from axiom_engine.providers.yahoo_daily_close import YahooDailyCloseArchive, refresh_yahoo_daily_closes


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh Yahoo completed daily closes and retain one year of history.")
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--symbols-file", type=Path)
    parser.add_argument("--universe-root", type=Path, help="Load one primary active security per company.")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--archive-root", type=Path, default=Path("data/generated/provider_cache/yahoo/daily_close"))
    parser.add_argument("--latest-cache", type=Path, default=Path("data/generated/market/previous_close_cache.json"))
    parser.add_argument("--retention-days", type=int, default=365)
    parser.add_argument("--delay", type=float, default=0.25, help="Delay between symbols in seconds.")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--force", action="store_true", help="Refetch/write rows already present for the session.")
    parser.add_argument("--report", type=Path, default=Path("data/generated/provider_cache/yahoo/daily_close_refresh_report.json"))
    args = parser.parse_args()

    symbols = list(args.symbols)
    if args.symbols_file:
        symbols.extend(load_symbols(args.symbols_file))
    if args.universe_root:
        symbols.extend(load_primary_symbols(args.universe_root))
    symbols = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    if not symbols:
        parser.error("provide --symbols, --symbols-file, or --universe-root")
    if args.offset < 0:
        parser.error("--offset cannot be negative")
    symbols = symbols[args.offset:]
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        symbols = symbols[: args.limit]

    archive = YahooDailyCloseArchive(
        args.archive_root,
        latest_cache_path=args.latest_cache,
        retention_days=args.retention_days,
    )
    report = refresh_yahoo_daily_closes(
        symbols,
        fetcher=YahooPreviousCloseAdapter(timeout_seconds=args.timeout),
        archive=archive,
        as_of=datetime.now(tz=timezone.utc),
        request_delay_seconds=args.delay,
        skip_existing=not args.force,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Requested: {report.requested}")
    print(f"Succeeded: {report.succeeded}")
    print(f"Skipped existing: {report.skipped_existing}")
    print(f"Failed: {report.failed}")
    print(f"Success rate: {report.success_rate * 100:.1f}%")
    print(f"Latest symbols: {report.archive.latest_symbols}")
    print(f"History rows: {report.archive.history_rows}")
    print(f"Retention days: {report.archive.retention_days}")
    print(f"Archive: {report.archive.archive_root}")
    print(f"Latest cache: {report.archive.latest_cache_path}")
    print(f"Report: {args.report}")
    return 0 if report.failed == 0 else 2


def load_symbols(path: Path) -> Iterable[str]:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".list"}:
        return [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        return [_symbol_from_mapping(row) for row in rows if _symbol_from_mapping(row)]
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return _symbols_from_json(payload)


def load_primary_symbols(universe_root: Path) -> list[str]:
    companies = json.loads((universe_root / "companies.json").read_text(encoding="utf-8"))
    securities = json.loads((universe_root / "securities.json").read_text(encoding="utf-8"))
    if not isinstance(companies, list) or not isinstance(securities, list):
        raise ValueError("universe companies and securities must be arrays")
    by_id = {str(row.get("security_id")): row for row in securities if isinstance(row, Mapping)}
    normalization_path = universe_root.parent / "generated/security_identity/security_identity_normalization.json"
    eligible_security_ids: set[str] | None = None
    included_company_ids: set[str] | None = None
    if normalization_path.is_file():
        normalization = json.loads(normalization_path.read_text(encoding="utf-8"))
        eligible_security_ids = {str(row.get("security_id")) for row in normalization.get("securities", []) if row.get("valuation_eligible") is True}
        included_company_ids = {str(row.get("company_id")) for row in normalization.get("companies", []) if row.get("valuation_scope_status") == "included"}
    by_company: dict[str, list[Mapping[str, object]]] = {}
    for row in securities:
        if isinstance(row, Mapping) and row.get("status") in (None, "active"):
            by_company.setdefault(str(row.get("company_id") or ""), []).append(row)
    output: list[str] = []
    for company in companies:
        if not isinstance(company, Mapping):
            continue
        if included_company_ids is not None and str(company.get("company_id")) not in included_company_ids:
            continue
        primary = by_id.get(str(company.get("primary_security_id") or ""))
        if primary and eligible_security_ids is not None and str(primary.get("security_id")) not in eligible_security_ids:
            primary = None
        if not primary:
            primary = next(
                (row for row in by_company.get(str(company.get("company_id") or ""), []) if row.get("primary_listing") is True and (eligible_security_ids is None or str(row.get("security_id")) in eligible_security_ids)),
                None,
            )
        if not primary:
            primary = next(
                (
                    row
                    for row in by_company.get(str(company.get("company_id") or ""), [])
                    if eligible_security_ids is None
                    or str(row.get("security_id")) in eligible_security_ids
                ),
                None,
            )
        symbol = str((primary or {}).get("ticker") or "").strip().upper()
        if symbol:
            output.append(symbol)
    return sorted(set(output))


def _symbols_from_json(payload: object) -> list[str]:
    if isinstance(payload, list):
        result = []
        for item in payload:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, Mapping):
                symbol = _symbol_from_mapping(item)
                if symbol:
                    result.append(symbol)
        return result
    if isinstance(payload, Mapping):
        for key in ("symbols", "securities", "companies", "universe", "rows", "items"):
            if key in payload:
                value = payload[key]
                if key == "symbols" and isinstance(value, Mapping):
                    return list(value.keys())
                return _symbols_from_json(value)
    return []


def _symbol_from_mapping(item: Mapping[str, object]) -> str:
    for key in ("symbol", "ticker", "display_symbol", "primary_symbol"):
        value = item.get(key)
        if value:
            return str(value).strip()
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
