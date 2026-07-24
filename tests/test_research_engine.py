import json
from pathlib import Path

import pytest

from axiom_engine.research_engine import ResearchEngineError, build_research, validate_research


def fixture_root() -> Path:
    return Path(__file__).resolve().parents[1] / "examples" / "research_fixture"


def test_build_complete_research_bundle(tmp_path):
    root = fixture_root()
    report = build_research(registry_dir=root / "company_registry", financial_dir=root / "financial_data", estimate_dir=root / "estimate_data", market_dir=root / "market_data", valuation_dir=root / "valuation_data", output_dir=tmp_path, company="AAPL", write=True, compact=True)
    assert report["acceptance_passed"] is True
    assert report["completed"] == 0
    assert report["partial"] == 1
    rows = json.loads((tmp_path / "company_research.json").read_text())
    assert rows[0]["market_snapshot"]["current_price"]["value"] == "210.15"
    assert set(rows[0]["valuation_summary"]) == {"bear", "base", "bull"}
    assert rows[0]["confidence"]["score"] == 78
    assert rows[0]["confidence"]["components"]["valuation_completion"] == 13
    assert rows[0]["confidence"]["components"]["quality_penalty"] == -10


def test_source_record_ids_are_preserved(tmp_path):
    root = fixture_root()
    build_research(registry_dir=root / "company_registry", financial_dir=root / "financial_data", estimate_dir=root / "estimate_data", market_dir=root / "market_data", valuation_dir=root / "valuation_data", output_dir=tmp_path, write=True)
    row = json.loads((tmp_path / "company_research.json").read_text())[0]
    assert "financial_fact:demo:ocf" in row["source_record_ids"]
    assert "market_observation:demo:price" in row["source_record_ids"]


def test_missing_layer_yields_partial_and_diagnostic(tmp_path):
    root = fixture_root()
    missing = tmp_path / "missing"; missing.mkdir()
    report = build_research(registry_dir=root / "company_registry", financial_dir=root / "financial_data", estimate_dir=missing, market_dir=root / "market_data", valuation_dir=root / "valuation_data", output_dir=tmp_path / "out", write=True)
    assert report["partial"] == 1
    diagnostics = json.loads((tmp_path / "out" / "diagnostics.json").read_text())
    assert any(row["code"] == "missing_estimates_layer" for row in diagnostics)


def test_validate_bundle(tmp_path):
    root = fixture_root()
    build_research(registry_dir=root / "company_registry", financial_dir=root / "financial_data", estimate_dir=root / "estimate_data", market_dir=root / "market_data", valuation_dir=root / "valuation_data", output_dir=tmp_path, write=True)
    assert validate_research(tmp_path)["valid"] is True


def test_unknown_company_is_rejected(tmp_path):
    root = fixture_root()
    with pytest.raises(ResearchEngineError):
        build_research(registry_dir=root / "company_registry", financial_dir=root / "financial_data", estimate_dir=root / "estimate_data", market_dir=root / "market_data", valuation_dir=root / "valuation_data", company="NOPE")


def test_partial_valuation_changes_bundle_status_and_adds_diagnostic(tmp_path):
    root = fixture_root()
    report = build_research(registry_dir=root / "company_registry", financial_dir=root / "financial_data", estimate_dir=root / "estimate_data", market_dir=root / "market_data", valuation_dir=root / "valuation_data", output_dir=tmp_path, write=True)
    assert report["completed"] == 0
    assert report["partial"] == 1
    diagnostics = json.loads((tmp_path / "diagnostics.json").read_text())
    row = next(item for item in diagnostics if item["code"] == "valuation_scenarios_incomplete")
    assert row["details"]["scenarios"] == ["bear", "base", "bull"]


def test_shares_mismatch_adds_diagnostic_and_penalty(tmp_path):
    root = fixture_root()
    build_research(registry_dir=root / "company_registry", financial_dir=root / "financial_data", estimate_dir=root / "estimate_data", market_dir=root / "market_data", valuation_dir=root / "valuation_data", output_dir=tmp_path, write=True)
    diagnostics = json.loads((tmp_path / "diagnostics.json").read_text())
    mismatch = next(item for item in diagnostics if item["code"] == "shares_outstanding_mismatch")
    assert mismatch["details"]["financial_diluted_shares"] == "1000"
    assert mismatch["details"]["market_shares_outstanding"] == "1.4995E+10"
    bundle = json.loads((tmp_path / "company_research.json").read_text())[0]
    assert bundle["confidence"]["components"]["quality_penalty"] == -10
