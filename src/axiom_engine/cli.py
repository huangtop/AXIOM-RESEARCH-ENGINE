from __future__ import annotations

import json
import typer
from axiom_engine.market_data import import_market_data, validate_market_data
from axiom_engine.company_registry_builder import build_real_100_registry, validate_real_100_registry
from .config import GENERATED_DIR
from .io import read_json, write_json
from .repository import load_bundle
from .services.public_builder import build_public
from .services.validator import validate_bundle
from .services.valuation import run_valuation_book
from .services.research import research_summary
from .services.industry import industry_summary, find_paths
from .services.etf import etf_summary
from .services.impact import impact_summary
from .company_registry import import_company_universe
from .ontology import load_ontology, validate_ontology, OntologyRegistry
from .financial_data import import_financial_data, validate_financial_data
from .estimate_data import import_estimate_data, validate_estimate_data
from .canonical_valuation import run_batch_valuation, validate_canonical_valuation, valuation_readiness
from .real_100_onboarding import build_sec_registry_source, load_cohort, onboarding_status

app = typer.Typer(no_args_is_help=True)
ontology_app = typer.Typer(no_args_is_help=True)
app.add_typer(ontology_app, name="ontology")


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


@app.command("import-company-universe")
def import_company_universe_command(
    source: str = typer.Option(..., help="Independent company-universe source JSON"),
    output_dir: str = typer.Option("data/company_registry"),
    write: bool = typer.Option(False, "--write", help="Write output; default is dry-run"),
) -> None:
    report = import_company_universe(
        source,
        output_dir=output_dir,
        dry_run=not write,
    )
    typer.echo(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))


@ontology_app.command("validate")
def ontology_validate_command(root: str = typer.Option("data/ontology")) -> None:
    stats = validate_ontology(load_ontology(root))
    typer.echo("OK " + " ".join(f"{k}={v}" for k, v in stats.items()))


@ontology_app.command("stats")
def ontology_stats_command(root: str = typer.Option("data/ontology")) -> None:
    stats = validate_ontology(load_ontology(root))
    typer.echo(json.dumps(stats, ensure_ascii=False, indent=2))


@ontology_app.command("list-types")
def ontology_list_types_command(root: str = typer.Option("data/ontology")) -> None:
    bundle = load_ontology(root)
    typer.echo(json.dumps({"entity_types": [x.entity_type_id for x in bundle.entity_types], "relation_types": [x.relation_type_id for x in bundle.relation_types]}, ensure_ascii=False, indent=2))


@ontology_app.command("show")
def ontology_show_command(entity_id: str, root: str = typer.Option("data/ontology")) -> None:
    bundle = load_ontology(root)
    registry = OntologyRegistry(bundle)
    if entity_id not in registry.entities:
        raise typer.BadParameter(f"unknown ontology entity: {entity_id}")
    entity = registry.entities[entity_id]
    typer.echo(json.dumps({**entity.__dict__, "aliases": list(entity.aliases), "parents": registry.parents(entity_id), "children": registry.children(entity_id)}, ensure_ascii=False, indent=2))


@app.command("import-financial-data")
def import_financial_data_command(
    source: str = typer.Option(..., help="Provider-normalized financial data source JSON"),
    output_dir: str = typer.Option("data/financial_data"),
    company_registry_dir: str = typer.Option("data/company_registry"),
    write: bool = typer.Option(False, "--write", help="Write output; default is dry-run"),
) -> None:
    report = import_financial_data(source, output_dir=output_dir, company_registry_dir=company_registry_dir, dry_run=not write)
    typer.echo(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))


@app.command("validate-financial-data")
def validate_financial_data_command(root: str = typer.Option("data/financial_data")) -> None:
    stats = validate_financial_data(root)
    typer.echo("OK " + " ".join(f"{key}={value}" for key, value in stats.items()))


@app.command("import-estimate-data")
def import_estimate_data_command(
    source: str = typer.Option(..., help="Provider-normalized estimate data source JSON"),
    output_dir: str = typer.Option("data/estimate_data"),
    company_registry_dir: str = typer.Option("data/company_registry"),
    write: bool = typer.Option(False, "--write", help="Write output; default is dry-run"),
) -> None:
    report = import_estimate_data(source, output_dir=output_dir, company_registry_dir=company_registry_dir, dry_run=not write)
    typer.echo(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))


@app.command("validate-estimate-data")
def validate_estimate_data_command(root: str = typer.Option("data/estimate_data")) -> None:
    stats = validate_estimate_data(root)
    typer.echo("OK " + " ".join(f"{key}={value}" for key, value in stats.items()))


@app.command("valuation-readiness")
def valuation_readiness_command(
    financial_dir: str = typer.Option("data/financial_data"),
    estimate_dir: str = typer.Option("data/estimate_data"),
    required_company_count: int = typer.Option(100, min=1),
) -> None:
    report = valuation_readiness(financial_dir=financial_dir, estimate_dir=estimate_dir, required_company_count=required_company_count)
    typer.echo(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    if not report.acceptance_passed:
        raise typer.Exit(code=2)


@app.command("run-canonical-valuation")
def run_canonical_valuation_command(
    financial_dir: str = typer.Option("data/financial_data"),
    estimate_dir: str = typer.Option("data/estimate_data"),
    output_dir: str = typer.Option("data/canonical_valuation"),
    write: bool = typer.Option(False, "--write", help="Write output; default is dry-run"),
) -> None:
    report = run_batch_valuation(financial_dir=financial_dir, estimate_dir=estimate_dir, output_dir=output_dir, dry_run=not write)
    typer.echo(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))


@app.command("validate-canonical-valuation")
def validate_canonical_valuation_command(root: str = typer.Option("data/canonical_valuation")) -> None:
    stats = validate_canonical_valuation(root)
    typer.echo("OK " + " ".join(f"{key}={value}" for key, value in stats.items()))


@app.command("real-100-plan")
def real_100_plan_command(cohort_path: str = typer.Option("data/onboarding/us_real_100_cohort.json")) -> None:
    typer.echo(json.dumps(load_cohort(cohort_path).model_dump(mode="json"), ensure_ascii=False, indent=2))

@app.command("real-100-status")
def real_100_status_command(cohort_path: str = typer.Option("data/onboarding/us_real_100_cohort.json"), registry_dir: str = typer.Option("data/company_registry"), financial_dir: str = typer.Option("data/financial_data"), estimate_dir: str = typer.Option("data/estimate_data")) -> None:
    report=onboarding_status(cohort_path,registry_dir,financial_dir,estimate_dir); typer.echo(json.dumps(report,ensure_ascii=False,indent=2))
    if not report["acceptance_passed"]: raise typer.Exit(code=2)

@app.command("build-sec-real-100-registry-source")
def build_sec_real_100_registry_source_command(user_agent: str = typer.Option(...), cohort_path: str = typer.Option("data/onboarding/us_real_100_cohort.json"), output: str = typer.Option("data/onboarding/generated/company_universe_source.json"), write: bool = typer.Option(False,"--write")) -> None:
    typer.echo(json.dumps(build_sec_registry_source(user_agent,cohort_path,output,write),ensure_ascii=False,indent=2))


@app.command("import-market-data")
def import_market_data_command(
    source: str = typer.Option(..., help="Provider-normalized market data source JSON"),
    output_dir: str = typer.Option("data/market_data"),
    company_registry_dir: str = typer.Option("data/company_registry"),
    write: bool = typer.Option(False, "--write", help="Write output; default is dry-run"),
) -> None:
    report = import_market_data(source, output_dir=output_dir, company_registry_dir=company_registry_dir, dry_run=not write)
    typer.echo(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))


@app.command("validate-market-data")
def validate_market_data_command(root: str = typer.Option("data/market_data")) -> None:
    stats = validate_market_data(root)
    typer.echo("OK " + " ".join(f"{key}={value}" for key, value in stats.items()))


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


@app.command("build-real-100-company-registry")
def build_real_100_company_registry_command(
    user_agent: str = typer.Option(..., help="SEC-compliant application and contact email"),
    cohort_path: str = typer.Option("data/onboarding/us_real_100_cohort.json"),
    sec_file: str | None = typer.Option(None, help="Optional downloaded SEC JSON for deterministic/offline runs"),
    source_output: str = typer.Option("data/onboarding/generated/real_100_company_registry_source.json"),
    registry_dir: str = typer.Option("data/company_registry"),
    write: bool = typer.Option(False, "--write", help="Write source and canonical registry; default is dry-run"),
) -> None:
    report = build_real_100_registry(user_agent=user_agent, cohort_path=cohort_path, sec_file=sec_file, source_output=source_output, registry_dir=registry_dir, write=write)
    typer.echo(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))


@app.command("validate-real-100-company-registry")
def validate_real_100_company_registry_command(
    cohort_path: str = typer.Option("data/onboarding/us_real_100_cohort.json"),
    registry_dir: str = typer.Option("data/company_registry"),
) -> None:
    report = validate_real_100_registry(cohort_path=cohort_path, registry_dir=registry_dir)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["acceptance_passed"]:
        raise typer.Exit(code=2)
