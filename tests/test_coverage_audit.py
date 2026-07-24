from __future__ import annotations

import json
from pathlib import Path

from axiom_engine.coverage_audit import build_coverage_audit, validate_coverage_audit


FIXTURE = Path(__file__).parents[1] / "examples" / "coverage_audit_fixture"


def test_build_coverage_audit(tmp_path: Path) -> None:
    result = build_coverage_audit(
        registry_path=FIXTURE / "company_registry",
        financial_path=FIXTURE / "financial_data",
        estimate_path=FIXTURE / "estimate_data",
        market_path=FIXTURE / "market_data",
        valuation_path=FIXTURE / "valuation_data",
        research_path=FIXTURE / "research_data",
        output_dir=tmp_path,
        write=True,
    )
    assert result == {
        "valid": True,
        "company_count": 3,
        "ready": 1,
        "partial": 1,
        "blocked": 1,
        "output_dir": str(tmp_path),
    }
    report = json.loads((tmp_path / "coverage_report.json").read_text())
    assert report["coverage"]["revenue"]["covered"] == 2
    assert report["valuation_eligibility"]["eligible"] == 1


def test_company_readiness_reasons(tmp_path: Path) -> None:
    build_coverage_audit(
        registry_path=FIXTURE / "company_registry",
        financial_path=FIXTURE / "financial_data",
        market_path=FIXTURE / "market_data",
        valuation_path=FIXTURE / "valuation_data",
        output_dir=tmp_path,
        write=True,
    )
    readiness = json.loads((tmp_path / "company_readiness.json").read_text())["companies"]
    by_ticker = {item["ticker"]: item for item in readiness}
    assert by_ticker["AAPL"]["status"] == "ready"
    assert by_ticker["MSFT"]["status"] == "partial"
    assert "shares_outstanding" in by_ticker["MSFT"]["missing_inputs"]
    assert by_ticker["DEMO"]["status"] == "blocked"


def test_validate_coverage_audit(tmp_path: Path) -> None:
    build_coverage_audit(
        registry_path=FIXTURE / "company_registry",
        financial_path=FIXTURE / "financial_data",
        estimate_path=FIXTURE / "estimate_data",
        market_path=FIXTURE / "market_data",
        valuation_path=FIXTURE / "valuation_data",
        research_path=FIXTURE / "research_data",
        output_dir=tmp_path,
        write=True,
    )
    validation = validate_coverage_audit(tmp_path)
    assert validation["valid"] is True
    assert validation["company_count"] == 3


def test_missing_registry_is_invalid(tmp_path: Path) -> None:
    result = build_coverage_audit(registry_path=tmp_path / "missing")
    assert result["valid"] is False
    assert result["company_count"] == 0
