#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.sec_financial_population import (  # noqa: E402
    build_sec_financial_population,
    write_sec_financial_population,
)



def yahoo_quarterly_backfill(symbols: list[str], *, write: bool = False) -> None:
    """Fill missing EPS/shares in existing SEC quarterly identities; no Yahoo fiscal inference."""
    from datetime import date
    from decimal import Decimal, InvalidOperation

    import yfinance as yf

    canonical = ROOT / "data/generated/canonical_financial_population"
    quarterly_index = json.loads((canonical / "quarterly_index.json").read_text(encoding="utf-8"))
    company_files = quarterly_index["company_id_to_file"]
    market_index = json.loads((ROOT / "data/generated/full_market_coverage/full_market_coverage.json").read_text(encoding="utf-8"))
    ticker_files = market_index["indexes"]["ticker_to_file"]
    metrics = {
        "Diluted EPS": ("diluted_eps", "currency_per_share"),
        "Diluted Average Shares": ("diluted_shares_outstanding", "shares"),
    }
    total_proposed = 0
    updated_companies = 0
    for symbol in dict.fromkeys(x.upper().strip() for x in symbols if x.strip()):
        relative = ticker_files.get(symbol)
        if not relative:
            print(f"SKIP {symbol}: missing Full Market ticker identity")
            continue
        card = json.loads((ROOT / "data/generated/full_market_coverage" / relative).read_text(encoding="utf-8"))
        company_id = str(card.get("company", {}).get("company_id") or "")
        quarterly_rel = company_files.get(company_id)
        if not quarterly_rel:
            print(f"SKIP {symbol}: no existing SEC quarterly history")
            continue
        path = canonical / quarterly_rel
        rows = json.loads(path.read_text(encoding="utf-8"))
        periods = {}
        for row in rows:
            period = str(row.get("fiscal_period") or "")
            end = str(row.get("period_end") or "")
            if period not in {"Q1", "Q2", "Q3", "Q4"} or not end:
                continue
            periods.setdefault(end, []).append(row)
        try:
            statement = yf.Ticker(symbol).quarterly_income_stmt
        except Exception as exc:
            print(f"SKIP {symbol}: Yahoo error: {type(exc).__name__}: {exc}")
            continue
        if statement is None or statement.empty:
            print(f"SKIP {symbol}: no Yahoo quarterly income statement")
            continue
        proposed = []
        for column in statement.columns:
            yahoo_end = column.date() if hasattr(column, "date") else date.fromisoformat(str(column)[:10])
            matches = []
            for end in periods:
                try:
                    difference = abs((date.fromisoformat(end) - yahoo_end).days)
                except ValueError:
                    continue
                if difference <= 7:
                    matches.append((difference, end))
            matches.sort()
            if not matches or (len(matches) > 1 and matches[0][0] == matches[1][0]):
                continue
            diff, end = matches[0]
            identity = {(int(r.get("fiscal_year") or 0), str(r.get("fiscal_period") or "")) for r in periods[end]}
            if len(identity) != 1:
                print(f"SKIP {symbol} {end}: ambiguous existing fiscal identity")
                continue
            fiscal_year, fiscal_period = next(iter(identity))
            template = periods[end][0]
            for yahoo_label, (metric, unit) in metrics.items():
                if yahoo_label not in statement.index or any(r.get("metric") == metric for r in periods[end]):
                    continue
                raw = statement.at[yahoo_label, column]
                try:
                    value = Decimal(str(raw))
                except (InvalidOperation, TypeError, ValueError):
                    continue
                if not value.is_finite() or (metric == "diluted_shares_outstanding" and value <= 0):
                    continue
                if metric == "diluted_shares_outstanding":
                    if value != value.to_integral_value():
                        continue
                    result = str(int(value))
                else:
                    result = format(value, 'f')
                # SEC-period identity is authoritative; Yahoo date is only a +/-7d match.
                fact = {
                    "financial_fact_id": f"quarterly_financial_fact:yahoo:{company_id}:{metric}:{end}:{fiscal_period}",
                    "company_id": company_id,
                    "metric": metric,
                    "value": result,
                    "unit": unit,
                    "currency": "USD" if unit == "currency_per_share" else None,
                    "period_type": "duration",
                    "period_start": template.get("period_start"),
                    "period_end": end,
                    "fiscal_year": fiscal_year,
                    "fiscal_period": fiscal_period,
                    "statement": "income_statement",
                    "form_type": None,
                    "filed_at": None,
                    "accession_number": None,
                    "source": {"provider": "yahoo_finance_quarterly_income_stmt", "yahoo_period_end": yahoo_end.isoformat(), "period_match_days": diff, "period_selection": "missing_sec_quarterly_metric_backfill"},
                }
                proposed.append(fact)
                print(f"{'WRITE' if write else 'DRY'} {symbol} FY{fiscal_year}{fiscal_period} {end} {metric}={result} (Yahoo {yahoo_end})")
        # No metric from Yahoo may displace an SEC/6-K fact, including any future duplicate.
        old_keys = {(r.get("period_end"), r.get("metric")) for r in rows}
        proposed = [r for r in proposed if (r["period_end"], r["metric"]) not in old_keys]
        total_proposed += len(proposed)
        if write and proposed:
            rows.extend(proposed)
            rows.sort(key=lambda r: (str(r.get("period_end")), str(r.get("metric"))))
            tmp = path.with_suffix('.json.tmp')
            tmp.write_text(json.dumps(rows, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
            tmp.replace(path)
            updated_companies += 1
        print(f"{symbol}: {len(proposed)} missing metrics {'written' if write else 'proposed'}")
    print(json.dumps({"mode": "WRITE" if write else "DRY_RUN", "proposed_metric_count": total_proposed, "updated_company_count": updated_companies, "full_market_rebuild_required": bool(write and updated_companies)}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build full-scope SEC Companyfacts financial population.")
    parser.add_argument("--bulk-zip", type=Path)
    parser.add_argument("--download-bulk", action="store_true")
    parser.add_argument("--user-agent", default="")
    parser.add_argument("--write-cache", action="store_true")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--merge-existing", action="store_true")
    parser.add_argument("--refresh-plan")
    parser.add_argument("--yahoo-quarterly-symbols", nargs="*", help="Yahoo missing-metric backfill for existing SEC quarters; no SEC download")
    parser.add_argument("--yahoo-quarterly-write", action="store_true", help="Write Yahoo backfills to Canonical; default is read-only")
    args = parser.parse_args()
    if args.yahoo_quarterly_symbols is not None:
        if not args.yahoo_quarterly_symbols:
            parser.error("--yahoo-quarterly-symbols requires at least one ticker")
        yahoo_quarterly_backfill(args.yahoo_quarterly_symbols, write=args.yahoo_quarterly_write)
        return 0
    if args.download_bulk:
        if not args.bulk_zip:
            parser.error("--download-bulk requires --bulk-zip")
        if not re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", args.user_agent):
            parser.error("--user-agent must include a contact email")
        request = urllib.request.Request(
            "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip",
            headers={"User-Agent": args.user_agent},
        )
        args.bulk_zip.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.bulk_zip.with_suffix(".zip.tmp")
        with urllib.request.urlopen(request, timeout=300) as response:
            temporary.write_bytes(response.read())
        temporary.replace(args.bulk_zip)
    company_ids = None
    if args.refresh_plan:
        plan = json.loads((ROOT / args.refresh_plan).read_text(encoding="utf-8"))
        company_ids = [
            str(row["company_id"])
            for row in plan.get("worklist") or []
            if row.get("requires_financial_refresh") is not False
        ]
    report = build_sec_financial_population(
        ROOT, bulk_zip=args.bulk_zip, limit=args.limit, offset=args.offset,
        write_cache=args.write_cache, company_ids=company_ids,
    )
    if args.write:
        write_sec_financial_population(
            report,
            ROOT / "data/generated/canonical_financial_population",
            merge_existing=args.merge_existing,
        )
    print(report["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
