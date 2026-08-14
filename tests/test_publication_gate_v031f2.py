import json
from pathlib import Path
from zipfile import ZipFile

from axiom_engine.full_market_coverage import FullMarketCoverageService
from axiom_engine.publication_gate import build_publication_catalog, write_publication_catalog


VALUATION_MODELS = {
    "dcf", "forward_pe", "peg", "forward_ps", "forward_pb", "ev_ebitda", "milestone"
}


ROOT = Path(__file__).resolve().parents[1]


def test_real_catalog_separates_market_publication_from_research_actions():
    report = build_publication_catalog(ROOT)
    eligibility = json.loads(
        (ROOT / "data/generated/research_eligibility/research_eligibility.json").read_text()
    )
    by_ticker = {row["ticker"]: row for row in report["companies"]}
    assert report["summary"]["public_company_count"] == 5851
    selected_ids = {
        row["company_id"] for row in eligibility["records"]
        if row.get("research_universe_status") == "selected"
    }
    public_ids = {row["company_id"] for row in report["companies"]}
    assert report["summary"]["frontier_research_count"] == len(selected_ids & public_ids)
    assert report["summary"]["scope_axis_counts"]["supply_chain_context"] == 1000
    assert report["summary"]["scope_axis_counts"]["news_ai"] == eligibility["summary"][
        "active_intelligence_company_count"
    ]
    assert report["summary"]["scope_axis_counts"]["etf_exposure"] == 5851
    assert by_ticker["MU"]["research_scope"] == "core"
    assert by_ticker["F"]["product_scope"] == "basic_market"
    assert by_ticker["F"]["scope_axes"]["research_page"] is False
    assert "BOTZ" not in by_ticker
    nvda_models = report["_company_projections"]["NVDA"]["valuation_card"]["valuation"][
        "models"
    ]
    assert set(nvda_models) == VALUATION_MODELS
    assert len(nvda_models) == 7


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


def test_publication_catalog_maps_secondary_share_class_to_primary_projection(tmp_path: Path):
    report = build_publication_catalog(ROOT)
    index = report["indexes"]["ticker_to_file"]
    assert index["GOOG"] == index["GOOGL"] == "GOOGL.json"
    assert "GOOGM" not in index
    assert "GOOGN" not in index
    output = tmp_path / "data/generated/publication_gate/company_catalog.json"
    write_publication_catalog(report, output)
    service = FullMarketCoverageService(root=ROOT, snapshot_path=tmp_path / "missing.json", publication_root=output.parent)
    goog = service.get("GOOG")
    googl = service.get("GOOGL")
    assert goog["company"]["company_id"] == googl["company"]["company_id"]
    assert goog["primary_security"]["ticker"] == "GOOGL"


def test_incremental_manifest_uses_stable_hashed_shards_and_reports_only_changes(tmp_path: Path):
    report = build_publication_catalog(ROOT)
    output = tmp_path / "publication/company_catalog.json"
    write_publication_catalog(report, output)
    first = json.loads((output.parent / "manifest.json").read_text())
    assert len(first["changed_company_ids"]) == first["company_count"]
    nvda = first["companies"]["NVDA"]
    assert nvda["sha256"][:16] in nvda["path"]
    assert (output.parent / nvda["path"]).is_file()

    second_report = build_publication_catalog(ROOT)
    write_publication_catalog(second_report, output)
    second = json.loads((output.parent / "manifest.json").read_text())
    assert second["release_id"] == first["release_id"]
    assert second["changed_company_ids"] == []
    assert second["companies"]["NVDA"]["path"] == nvda["path"]
