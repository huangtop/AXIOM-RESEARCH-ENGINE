from __future__ import annotations

import json
from pathlib import Path

import pytest

from axiom_engine.classification_population import ClassificationPopulationError, build_research_relevance_gate


ROOT = Path(__file__).resolve().parents[1]


def _write(root: Path, relative: str, payload) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(tmp_path: Path) -> Path:
    policy = json.loads((ROOT / "config/research_relevance_gate.v031c.5.json").read_text())
    _write(tmp_path, "config/research_relevance_gate.v031c.5.json", policy)
    _write(tmp_path, "data/universe/companies.json", [
        {"company_id":"company:bank"}, {"company_id":"company:shoe"}, {"company_id":"company:crypto"}, {"company_id":"company:override"}
    ])
    _write(tmp_path, "data/generated/canonical_company_evidence/official_classifications.json", [
        {"company_id":"company:bank","classification_scheme":"SEC_SIC","classification_code":"6021","classification_label":"National Commercial Banks"},
        {"company_id":"company:shoe","classification_scheme":"SEC_SIC","classification_code":"3021","classification_label":"Footwear"},
        {"company_id":"company:crypto","classification_scheme":"SEC_SIC","classification_code":"6199","classification_label":"Finance Services"},
        {"company_id":"company:override","classification_scheme":"SEC_SIC","classification_code":"6021","classification_label":"National Commercial Banks"}
    ])
    _write(tmp_path, "data/generated/company_signals/company_signals.json", {"records":[{
        "company_id":"company:override","signals":[{"signal_id":"technology:blockchain","dimension":"technology"}]
    }]})
    return tmp_path


def test_sic_gate_deprioritizes_traditional_companies_and_keeps_crypto(tmp_path: Path):
    report = build_research_relevance_gate(_fixture(tmp_path))
    records = {row["company_id"]: row for row in report["records"]}
    assert records["company:bank"]["status"] == "deprioritized_non_research"
    assert records["company:shoe"]["status"] == "deprioritized_non_research"
    assert records["company:crypto"]["upper_category"] == "fintech_and_digital_assets"
    assert records["company:crypto"]["status"] == "priority_candidate"
    assert records["company:override"]["reason_code"] == "VERIFIED_RESEARCH_SIGNAL_OVERRIDE"
    assert report["policy"]["contains_ticker_membership"] is False


def test_gate_policy_forbids_ticker_membership(tmp_path: Path):
    root = _fixture(tmp_path)
    path = root / "config/research_relevance_gate.v031c.5.json"
    policy = json.loads(path.read_text())
    policy["tickers"] = ["COIN"]
    path.write_text(json.dumps(policy))
    with pytest.raises(ClassificationPopulationError, match="membership is forbidden"):
        build_research_relevance_gate(root)


def test_real_gate_covers_full_registry_and_expected_sic_examples():
    report = build_research_relevance_gate(ROOT)
    assert report["summary"]["company_count"] == 6464
    records = {row["company_id"]: row for row in report["records"]}
    assert records["company:US-CIK0000831001"]["upper_category"] == "traditional_banking"
    assert records["company:US-CIK0000320187"]["upper_category"] == "apparel_and_footwear"
    assert records["company:US-CIK0001679788"]["upper_category"] == "fintech_and_digital_assets"
