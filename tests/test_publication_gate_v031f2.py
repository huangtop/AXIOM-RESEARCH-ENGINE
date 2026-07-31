from pathlib import Path
from zipfile import ZipFile

from axiom_engine.full_market_coverage import FullMarketCoverageService
from axiom_engine.publication_gate import build_publication_catalog, write_publication_catalog


ROOT = Path(__file__).resolve().parents[1]


def test_real_catalog_separates_market_publication_from_research_actions():
    report = build_publication_catalog(ROOT)
    by_ticker = {row["ticker"]: row for row in report["companies"]}
    assert report["summary"]["public_company_count"] == 5851
    assert report["summary"]["frontier_research_count"] == 80
    assert report["summary"]["scope_axis_counts"]["news_ai"] == 68
    assert report["summary"]["scope_axis_counts"]["etf_exposure"] == 5851
    assert by_ticker["MU"]["research_scope"] == "core"
    assert by_ticker["F"]["product_scope"] == "basic_market"
    assert by_ticker["F"]["scope_axes"]["research_page"] is False
    assert "BOTZ" not in by_ticker


def test_per_company_archive_supports_single_ticker_lookup_without_snapshot(tmp_path: Path):
    report = build_publication_catalog(ROOT)
    output = tmp_path / "data/generated/publication_gate/company_catalog.json"
    write_publication_catalog(report, output)
    archive = output.parent / "company_projections.zip"
    with ZipFile(archive) as bundle:
        assert "NVDA.json" in bundle.namelist()
    service = FullMarketCoverageService(
        root=ROOT,
        snapshot_path=tmp_path / "missing-full-market.json",
        publication_root=output.parent,
    )
    assert service.get("NVDA")["primary_security"]["ticker"] == "NVDA"
    assert service._payload is None
