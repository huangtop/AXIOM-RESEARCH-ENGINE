from __future__ import annotations

import json
from pathlib import Path

import pytest

from axiom_engine.coverage_policy import (
    CoveragePolicyError,
    CoveragePolicyService,
    CoveragePublicationDenied,
    build_coverage_policy,
    write_coverage_policy,
)


ROOT = Path(__file__).resolve().parents[1]


def _write(root: Path, relative: str, payload) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(tmp_path: Path) -> Path:
    policy = json.loads((ROOT / "config/coverage_policy.v031f.2.1.json").read_text())
    _write(tmp_path, "config/coverage_policy.v031f.2.1.json", policy)
    companies = [{"company_id": f"company:{name}", "display_name": name} for name in ("core", "chain", "pending", "context", "fund")]
    securities = [
        {"company_id": f"company:{name}", "ticker": name.upper(), "primary_listing": True}
        for name in ("core", "chain", "pending", "context", "fund")
    ]
    securities.append({"company_id": "company:core", "ticker": "CORE.B", "primary_listing": False, "status": "active"})
    _write(tmp_path, "data/universe/companies.json", companies)
    _write(tmp_path, "data/universe/securities.json", securities)
    _write(tmp_path, "data/generated/security_identity/security_identity_normalization.json", {"companies": [
        {"company_id": f"company:{name}", "valuation_scope_status": "excluded" if name == "fund" else "included", "reason_code": "NON_COMPANY_INSTRUMENT_ONLY" if name == "fund" else "COMMON_OR_ORDINARY_EQUITY_PRESENT"}
        for name in ("core", "chain", "pending", "context", "fund")
    ]})
    records = []
    for name in ("core", "chain", "pending", "context", "fund"):
        decisions = {action: {"enabled": False} for action in ("news", "etf", "supply_chain", "deep_research")}
        if name == "core": decisions["news"]["enabled"] = True
        if name == "chain": decisions["supply_chain"]["enabled"] = True
        records.append({
            "company_id": f"company:{name}",
            "research_universe_status": "eligible_not_selected" if name == "pending" else "not_eligible",
            "research_relevance": {"status": "evidence_required", "reason_code": "TEST"},
            "decisions": decisions,
            "evidence_summary": {"business_evidence_ids": [f"evidence:{name}"]},
        })
    _write(tmp_path, "data/generated/research_eligibility/research_eligibility.json", {"records": records})
    _write(tmp_path, "data/generated/full_market_coverage/full_market_coverage.json", {"cards": []})
    _write(tmp_path, "data/generated/canonical_etf_exposure/etf_exposures.json", [{"company_id": "company:context"}])
    return tmp_path


def test_coverage_tiers_are_derived_independently(tmp_path: Path):
    report = build_coverage_policy(_fixture(tmp_path))
    records = {row["company_id"]: row for row in report["records"]}
    assert records["company:core"]["research_scope"] == "core"
    assert records["company:chain"]["research_scope"] == "coverage"
    assert records["company:pending"]["research_scope"] == "candidate"
    assert "company:context" not in records
    assert records["company:fund"]["product_scope"] == "excluded"
    assert report["summary"]["default_basic_market_company_count"] == 1
    assert report["contract"]["unlisted_operating_company_default_tier"] == "basic_market"
    assert records["company:core"]["scope_axes"]["news_ai"] is True
    assert records["company:chain"]["scope_axes"]["supply_chain_analysis"] is True


def test_non_company_instrument_never_gets_page_or_valuation(tmp_path: Path):
    report = build_coverage_policy(_fixture(tmp_path))
    record = next(row for row in report["records"] if row["company_id"] == "company:fund")
    assert record["publication"] == {"company_page": False, "valuation_card": False, "visibility": "none"}
    assert record["valuation"]["scope_status"] == "not_applicable"


def test_sparse_service_resolves_contextual_default_as_basic_market(tmp_path: Path):
    root = _fixture(tmp_path)
    report = build_coverage_policy(root)
    output = root / "data/generated/coverage_policy/coverage_policy.json"
    write_coverage_policy(report, output)
    service = CoveragePolicyService(root=root)
    assert service.get("CORE")["research_scope"] == "core"
    assert service.get("CORE.B")["research_scope"] == "core"
    assert service.get("CORE-B")["research_scope"] == "core"
    assert service.get("CONTEXT")["publication_tier"] == "basic_market"
    assert service.require_public("CONTEXT")["publication"]["valuation_card"] is True
    with pytest.raises(CoveragePublicationDenied):
        service.require_public("FUND")


def test_policy_rejects_ticker_membership(tmp_path: Path):
    root = _fixture(tmp_path)
    path = root / "config/coverage_policy.v031f.2.1.json"
    policy = json.loads(path.read_text())
    policy["symbols"] = ["NVDA"]
    path.write_text(json.dumps(policy))
    with pytest.raises(CoveragePolicyError, match="membership is forbidden"):
        build_coverage_policy(root)


def test_real_projection_preserves_key_identity_and_scope_contracts():
    report = build_coverage_policy(ROOT)
    by_ticker = {row["ticker"]: row for row in report["records"] if row.get("ticker")}
    assert report["summary"]["company_count"] == 6464
    assert report["summary"]["explicit_record_count"] < report["summary"]["company_count"]
    assert by_ticker["MU"]["research_scope"] == "core"
    assert by_ticker["TSLA"]["research_scope"] == "core"
    assert by_ticker["SKHY"]["research_scope"] == "candidate"
    assert report["summary"]["public_valuation_card_count"] == 5851
    assert report["summary"]["research_page_count"] == 80
    assert report["contract"]["etf_exposure_determines_tier"] is False
    assert report["contract"]["valuation_readiness_determines_research_scope"] is False
