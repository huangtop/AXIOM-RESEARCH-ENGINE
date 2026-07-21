from __future__ import annotations

import json
import typer
from .config import GENERATED_DIR
from .io import read_json, write_json
from .repository import load_bundle
from .services.public_builder import build_public
from .services.validator import validate_bundle
from .services.valuation import run_valuation_book
from .services.research import research_summary
from .services.industry import industry_summary, find_paths

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
