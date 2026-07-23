from __future__ import annotations

import json
from datetime import datetime, timezone

import typer

from .cached_close import write_close_cache
from .config import GENERATED_DIR, PREVIOUS_CLOSE_CACHE
from .io import read_json, write_json
from .previous_close import PreviousCloseError, YahooPreviousCloseAdapter
from .repository import load_bundle
from .services.public_builder import build_public
from .services.validator import validate_bundle
from .services.valuation import run_valuation_book
from .services.research import research_summary
from .services.industry import industry_summary, find_paths
from .services.etf import etf_summary
from .services.impact import impact_summary

app = typer.Typer(no_args_is_help=True)


@app.command()
def validate() -> None:
    summary = validate_bundle(load_bundle())
    typer.echo(f"OK {summary.compact()}")


@app.command()
def value(
    company_id: str = typer.Option("company:US-NVDA"),
    security_id: str = typer.Option("security:NASDAQ-NVDA"),
    scenario_id: str = typer.Option("valuation_scenario:NVDA-2026Q3-BASE"),
) -> None:
    bundle = load_bundle()
    validate_bundle(bundle)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    ep = GENERATED_DIR / "executions.json"
    sp = GENERATED_DIR / "valuation_snapshots.json"
    bp = GENERATED_DIR / "valuation_books.json"
    executions = read_json(ep) if ep.exists() else []
    snapshots = read_json(sp) if sp.exists() else []
    books = read_json(bp) if bp.exists() else []
    new_executions, new_snapshots, book = run_valuation_book(
        bundle,
        company_id=company_id,
        security_id=security_id,
        scenario_id=scenario_id,
        existing_snapshot_ids={x["valuation_snapshot_id"] for x in snapshots},
    )
    executions.extend(x.model_dump(mode="json", exclude_none=True) for x in new_executions)
    snapshots.extend(x.model_dump(mode="json", exclude_none=True) for x in new_snapshots)
    books = [x for x in books if x["valuation_book_id"] != book.valuation_book_id]
    books.append(book.model_dump(mode="json", exclude_none=True))
    write_json(ep, executions)
    write_json(sp, snapshots)
    write_json(bp, books)
    typer.echo(
        json.dumps(
            {
                "valuation_book_id": book.valuation_book_id,
                "created_snapshots": len(new_snapshots),
                "models": [
                    {
                        "model": x.model_type,
                        "status": x.status,
                        "fair_value": x.fair_value_per_share,
                        "upside": x.upside,
                    }
                    for x in book.entries
                ],
                "blended_fair_value": book.blended_fair_value,
                "blended_upside": book.blended_upside,
            },
            ensure_ascii=False,
        )
    )


@app.command()
def research(company_id: str = typer.Option("company:US-NVDA")) -> None:
    bundle = load_bundle()
    validate_bundle(bundle)
    typer.echo(json.dumps(research_summary(bundle, company_id), ensure_ascii=False, indent=2))


@app.command()
def industry(
    company_id: str = typer.Option("company:US-NVDA"),
    source_id: str | None = typer.Option(None),
    target_id: str | None = typer.Option(None),
) -> None:
    bundle = load_bundle()
    validate_bundle(bundle)
    payload = industry_summary(bundle, company_id)
    if source_id and target_id:
        payload["paths"] = find_paths(bundle, source_id, target_id)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command()
def etf(etf_id: str = typer.Option("etf:AXSM")) -> None:
    bundle = load_bundle()
    validate_bundle(bundle)
    typer.echo(json.dumps(etf_summary(bundle, etf_id), ensure_ascii=False, indent=2))


@app.command()
def impact(shock_id: str = typer.Option("shock:CLOUD-AI-CAPEX-DOWN-15")) -> None:
    bundle = load_bundle()
    validate_bundle(bundle)
    typer.echo(json.dumps(impact_summary(bundle, shock_id), ensure_ascii=False, indent=2))


@app.command("refresh-closes")
def refresh_closes(
    symbol: list[str] | None = typer.Option(
        None, "--symbol", "-s", help="Ticker to refresh; repeat for multiple symbols."
    ),
) -> None:
    """Fetch completed daily closes once and persist them for the Render API."""
    bundle = load_bundle()
    requested = {item.strip().upper() for item in (symbol or []) if item.strip()}
    symbols = sorted(
        {item.ticker.upper() for item in bundle.securities if item.active}
        if not requested
        else requested
    )
    provider = YahooPreviousCloseAdapter()
    closes = []
    failures = []
    for ticker in symbols:
        try:
            closes.append(provider.previous_close(ticker))
            typer.echo(f"OK {ticker} {closes[-1].session_date} {closes[-1].close}")
        except PreviousCloseError as exc:
            failures.append(f"{ticker}: {exc}")
            typer.echo(f"WARN {ticker}: {exc}", err=True)

    if closes:
        write_close_cache(
            PREVIOUS_CLOSE_CACHE, closes, generated_at=datetime.now(timezone.utc)
        )
    if not closes:
        raise typer.Exit(code=1)
    typer.echo(
        f"Updated {len(closes)} close(s) in {PREVIOUS_CLOSE_CACHE}; "
        f"failures={len(failures)}"
    )


@app.command("build-public")
def build_public_command() -> None:
    bundle = load_bundle()
    validate_bundle(bundle)
    typer.echo(f"Built public JSON: {build_public(bundle)}")


@app.command()
def run() -> None:
    validate()
    value()
    build_public_command()


if __name__ == "__main__":
    app()
