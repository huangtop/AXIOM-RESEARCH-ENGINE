#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from axiom_engine.providers.yahoo_company_snapshot import (
    YFinanceCompanyInfoFetcher,
    YahooCompanySnapshotCache,
    refresh_yahoo_company_snapshots,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh cache-first Yahoo company and valuation snapshots.")
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--symbols-file", type=Path)
    parser.add_argument("--cache-root", type=Path, default=Path("data/generated/provider_cache/yahoo/company_snapshot"))
    parser.add_argument("--output", type=Path, default=Path("data/generated/company/yahoo_company_snapshot.json"))
    parser.add_argument("--ttl-days", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--report", type=Path, default=Path("data/generated/provider_cache/yahoo/company_snapshot_refresh_report.json"))
    parser.add_argument("--diagnostic", type=Path, default=Path("data/generated/provider_cache/yahoo/provider_diagnostic.json"))
    parser.add_argument("--error-log", type=Path, default=Path("data/generated/provider_cache/yahoo/provider_errors.log"))
    args = parser.parse_args()

    symbols = list(args.symbols)
    if args.symbols_file:
        symbols.extend(load_symbols(args.symbols_file))
    symbols = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    if not symbols:
        parser.error("provide --symbols or --symbols-file")
    if args.offset < 0 or (args.limit is not None and args.limit < 1):
        parser.error("--offset must be non-negative and --limit must be positive")
    symbols = symbols[args.offset:None if args.limit is None else args.offset + args.limit]

    cache = YahooCompanySnapshotCache(
        args.cache_root,
        canonical_output_path=args.output,
        ttl_days=args.ttl_days,
        diagnostic_path=args.diagnostic,
        error_log_path=args.error_log,
    )
    report = refresh_yahoo_company_snapshots(
        symbols,
        fetcher=YFinanceCompanyInfoFetcher(),
        cache=cache,
        now=datetime.now(tz=timezone.utc),
        request_delay_seconds=args.delay,
        force=args.force,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Requested: {report.requested}")
    print(f"Fetched: {report.fetched}")
    print(f"Succeeded: {report.succeeded}")
    print(f"Skipped: {report.skipped_cached_before_request}")
    print(f"Failed: {report.failed}")
    print(f"Success rate: {report.success_rate * 100:.1f}%")
    print(f"Cache TTL days: {report.cache_ttl_days}")
    print(f"Symbol cache: {report.symbol_cache_root}")
    print(f"Canonical output: {report.output_path}")
    print(f"Diagnostic: {report.diagnostic_path}")
    print(f"Error log: {report.error_log_path}")
    print(f"Report: {args.report}")
    if report.failures:
        print("Failures:")
        for symbol, failure in sorted(report.failures.items()):
            print(f"  {symbol}: {failure}")
    return 0 if report.failed == 0 else 2


def load_symbols(path: Path) -> Iterable[str]:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".list"}:
        return [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return [_symbol_from_mapping(row) for row in csv.DictReader(handle) if _symbol_from_mapping(row)]
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return _symbols_from_json(payload)


def _symbols_from_json(payload: object) -> list[str]:
    if isinstance(payload, list):
        result: list[str] = []
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
        if item.get(key):
            return str(item[key]).strip()
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
