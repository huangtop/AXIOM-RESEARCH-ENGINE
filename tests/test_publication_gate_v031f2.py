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
    assert report["summary"]["public_company_count"] == len(report["companies"])
    # Publication is security/card based, while research eligibility is company
    # based.  Comparing their de-duplicated company-id counts is invalid when a
    # company has multiple listings or a publication card resolves through a
    # ticker alias.  Validate the actual publication contract row by row.
    frontier_rows = [
        row for row in report["companies"]
        if row["product_scope"] == "frontier_research"
    ]
    assert report["summary"]["frontier_research_count"] == len(frontier_rows)
    assert all(row["scope_axes"]["research_page"] is True for row in frontier_rows)
    assert all(
        (row["product_scope"] == "frontier_research")
        == (row["scope_axes"]["research_page"] is True)
        for row in report["companies"]
    )
    supply_chain_context_rows = [
        row for row in report["companies"]
        if row["scope_axes"].get("supply_chain_context") is True
    ]
    assert report["summary"]["scope_axis_counts"]["supply_chain_context"] == len(
        supply_chain_context_rows
    )
    assert report["summary"]["scope_axis_counts"]["news_ai"] == eligibility["summary"][
        "active_intelligence_company_count"
    ]
    assert report["summary"]["scope_axis_counts"]["etf_exposure"] == len(
        report["companies"]
    )
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


def test_publication_retains_recent_hashed_shard_generations(tmp_path: Path):
    output = tmp_path / "publication/company_catalog.json"

    def report(value: int) -> dict:
        projection = {"company_id": "company:TEST", "ticker": "TEST", "value": value}
        return {
            "generated_at": f"2026-09-{value + 1:02d}T00:00:00+00:00",
            "companies": [],
            "indexes": {},
            "_company_projections": {"TEST": projection},
        }

    paths = []
    for value in range(4):
        write_publication_catalog(report(value), output, retention_generations=3)
        manifest = json.loads((output.parent / "manifest.json").read_text())
        paths.append(output.parent / manifest["companies"]["TEST"]["path"])

    assert not paths[0].exists()
    assert all(path.exists() for path in paths[1:])
    retention = json.loads((output.parent / "shard_retention.json").read_text())
    assert retention["retention_generations"] == 3
    assert len(retention["generations"]) == 3


def test_publication_defaults_to_current_and_previous_generation(tmp_path: Path):
    output = tmp_path / "publication/company_catalog.json"

    for value in range(3):
        projection = {"company_id": "company:TEST", "ticker": "TEST", "value": value}
        report = {
            "companies": [],
            "indexes": {},
            "_company_projections": {"TEST": projection},
        }
        write_publication_catalog(report, output)

    manifest = json.loads((output.parent / "manifest.json").read_text())
    retention = json.loads((output.parent / "shard_retention.json").read_text())
    assert manifest["retention_policy"]["company_shard_generations"] == 2
    assert retention["retention_generations"] == 2
    assert len(retention["generations"]) == 2


def test_publication_rejects_retention_that_can_delete_previous_generation(tmp_path: Path):
    output = tmp_path / "publication/company_catalog.json"
    report = {"_company_projections": {}, "companies": [], "indexes": {}}

    try:
        write_publication_catalog(report, output, retention_generations=1)
    except ValueError as exc:
        assert "at least 2" in str(exc)
    else:
        raise AssertionError("retention_generations=1 must be rejected")



def test_incremental_publication_builder_reads_only_selected_full_market_cards():
    report = build_publication_catalog(ROOT, symbols=["GOOG"])
    assert report["summary"]["incremental"] is True
    assert report["summary"]["selected_symbol_count"] == 1
    assert list(report["_company_projections"]) == ["GOOGL"]
    assert report["indexes"]["ticker_to_file"]["GOOG"] == "GOOGL.json"
    assert report["indexes"]["ticker_to_file"]["GOOGL"] == "GOOGL.json"


def test_incremental_publication_merges_manifest_and_catalog_without_touching_zip(
    tmp_path: Path,
):
    output = tmp_path / "publication/company_catalog.json"

    initial = build_publication_catalog(ROOT)
    write_publication_catalog(initial, output)

    first_manifest = json.loads((output.parent / "manifest.json").read_text())
    first_catalog = json.loads(output.read_text())
    archive = output.parent / "company_projections.zip"
    archive_before = archive.read_bytes()

    amd_entry_before = dict(first_manifest["companies"]["AMD"])
    nvda_entry_before = dict(first_manifest["companies"]["NVDA"])
    company_count_before = first_manifest["company_count"]
    catalog_count_before = len(first_catalog["companies"])

    partial = build_publication_catalog(ROOT, symbols=["NVDA"])
    assert list(partial["_company_projections"]) == ["NVDA"]
    partial["_company_projections"]["NVDA"]["valuation_card"]["company"][
        "display_name"
    ] = "NVIDIA incremental publication test"
    partial["companies"][0]["display_name"] = "NVIDIA incremental publication test"

    write_publication_catalog(partial, output, incremental=True)

    second_manifest = json.loads((output.parent / "manifest.json").read_text())
    second_catalog = json.loads(output.read_text())

    assert second_manifest["company_count"] == company_count_before
    assert len(second_catalog["companies"]) == catalog_count_before
    assert second_manifest["companies"]["AMD"] == amd_entry_before
    assert second_manifest["companies"]["NVDA"] != nvda_entry_before
    assert second_manifest["companies"]["NVDA"]["company_id"] in (
        second_manifest["changed_company_ids"]
    )
    assert archive.read_bytes() == archive_before

    amd_catalog_before = next(
        row for row in first_catalog["companies"] if row["ticker"] == "AMD"
    )
    amd_catalog_after = next(
        row for row in second_catalog["companies"] if row["ticker"] == "AMD"
    )
    nvda_catalog_after = next(
        row for row in second_catalog["companies"] if row["ticker"] == "NVDA"
    )
    assert amd_catalog_after == amd_catalog_before
    assert nvda_catalog_after["display_name"] == (
        "NVIDIA incremental publication test"
    )


def test_incremental_publication_retains_previous_manifest_generation(
    tmp_path: Path,
):
    output = tmp_path / "publication/company_catalog.json"

    initial = build_publication_catalog(ROOT)
    write_publication_catalog(initial, output)
    first_manifest = json.loads((output.parent / "manifest.json").read_text())
    first_nvda = output.parent / first_manifest["companies"]["NVDA"]["path"]

    partial = build_publication_catalog(ROOT, symbols=["NVDA"])
    partial["_company_projections"]["NVDA"]["valuation_card"]["company"][
        "display_name"
    ] = "NVIDIA retention generation test"
    write_publication_catalog(partial, output, incremental=True)

    second_manifest = json.loads((output.parent / "manifest.json").read_text())
    second_nvda = output.parent / second_manifest["companies"]["NVDA"]["path"]
    retention = json.loads((output.parent / "shard_retention.json").read_text())

    assert first_nvda.exists()
    assert second_nvda.exists()
    assert first_nvda != second_nvda
    assert retention["retention_generations"] == 2
    assert len(retention["generations"]) == 2
