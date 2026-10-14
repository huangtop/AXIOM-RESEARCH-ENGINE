#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.previous_close import YahooPreviousCloseAdapter  # noqa: E402
from axiom_engine.providers.yahoo_daily_close import (  # noqa: E402
    YahooDailyCloseArchive,
    refresh_yahoo_daily_closes,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh Yahoo completed daily closes with session freshness checks")
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--symbols-file", type=Path)
    parser.add_argument("--universe-root", type=Path)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--archive-root", type=Path, default=Path("data/generated/provider_cache/yahoo/daily_close"))
    parser.add_argument("--latest-cache", type=Path, default=Path("data/generated/market/previous_close_cache.json"))
    parser.add_argument("--refresh-state", type=Path, default=Path("data/generated/provider_cache/yahoo/daily_close_state.json"))
    parser.add_argument("--retention-days", type=int, default=365)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--checkpoint-size", type=int, default=25)
    parser.add_argument("--retry-stale", action="store_true", help="One targeted second pass for stale symbols only")
    parser.add_argument("--max-failure-rate", type=float, default=0.0)
    parser.add_argument("--min-fresh-coverage", type=float, default=0.0, help="Minimum share of universe at the target completed US session")
    parser.add_argument("--report", type=Path, default=Path("data/generated/market/daily_close_refresh_report.json"))
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
    if not 0 <= args.max_failure_rate <= 1:
        parser.error("--max-failure-rate must be between zero and one")
    if not 0 <= args.min_fresh_coverage <= 1:
        parser.error("--min-fresh-coverage must be between zero and one")
    symbols = symbols[args.offset:]
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        symbols = symbols[:args.limit]

    as_of = datetime.now(tz=timezone.utc)
    print("Yahoo daily close refresh")
    print(f"As of UTC: {as_of.isoformat()}")
    print(f"Symbols: {len(symbols)}")
    print(f"Force refetch: {'yes' if args.force else 'no'}")
    print(f"Selective stale retry: {'yes' if args.retry_stale else 'no'}")
    archive = YahooDailyCloseArchive(
        args.archive_root, latest_cache_path=args.latest_cache,
        refresh_state_path=args.refresh_state, retention_days=args.retention_days,
    )
    report = refresh_yahoo_daily_closes(
        symbols,
        fetcher=YahooPreviousCloseAdapter(timeout_seconds=args.timeout),
        archive=archive, as_of=as_of,
        request_delay_seconds=args.delay,
        skip_existing=not args.force,
        checkpoint_size=args.checkpoint_size,
        retry_stale=args.retry_stale,
    )
    provider_attempted = report.provider_attempted
    provider_failure_rate = (
        (provider_attempted - report.provider_succeeded) / provider_attempted
        if provider_attempted else 0.0
    )
    universe_failure_rate = report.failed / report.requested if report.requested else 0.0
    coverage = report.target_coverage_rate

    payload = report.to_dict()
    payload["execution"] = {
        "generated_at": as_of.isoformat(), "force": args.force,
        "skip_existing": not args.force, "retry_stale": args.retry_stale,
        "provider_requests_attempted": provider_attempted,
        "provider_failure_rate": provider_failure_rate,
        "universe_failure_rate": universe_failure_rate,
        "ci_failure_rate_basis": "requested_universe",
        "target_session_date": report.target_session_date,
        "fresh_coverage_rate": round(coverage, 6),
        "min_fresh_coverage": args.min_fresh_coverage,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if not args.report.exists() or args.report.read_text(encoding="utf-8") != content:
        args.report.write_text(content, encoding="utf-8")

    print("\nRefresh result")
    print(f"Requested universe: {report.requested}")
    print(f"Provider attempts (including retries): {provider_attempted}")
    print(f"Provider responses succeeded: {report.provider_succeeded}")
    print(f"New or updated archive rows: {report.succeeded}")
    print(f"Skipped fresh cache: {report.skipped_existing}")
    print(f"Provider errors after retries: {report.failed}")
    print(f"Target completed US session: {report.target_session_date}")
    print(f"Fresh symbols: {report.fresh}")
    print(f"Stale or missing: {report.stale}")
    print(f"Fresh coverage: {coverage:.2%} (minimum {args.min_fresh_coverage:.2%})")
    print(f"Selective retries: {report.retry_attempted}, recovered: {report.retry_recovered}")
    print(f"Unresolved universe provider error rate: {universe_failure_rate:.2%}")
    print(f"Report: {args.report}")
    if universe_failure_rate > args.max_failure_rate:
        print("ERROR: Provider failure rate gate failed")
        return 2
    if coverage < args.min_fresh_coverage:
        print("ERROR: Target trading-session coverage gate failed")
        return 3
    return 0


def load_symbols(path: Path) -> Iterable[str]:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".list"}:
        return [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        return [_symbol_from_mapping(row) for row in rows if _symbol_from_mapping(row)]
    return _symbols_from_json(json.loads(path.read_text(encoding="utf-8-sig")))


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
        eligible_security_ids = {str(row.get("security_id")) for row in normalization.get("securities", [])
                                 if row.get("valuation_eligible") is True}
        included_company_ids = {str(row.get("company_id")) for row in normalization.get("companies", [])
                                if row.get("valuation_scope_status") == "included"}
    by_company: dict[str, list[Mapping[str, object]]] = {}
    for row in securities:
        if isinstance(row, Mapping) and row.get("status") in (None, "active"):
            by_company.setdefault(str(row.get("company_id") or ""), []).append(row)
    output: list[str] = []
    for company in companies:
        if not isinstance(company, Mapping):
            continue
        company_id = str(company.get("company_id") or "")
        if included_company_ids is not None and company_id not in included_company_ids:
            continue
        primary = by_id.get(str(company.get("primary_security_id") or ""))
        if primary and eligible_security_ids is not None and str(primary.get("security_id")) not in eligible_security_ids:
            primary = None
        if not primary:
            primary = next((row for row in by_company.get(company_id, [])
                            if row.get("primary_listing") is True and
                            (eligible_security_ids is None or str(row.get("security_id")) in eligible_security_ids)), None)
        if not primary:
            primary = next((row for row in by_company.get(company_id, [])
                            if eligible_security_ids is None or str(row.get("security_id")) in eligible_security_ids), None)
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
            if key not in payload:
                continue
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
