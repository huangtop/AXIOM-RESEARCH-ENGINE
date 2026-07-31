from pathlib import Path

from axiom_engine.publication_gate import build_publication_catalog


ROOT = Path(__file__).resolve().parents[1]


def test_real_catalog_emits_only_public_core_and_coverage_companies():
    report = build_publication_catalog(ROOT)
    by_ticker = {row["ticker"]: row for row in report["companies"]}
    assert report["summary"]["public_company_count"] == 80
    assert report["summary"]["core_count"] == 68
    assert report["summary"]["coverage_count"] == 12
    assert report["summary"]["contextual_or_excluded_records_emitted"] == 0
    assert by_ticker["MU"]["publication_tier"] == "core"
    assert by_ticker["TSLA"]["company_page"] is True
    assert "SKHY" not in by_ticker
    assert "F" not in by_ticker
    assert "C" not in by_ticker
    assert "NKE" not in by_ticker
